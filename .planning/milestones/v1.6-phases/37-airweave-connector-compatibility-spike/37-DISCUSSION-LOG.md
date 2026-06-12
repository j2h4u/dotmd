# Phase 37: Airweave connector compatibility spike - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-11
**Phase:** 37-airweave-connector-compatibility-spike
**Areas discussed:** Pilot connector choice, Spike depth, SourceAsset scope, AIR-02 report format

---

## Pilot Connector Choice

| Option | Description | Selected |
|--------|-------------|----------|
| GitHub (public repo, no auth) | Issues → SourceDocument, comments → SourceUnit. No credentials needed. | |
| Enron email dataset (static) | No live API, offline, CI-safe. Not representative of SaaS auth. | |
| Linear (OAuth, in repo) | Rich entity model. Requires OAuth token. | |
| Synthetic stub | Fake BaseSource mimicking generate_entities() output. Zero auth. | |
| *(initial options)* | User pointed out there are 50+ connectors in the repo. | |
| Gmail | OAuth with refresh. Thread→SourceDocument, Message→SourceUnit, Attachment→SourceAsset. | ✓ |

**User's choice:** Gmail (freeform: "давай Gmail")
**Notes:** User was unsatisfied with the initial 4-option list as it didn't show the full connector catalog (50+ sources). After seeing the full list with auth complexity / entity type / cursor coverage breakdown, user picked Gmail. Follow-up discussion revealed the user's broader intent: prove that **any** Airweave connector can be plugged into dotMD — Gmail is the test subject, not the end goal.

---

## Spike Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Fixtures only (no live Gmail) | Build bridge, test with static entity fixtures. No OAuth, CI-safe. | |
| Live OAuth, real Gmail inbox | Set up Google OAuth, call generate_entities() against real inbox. | ✓ |
| Replay captured output | Capture one live session, replay as fixture. OAuth once, then CI-safe. | |

**User's choice:** Live OAuth, real Gmail inbox

**Follow-up — Auth setup:**

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, have credentials already | Cloud project exists, Gmail API enabled. | |
| No, need to create them | Create Cloud project + OAuth credentials as part of spike. | ✓ |
| Reuse existing Google auth | Another project's auth setup on the server. | |

**User's choice:** Need to create credentials

**Follow-up — Which Gmail account:**

| Option | Description | Selected |
|--------|-------------|----------|
| Personal Gmail (main account) | Real email data, most realistic. Read-only OAuth scopes. | ✓ |
| Dedicated test account | Separate account for spike. More controlled. | |
| Your call | Decide during execution. | |

**User's choice:** Personal Gmail

**Notes on spike direction shift:** During the scope-limit question ("how many threads?"), user redirected: "с Gmail я бы предпочёл попробовать федерированный поиск" (I'd prefer federated search). This changed the spike from local indexing (generate_entities → SourceDocument/SourceUnit → SQLite) to **federated search** (GmailSource.search() → SearchCandidate, live at query time). No embedding, no FTS5, no graph. Mirrors Telegram native FTS pattern.

**Follow-up — Bridge reuse vs. direct API:**

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse GmailSource.search() from Airweave directly | Import airweave, call GmailSource.search(), convert BaseEntity → SearchCandidate. | ✓ |
| Mirror the approach, call Gmail API directly | Like mcp-telegram — no Airweave import. | |
| Either works, planner decides | Mapping analysis matters more than import strategy. | |

**User's choice:** Reuse GmailSource.search() directly
**Notes:** User stated: "I'm planning to use any Airweave connector in our project in general, so I need to check how all this will work." This confirms the generic bridge goal.

**Follow-up — Airweave dependency:**

| Option | Description | Selected |
|--------|-------------|----------|
| pip install airweave | Direct package dependency. May pull heavy transitive deps. | |
| Cherry-pick / vendor connector modules | Copy platform/sources/, entities/, configs/. No pip dep. | ✓ (preferred) |
| Researcher decides | Check import graph and recommend. | |

**User's choice:** Vendor (cherry-pick), freeform: "Я предпочитаю Cherry Peek, то есть вариант номер два. Но если вдруг внезапно окажется, что можно взять первый вариант и не будет никаких тяжёлых зависимостей, то в принципе это тоже неплохо." (Prefer vendoring. But if pip install turns out clean with no heavy deps, that's also fine.)

---

## SourceAsset Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Define minimal SourceAsset in models.py | Add model shape, show GmailAttachmentEntity mapping. No pipeline code. | |
| Defer it, document as deferred | Spike covers SourceDocument + SourceUnit + SearchCandidate only. | ✓ |

**User's choice:** Defer
**Notes:** User initially didn't know what SourceAsset was ("Если честно, я вообще не знаю, что это такое") and asked for an expert panel. Explained in plain terms (binary attachment shape, e.g., PDF in email). After explanation, user agreed to defer — SourceAsset is noted in AIR-02 as future work mapping GmailAttachmentEntity.

---

## AIR-02 Report Format

| Option | Description | Selected |
|--------|-------------|----------|
| docs/gmail-airweave-compatibility-spike.md | Standalone markdown in docs/. Permanent reference, easily discoverable. | ✓ |
| Phase artifact in .planning/phases/37-*/ | Part of phase directory. Good for GSD continuity. | |
| Inline in bridge code as structured docstrings | Findings live in code. No separate doc. | |

**User's choice:** `docs/gmail-airweave-compatibility-spike.md`

---

## Claude's Discretion

- Exact module path for vendored Airweave subtree
- Shim implementation for `ContextualLogger` and `AirweaveHttpClient` (dataclass vs. thin wrapper)
- Gmail descriptor config schema field names and env var naming
- Whether `dotmd status` surfaces last-federated-search stats for Gmail
- Default search result limit for live Gmail queries

## Deferred Ideas

- **SourceAsset model** — future shape for binary attachments; GmailAttachmentEntity maps here
- **Local Gmail indexing** — ingesting Gmail into SQLite/FTS5/vector store; out of scope for spike
- **GmailMessageDeletionEntity handling** — deletion signals via Gmail History API; requires shim to dotMD's binding deactivation; follow-on phase
- **Multi-connector runtime** — multiple simultaneous Airweave connectors; architecture should enable it, Phase 37 validates one
- **Connector config UI** — admin UI for adding connectors; stays env/TOML-based
- **Access control** — Airweave's multi-tenant ACL; dotMD is single-user, explicitly out of scope
