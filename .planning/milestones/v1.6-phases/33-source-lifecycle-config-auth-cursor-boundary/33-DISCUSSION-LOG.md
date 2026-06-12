# Phase 33: Source lifecycle/config/auth/cursor boundary - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 33-Source lifecycle/config/auth/cursor boundary
**Areas discussed:** Airweave adaptation, runtime bundle shape, config and credential ownership, validation strictness, filesystem and Telegram migration path, cursor policy

---

## Todo Folding

| Option | Description | Selected |
|--------|-------------|----------|
| None | Treat low-confidence todo matches as unrelated backlog items. | yes |
| Soft-delete TTL | Fold the removed-source-file lifecycle note into Phase 33 context. | |
| Graph/config item | Fold graph-store/config-related notes into Phase 33 context. | |

**User's choice:** 1
**Notes:** No todos were folded. The matches were generic keyword hits and are recorded as reviewed but deferred in CONTEXT.md.

---

## Airweave Adaptation

| Option | Description | Selected |
|--------|-------------|----------|
| Airweave-lite runtime bundle | Keep lifecycle/factory ideas, adapted minimally for filesystem and Telegram. | yes |
| Even simpler | Only add a thin factory wrapper over current paths. | |
| Closer to Airweave | Design a broader connector runtime now. | |

**User's choice:** 1
**Notes:** User wanted the prior reference project used for maximum ROI. Airweave was identified as the reference, with platform-heavy pieces explicitly rejected for this phase.

---

## Runtime Bundle Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Full minimal bundle | Return descriptor, config, credential/auth provider, cursor store, provider/source object, and helpers. | yes |
| Only provider/source object | Hide config/cursor/credentials inside the constructed object. | |
| Two levels | Public simple object plus internal full bundle. | |

**User's choice:** 1
**Notes:** The bundle should stay inspectable and useful for later Phases 34-37.

---

## Config And Credential Ownership

| Option | Description | Selected |
|--------|-------------|----------|
| Local source config store | Store typed config and credential references locally; raw secrets stay behind a credential provider. | yes |
| Env/settings only | Use current env/settings paths for MVP. | |
| Descriptor metadata | Put config in descriptor metadata. | |

**User's choice:** 1
**Notes:** Descriptors remain declarative. Adapters/providers must not read raw secret storage directly.

---

## Validation Strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Fail fast at runtime creation | Missing or invalid required config/credential references prevent runtime creation. | yes |
| Lazy validation | Let runtime exist and fail only when used. | |
| Mixed mode | Validate config eagerly and credentials lazily. | |

**User's choice:** 1
**Notes:** Runtime construction should fail early and clearly.

---

## Filesystem And Telegram Migration Path

| Option | Description | Selected |
|--------|-------------|----------|
| Both through lifecycle immediately | Phase 33 is done only when filesystem and Telegram construction paths use lifecycle. | yes |
| Telegram first | Leave filesystem shim for a later phase. | |
| Boundary plus test shims only | Add architecture without routing real paths yet. | |

**User's choice:** 1
**Notes:** The lifecycle boundary must be proven with real construction paths, not only test-only shims.

---

## Cursor Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Write CONTEXT.md | Carry forward existing checkpoint cursor policy as locked. | yes |
| Discuss cursor failure behavior | Reopen retry/error/partial batch behavior. | |
| Another Airweave pass | Recheck Airweave for missed high-ROI pieces. | |

**User's choice:** 1
**Notes:** Phase 28 already settled that `checkpoint_cursor` is durable progress and `next_cursor` is not. No further discussion needed.

## the agent's Discretion

- Exact class/module names.
- Concrete local source config store persistence shape.
- Minimal credential provider interface details.
- Filesystem fingerprint-state representation inside the lifecycle vocabulary.

## Deferred Ideas

- Full connector marketplace.
- Production OAuth UI for arbitrary SaaS apps.
- Rate-limit framework and broader SaaS runtime policy.
- Source TTL/GC cleanup from the low-confidence todo match.
