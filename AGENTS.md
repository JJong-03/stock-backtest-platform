# AGENTS.md — Codex Execution Playbook (Stock Backtesting Platform)

This file defines **operational constraints** for Codex agents working in this repository.  
The architectural constitution and all contracts live in `CLAUDE.md`.  
If anything conflicts, **`CLAUDE.md` wins**.

**Active Phase: read `CLAUDE.md §2 Project Status` and find the line explicitly labeled
`Active Phase:` (e.g. `Active Phase: Phase 1`).
Do NOT infer from table order. Use only the explicitly labeled value.**  
**If the `Active Phase:` line is missing, STOP and request it to be added to `CLAUDE.md §2`. Do NOT proceed.**  
(Phase details, deliverables, and acceptance criteria: `CLAUDE.md §8`)

---

## 0) Mandatory Pre-Flight (Checklist Only)

Before making changes, the agent MUST:
- Read `CLAUDE.md` (Strict Rules §5 + Phase Plan §8 are minimum)
- Identify the active Phase from `CLAUDE.md §2` using the line explicitly labeled `Active Phase:`
- Identify minimal files to change
- Ensure planned work does not violate the Hard Stop Rules below
- Ensure planned work is required to satisfy **current Phase deliverables/AC** (avoid scope creep)

No specific output format is required. The checklist exists to prevent scope drift.

---

## 1) Hard Stop Rules (ABSOLUTE)

If a requested change violates any rule below, the agent MUST NOT proceed.

### 1.1 Engine Immutability (Rule 1)
- `backtest/engine.py` is IMMUTABLE.
- Do not edit, reformat, move, or "minor fix" it.
- Do not change engine trading logic, signal generation, or internal formulas.
- Enhancements must use wrapper/adapter pattern (`adapters/`, controller, worker).

Forbidden:
- Editing engine's loop to track peak equity
- Changing Sharpe/returns formula inside engine
- Adding new outputs directly inside engine

Allowed:
- Derive drawdown from `equity_curve` in adapter
- Compute win_rate from `trades` in adapter
- Render charts (Matplotlib Agg) in adapter

### 1.2 API Contracts are Additive-Only (Rule 2)
- Existing JSON fields MUST NOT be removed, renamed, or have meaning changed.
- New fields MUST be optional OR have defaults.
- Backward compatibility is mandatory.

### 1.3 Stateless Web (Rule 4)
- Web tier MUST NOT write files (no `/tmp`, no saved PNGs, no cached artifacts).
- Charts/images must be created in-memory and returned as Base64.
- Persistent state lives in DB only (SQLite local dev exception; MySQL in K8s/prod).

### 1.4 Matplotlib Server-Safe (Rule 5)
- `matplotlib.use("Agg")` before importing pyplot.
- Always `plt.close(fig)` after saving to buffer.

### 1.5 Error Handling Discipline (Rule 6)
- user_error → HTTP 400
- system_error → HTTP 500
- No stack traces returned to user (log only).

### 1.6 Config & Secrets (Rule 7)
- Config via env vars only.
- `.env.example` may be committed; real `.env` must not.
- Repository contains `k8s/secret-template.yaml` only; real secrets must not be committed.
- `.gitignore` must block `k8s/secret.yaml`, `strategies.db`.

### 1.7 Observability (Rule 8)
- Every backtest request MUST have `run_id` (UUID4).
- Every log line MUST include `[run_id=...]`.
- Logging to stdout/stderr only (no file logging).

### 1.8 DB Session Safety (Rule 9)
- Wrap `db.session.commit()` in try/except.
- On exception: `db.session.rollback()`.
- Separate `IntegrityError` vs general `Exception`.
- No automatic `db.create_all()` in production/K8s (local dev only under `if __name__ == "__main__":`).

### 1.9 Immutable Image Tags (Rule 10)
- Never deploy `:latest`.
- Tag images with `:<git-sha-short>` (or semver).
- Never overwrite same tag.

---

## 2) Execution Context (ROOT ONLY)

All commands must run from repository root. Do not `cd` into subdirs.

✅ Correct
- `pytest -q`
- `python -m flask run`
- `python scripts/verify_mvp.py`
- `docker build -t stock-backtest .`

❌ Wrong
- `cd scripts && python verify_mvp.py`

---

## 3) Git / Branch Guidance

Codex may not have push or PR permissions. Therefore:
- Prefer `feature/<topic>` branch names when proposing changes.
- Do not assume direct pushes to `dev` or `main`.
- Provide clear file diffs so a developer can apply and commit safely.

---

## 4) Phase Discipline

Codex MUST stay within the active Phase scope.

**Active Phase source of truth:** the line labeled `Active Phase:` in `CLAUDE.md §2 Project Status`

Codex MUST:
- Implement only the deliverables listed for the current Phase in `CLAUDE.md §8`
- Not implement features belonging to future Phases
- Verify acceptance criteria from `CLAUDE.md §8` before considering work complete

---

## 5) Web vs Worker Boundary

Web vs Worker responsibility boundary is defined in `CLAUDE.md §3`.  
Codex MUST follow it. Do not implement Worker logic in Web, or vice versa.

---

## 6) Contracts & Operational Policies (Single Source of Truth)

The following are defined ONLY in `CLAUDE.md` and MUST NOT be duplicated here:
- Runtime state machine, timestamps, failure classification
- Persistence boundaries (canonical vs derived)
- Reproducibility identifiers
- RBAC restrictions and Job lifecycle policies
- GitOps deployment flow

Reference sections (by CLAUDE.md headings; do not paraphrase or re-specify here):
- **Runtime & Data Contracts (Phase 2+)**
  - Run Execution Contract (State Machine, Timestamps, Failure Classification)
  - Reproducibility Guarantees
  - Result Persistence Boundaries
  - Job Lifecycle & Auditability
- **Web vs Worker Responsibility Boundary**
- **GitOps Deployment Flow (CI vs CD)**
- **Phase Plan — Platform Completion** (Phase 1–6 deliverables/AC)

---

## 7) Always-Allowed vs Always-Forbidden

These apply regardless of active Phase.

Always allowed **only when required to satisfy current Phase deliverables/AC and Rule-compliant**:
- Adapter-layer metric derivation and visualization (Rule 1)
- Logging improvements (Rule 8)
- Additive schema extensions (Rule 2)
- Phase-aligned infrastructure files

Always forbidden:
- Any engine trading logic modification (Rule 1)
- Breaking API schema changes (Rule 2)
- Web local file writes (Rule 4)
- File logging (Rule 8)
- `:latest` image tags (Rule 10)
- Hardcoded secrets committed to repo (Rule 7)

---

## 8) Completion Notes

When finishing a task:

**Required (minimum):**
- List of files changed

**Include where available/appropriate:**
- Why each file was changed
- Commands run and their results (if execution is available)
- Which strict rules were checked and how