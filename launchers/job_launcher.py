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

# Optional worker env vars shared by both launchers.  (env_key, payload_key)
_OPTIONAL_ENV_FIELDS = (
    ("INITIAL_CAPITAL", "initial_capital"),
    ("FEE_RATE", "fee_rate"),
    ("SLIPPAGE_BPS", "slippage_bps"),
    ("POSITION_SIZE", "position_size"),
    ("SIZE_TYPE", "size_type"),
    ("DIRECTION", "direction"),
    ("TIMEFRAME", "timeframe"),
)

# OS / runtime keys forwarded to the subprocess in LOCAL mode.
_SUBPROCESS_PASSTHROUGH_KEYS = (
    "PATH",
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "LANG",
    "LC_ALL",
    "DATABASE_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "LOG_LEVEL",
)


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
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cwd = cwd or project_root
        self.worker_script = worker_script or os.path.join(project_root, "worker.py")

    def launch(self, run_payload: Dict[str, Any]) -> None:
        env: Dict[str, str] = {}
        for key in _SUBPROCESS_PASSTHROUGH_KEYS:
            if key in os.environ:
                env[key] = os.environ[key]

        env.update(
            {
                "RUN_ID": _stringify(run_payload.get("run_id")),
                "TICKER": _stringify(run_payload.get("ticker")),
                "RULE_TYPE": _stringify(run_payload.get("rule_type")),
                "PARAMS_JSON": _stringify(run_payload.get("params_json")),
                "START_DATE": _stringify(run_payload.get("start_date")),
                "END_DATE": _stringify(run_payload.get("end_date")),
            }
        )

        for env_key, payload_key in _OPTIONAL_ENV_FIELDS:
            val = run_payload.get(payload_key)
            if val is not None:
                env[env_key] = _stringify(val)

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
        except Exception as in_cluster_exc:
            try:
                config.load_kube_config()
            except Exception as kube_exc:
                raise RuntimeError(
                    f"Kubernetes configuration failed. "
                    f"In-cluster config error: {in_cluster_exc}; "
                    f"kubeconfig error: {kube_exc}"
                ) from kube_exc

        self._k8s_client = client
        self._api = client.BatchV1Api()

    def launch(self, run_payload: Dict[str, Any]) -> None:
        # python 객체로 job 스펙 조립 (yaml 템플릿 대신 코드로 작성하여 유연성↑)

        client = self._k8s_client

        env = [
            client.V1EnvVar(name="RUN_ID", value=_stringify(run_payload.get("run_id"))),
            client.V1EnvVar(name="TICKER", value=_stringify(run_payload.get("ticker"))),
            client.V1EnvVar(name="RULE_TYPE", value=_stringify(run_payload.get("rule_type"))),
            client.V1EnvVar(name="PARAMS_JSON", value=_stringify(run_payload.get("params_json"))),
            client.V1EnvVar(name="START_DATE", value=_stringify(run_payload.get("start_date"))),
            client.V1EnvVar(name="END_DATE", value=_stringify(run_payload.get("end_date"))),
        ]

        for env_key, payload_key in _OPTIONAL_ENV_FIELDS:
            val = run_payload.get(payload_key)
            if val is not None:
                env.append(client.V1EnvVar(name=env_key, value=_stringify(val)))

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
            image=self.worker_image,            # 같은 이미지 재사용
            image_pull_policy="IfNotPresent",   # Phase 4에서 GHCR:<git-sha>로 전환 예정
            command=["python", "worker.py"],    # worker.py 실행 (컨테이너 내에서 worker.py가 존재한다고 가정)
            env=env,
            env_from=[
                client.V1EnvFromSource(
                    config_map_ref=client.V1ConfigMapEnvSource(name=self.configmap_name) # DB 접속 정보 등 일반 설정
                ),
                client.V1EnvFromSource(
                    secret_ref=client.V1SecretEnvSource(name=self.secret_name)           # DB 비밀번호 등 민감 정보
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
                body=self._k8s_client.V1DeleteOptions(propagation_policy="Background"),
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
