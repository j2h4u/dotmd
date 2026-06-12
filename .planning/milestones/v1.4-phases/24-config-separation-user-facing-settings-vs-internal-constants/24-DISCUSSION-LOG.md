# Phase 24: Config separation - user-facing settings vs internal constants - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-05-05
**Phase:** 24-config-separation-user-facing-settings-vs-internal-constants
**Areas discussed:** configuration vocabulary, deployment assumptions, tuning surface, startup smoke gate

---

## Configuration Vocabulary

| Option | Description | Selected |
|--------|-------------|----------|
| External settings | Treat env/TOML/compose values as "external" to dotMD. | |
| Operator / deployment-bound config | Treat them as dotMD config whose values are supplied from the deployment. | yes |
| Internal constants | Treat tuning values as implementation defaults rather than primary config. | yes |

**User's choice:** The user rejected the phrase "external settings" because all
settings still belong to the dotMD service.

**Notes:** Captured the clearer vocabulary: operator/deployment-bound
configuration versus internal defaults/constants.

---

## Deployment Assumptions

| Option | Description | Selected |
|--------|-------------|----------|
| Add explicit strict mode | Introduce `DOTMD_ENV=production` or similar. | |
| Infer dev/prod environments | Split behavior by local/development/production assumptions. | |
| Single live deployment | Assume one real container deployment for now. | yes |

**User's choice:** Do not introduce environment profiles or strict-mode flags in
Phase 24.

**Notes:** dotMD currently runs in one container on one server for one user who
is also the developer. Multi-environment config should wait until it is real.

---

## Tuning Surface

| Option | Description | Selected |
|--------|-------------|----------|
| Keep tuning knobs prominent | Leave values such as `fusion_k` and `snippet_length` in the main config surface. | |
| Move tuning deeper | Keep advanced tuning possible but remove it from the primary deployment checklist. | yes |
| Remove tuning entirely | Delete override paths for unused tuning values. | |

**User's choice:** Tuning knobs have not really been used; keep them deeper and
document them as advanced fine-tuning possibilities.

**Notes:** The main config docs/templates should focus on actual deployment
configuration.

---

## Startup Smoke Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Treat as internal detail | Hide the restart-time smoke gate with other implementation details. | |
| Preserve as operational safety switch | Keep and document the restart gate because continuous development makes it useful. | yes |
| Remove gate | Avoid running tests on container restart. | |
| Rename the switch | Replace misleading `ENVIRONMENT=dev` naming with a flag that names the behavior. | yes |

**User's choice:** Preserve the smoke/test gate used during container restarts.

**Notes:** Current implementation is `ENVIRONMENT=dev` in `backend/start.sh`,
which runs ruff, pyright ratchet, health startup, and live e2e smoke before the
container stays up. This is operational safety, not general environment
profiling. Preferred replacement name: `DOTMD_RUN_STARTUP_CHECKS=true`.
`DOTMD_PREFLIGHT_CHECKS=true` is acceptable, but slightly less explicit.

---

## the agent's Discretion

- Decide the smallest implementation shape for separating `Settings` from
  constants.
- Decide whether to rename or only document the `ENVIRONMENT=dev` smoke-gate
  variable after inspecting deployment compatibility.

## Deferred Ideas

- Multi-environment configuration profiles are deferred until dotMD actually
  has more than one operating environment.
