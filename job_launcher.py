"""Job launcher abstraction for Phase 3 Web -> Worker orchestration."""

from __future__ import annotations

import os
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict


DEFAULT_NAMESPACE = "stock-backtest"
DEFAULT_WORKER_IMAGE = "stock-web:local"
DEFAULT_CONFIGMAP_NAME = "web-config"
DEFAULT_SECRET_NAME = "web-secret"


def build_job_name(run_id: str) -> str:
    return f"worker-{run_id.replace('-', '')[:8].lower()}"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


class JobLauncher(ABC):
    mode: str = "UNKNOWN"

    @abstractmethod
    def launch(self, run_payload: Dict[str, Any]) -> None:
        """Launch a worker execution for the given run payload."""

    def delete_for_run(self, run_id: str) -> None:
        """Delete job resources for a run (optional no-op)."""


class LocalJobLauncher(JobLauncher):
    mode = "LOCAL"

    def __init__(self, worker_script: str | None = None, cwd: str | None = None):
        project_root = os.path.dirname(os.path.abspath(__file__))
        self.cwd = cwd or project_root
        self.worker_script = worker_script or os.path.join(project_root, "worker.py")

    def launch(self, run_payload: Dict[str, Any]) -> None:
        # strategy→RULE_TYPE 브릿지: rule_type 우선, 없으면 strategy fallback
        rule_type = run_payload.get("rule_type") or run_payload.get("strategy", "")


        env = os.environ.copy()
        env.update(
            {
                "RUN_ID": _stringify(run_payload.get("run_id")),
                "TICKER": _stringify(run_payload.get("ticker")),
                "RULE_TYPE": _stringify(rule_type), # rule_type이 strategy로 fallback하는 부분
                
                "PARAMS_JSON": _stringify(run_payload.get("params_json")),
                "START_DATE": _stringify(run_payload.get("start_date")),
                "END_DATE": _stringify(run_payload.get("end_date")),
                "INITIAL_CAPITAL": _stringify(run_payload.get("initial_capital", 100000)),
                "FEE_RATE": _stringify(run_payload.get("fee_rate")),
                "SLIPPAGE_BPS": _stringify(run_payload.get("slippage_bps")),
                "POSITION_SIZE": _stringify(run_payload.get("position_size")),
                "SIZE_TYPE": _stringify(run_payload.get("size_type")),
                "DIRECTION": _stringify(run_payload.get("direction")),
                "TIMEFRAME": _stringify(run_payload.get("timeframe")),
            }
        )

        subprocess.Popen(
            [sys.executable, self.worker_script],
            cwd=self.cwd,
            env=env,
            close_fds=True,
        )


class K8sJobLauncher(JobLauncher):
    mode = "K8S"

    def __init__(self):
        self.namespace = os.getenv("K8S_NAMESPACE", DEFAULT_NAMESPACE)
        self.worker_image = os.getenv("WORKER_IMAGE", DEFAULT_WORKER_IMAGE)
        self.configmap_name = os.getenv("WORKER_CONFIGMAP_NAME", DEFAULT_CONFIGMAP_NAME)
        self.secret_name = os.getenv("WORKER_SECRET_NAME", DEFAULT_SECRET_NAME)

        try:
            from kubernetes import client, config
        except ImportError as exc:
            raise RuntimeError(
                "kubernetes package is required for JOB_LAUNCHER_MODE=K8S"
            ) from exc

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()

        self._k8s_client = client
        self._api = client.BatchV1Api()

    def launch(self, run_payload: Dict[str, Any]) -> None:
        client = self._k8s_client

        env = [
            client.V1EnvVar(name="RUN_ID", value=_stringify(run_payload.get("run_id"))),
            client.V1EnvVar(name="TICKER", value=_stringify(run_payload.get("ticker"))),
            client.V1EnvVar(name="RULE_TYPE", value=_stringify(run_payload.get("rule_type"))),
            client.V1EnvVar(name="PARAMS_JSON", value=_stringify(run_payload.get("params_json"))),
            client.V1EnvVar(name="START_DATE", value=_stringify(run_payload.get("start_date"))),
            client.V1EnvVar(name="END_DATE", value=_stringify(run_payload.get("end_date"))),
            client.V1EnvVar(
                name="INITIAL_CAPITAL",
                value=_stringify(run_payload.get("initial_capital", 100000)),
            ),
        ]

        if run_payload.get("fee_rate") is not None:
            env.append(client.V1EnvVar(name="FEE_RATE", value=_stringify(run_payload.get("fee_rate"))))
        if run_payload.get("slippage_bps") is not None:
            env.append(
                client.V1EnvVar(name="SLIPPAGE_BPS", value=_stringify(run_payload.get("slippage_bps")))
            )
        if run_payload.get("position_size") is not None:
            env.append(
                client.V1EnvVar(name="POSITION_SIZE", value=_stringify(run_payload.get("position_size")))
            )
        if run_payload.get("size_type") is not None:
            env.append(client.V1EnvVar(name="SIZE_TYPE", value=_stringify(run_payload.get("size_type"))))
        if run_payload.get("direction") is not None:
            env.append(client.V1EnvVar(name="DIRECTION", value=_stringify(run_payload.get("direction"))))
        if run_payload.get("timeframe") is not None:
            env.append(client.V1EnvVar(name="TIMEFRAME", value=_stringify(run_payload.get("timeframe"))))

        metadata = client.V1ObjectMeta(
            name=build_job_name(_stringify(run_payload.get("run_id"))),
            namespace=self.namespace,
            labels={
                "app": "worker",
                "run_id": _stringify(run_payload.get("run_id")),
            },
        )

        container = client.V1Container(
            name="worker",
            image=self.worker_image,
            image_pull_policy="IfNotPresent",
            command=["python", "worker.py"],
            env=env,
            env_from=[
                client.V1EnvFromSource(
                    config_map_ref=client.V1ConfigMapEnvSource(name=self.configmap_name)
                ),
                client.V1EnvFromSource(
                    secret_ref=client.V1SecretEnvSource(name=self.secret_name)
                ),
            ],
        )

        pod_spec = client.V1PodSpec(restart_policy="Never", containers=[container])
        pod_template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": "worker", "run_id": _stringify(run_payload.get("run_id"))}),
            spec=pod_spec,
        )

        job_spec = client.V1JobSpec(
            template=pod_template,
            backoff_limit=1,
            ttl_seconds_after_finished=86400,
        )

        job = client.V1Job(api_version="batch/v1", kind="Job", metadata=metadata, spec=job_spec)

        self._api.create_namespaced_job(namespace=self.namespace, body=job)

    def delete_for_run(self, run_id: str) -> None:
        job_name = build_job_name(run_id)
        try:
            self._api.delete_namespaced_job(
                name=job_name,
                namespace=self.namespace,
                propagation_policy="Background",
            )
        except Exception as exc:
            # Swallow 404 to keep endpoint idempotent.
            status = getattr(exc, "status", None)
            if status == 404:
                return
            raise


def create_job_launcher() -> JobLauncher:
    mode = os.getenv("JOB_LAUNCHER_MODE", "LOCAL").strip().upper()
    if mode == "K8S":
        return K8sJobLauncher()
    return LocalJobLauncher()
