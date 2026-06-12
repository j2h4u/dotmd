# Phase 32: Source capability registry - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 32-Source capability registry
**Areas discussed:** Airweave adaptation, registry content, capability flags, schema strictness, registry/runtime boundary, Airweave mapping, seeded entries, todo handling

---

## Todo Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Soft-delete only | Fold only retention/materialization intent; leave unrelated historical matches out. | |
| All matches | Fold every keyword match, including likely noisy historical todos. | |
| None | Do not fold any pending todos into this phase context. | yes |

**User's choice:** None.
**Notes:** Keyword-matched todos were not folded into Phase 32 scope.

---

## Airweave Adaptation Mode

| Option | Description | Selected |
|--------|-------------|----------|
| Principles-first | Take Airweave's engineering categories and design a compact dotMD-native registry; document the mapping explicitly. | yes |
| Schema-close | Keep dotMD descriptors close to Airweave source schema to simplify future connector shims. | |
| Selective improvements | Classify each Airweave field individually during discussion. | |

**User's choice:** Principles-first.
**Notes:** User clarified that the earlier architecture conversation identified
Airweave ideas worth borrowing, but not copying one-to-one.

---

## Registry Content

| Option | Description | Selected |
|--------|-------------|----------|
| Capabilities + schemas | Preserve source capabilities plus config/auth/cursor schemas as the useful engineering minimum. | yes |
| Full source catalog | Include richer marketplace/card metadata such as labels, rate limits, and auth provider hints. | |
| Minimal core | Keep only kind, display name, and capability flags; defer schemas to lifecycle. | |

**User's choice:** Capabilities + schemas.
**Notes:** Phase 32 should keep the important source-catalog ideas without
turning into Airweave's full SaaS catalog.

---

## Capability Flags

| Option | Description | Selected |
|--------|-------------|----------|
| Closed enum | Fixed known flags such as sync, federated search, read windows, materialization, browse tree, ACL, and incremental cursor. | yes |
| Extensible strings | Let sources add arbitrary capability strings without model changes. | |
| Enum + experimental metadata | Keep core enum closed but allow temporary experimental metadata. | |

**User's choice:** Closed enum.
**Notes:** The closed vocabulary should prevent naming drift and keep planner
behavior deterministic.

---

## Schema Strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Structural Pydantic models | Registry uses typed schema models/objects, even when simple. | yes |
| JSON Schema-like dict | Closer to Airweave `config_fields`, easier to render but weaker inside Python. | |
| Placeholders now | Include fields but let Phase 33 define strict shape. | |

**User's choice:** Structural Pydantic models.
**Notes:** Phase 32 should leave Phase 33 a typed lifecycle foundation, not
placeholder schema bags.

---

## Registry/Runtime Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Descriptor is declarative only | Registry describes source identity, schemas, and capabilities; Phase 33 constructs runtimes. | yes |
| Descriptor includes factory hook | Registry points at runtime factory classes. | |
| Descriptor includes provider instance | Seeded entries include ready provider objects. | |

**User's choice:** Descriptor is declarative only.
**Notes:** Keep runtime construction, credentials, clients, and cursor commits
out of Phase 32.

---

## Airweave Mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit copied/adapted/rejected table | Classify important Airweave source fields by how dotMD uses them. | yes |
| Short narrative docs | Explain the ideas in prose without field-level mapping. | |
| Test fixture mapping | Add a fixture/test that converts an Airweave source example into a dotMD descriptor. | |

**User's choice:** Explicit copied/adapted/rejected table.
**Notes:** The table should also support deferred classification where a concept
belongs to a later phase.

---

## Seeded Entries

| Option | Description | Selected |
|--------|-------------|----------|
| Detailed reference entries | Filesystem and Telegram populate all descriptor/schema/capability fields and serve as examples. | yes |
| Minimal seed entries | Only mandatory fields and capability flags. | |
| Filesystem simple, Telegram detailed | Treat Telegram as the richer application-source example. | |

**User's choice:** Detailed reference entries.
**Notes:** The registry should not be a nearly empty shell; filesystem and
Telegram should be credible examples for future sources.

---

## Completion Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Write context | Decisions are enough for researcher/planner. | yes |
| Discuss edge cases | Continue with naming, empty schemas, and registry placement. | |
| Discuss Airweave deeper | Inspect more Airweave source schema and connector metadata before writing context. | |

**User's choice:** Write context.
**Notes:** Proceeded to create `32-CONTEXT.md`.

---

## Graphify Usage

**User's question:** Whether Graphify is needed, and in which phase.
**Captured answer:** Graphify is optional and useful mainly during
research/planning, not as implementation truth. Phase 32 may use it for code
navigation, but the stronger value is likely in Phases 33-36 where lifecycle,
pipeline, storage, service, filesystem, and Telegram dependencies are more
coupled. Any Graphify-derived finding must be verified against live source
files.

## the agent's Discretion

- Exact class/module/enum names.
- Exact typed schema representation, as long as it is not loose untyped dicts.
- Exact display metadata field set, as long as it stays source-descriptor
  focused and avoids marketplace bloat.
- Optional Graphify-assisted navigation during downstream research/planning,
  with live-file verification required.

## Deferred Ideas

- Phase 33 lifecycle/factory/credential/cursor runtime construction.
- Phase 34 federated search candidate implementation.
- Phase 35 filesystem unification.
- Phase 36 Telegram unified sync/federated work.
- Phase 37 Airweave connector compatibility spike.
