# Surreal Golden Queries Review

Status: approved for Phase 40 harness check-in

- Query count: 16
- Category coverage: 2 rows each for `title-heavy`, `tag-heavy`, `body-heavy`, `semantic`, `graph-entity`, `hybrid`, `source-ref`, and `mixed-ru-en`
- Broad queries: none in the checked-in corpus
- Intentional accepted ambiguity: none in the checked-in corpus; acceptance metadata is reserved for later evaluation runs

## Category Matrix

| Category | Query IDs | Count | Primary refs |
|----------|-----------|-------|--------------|
| `title-heavy` | `sq-001`, `sq-002` | 2 | eyeglasses voicenote, tmux clipboard thread |
| `tag-heavy` | `sq-003`, `sq-004` | 2 | Jarvis integration notes |
| `body-heavy` | `sq-005`, `sq-006` | 2 | vibe-coding meeting transcript, podcast/internalization note |
| `semantic` | `sq-007`, `sq-008` | 2 | gbrain memory/graph thread, SurrealDB overview |
| `graph-entity` | `sq-009`, `sq-010` | 2 | Дмитрий Тимошин transcript, Сергей Хабаров transcript |
| `hybrid` | `sq-011`, `sq-012` | 2 | gbrain graph/metadata thread, SurrealDB overview |
| `source-ref` | `sq-013`, `sq-014` | 2 | exact repo-url thread, exact-title voicenote |
| `mixed-ru-en` | `sq-015`, `sq-016` | 2 | Jarvis/YouTube note, SurrealDB overview |

## Rationale by Category

- `title-heavy`: both rows use distinctive title or heading text that should resolve to one intended document ref without relying on deep transcript/body context.
- `tag-heavy`: the Jarvis notes carry frontmatter tags (`Jarvis`, `подкаст`) that are stronger than generic body language and are already indexed under the active baseline.
- `body-heavy`: both rows target phrases that live in the document body rather than the short title.
- `semantic`: these rows use abstract wording such as "structured metadata" and "context layer for AI agents" to prefer meaning-based retrieval.
- `graph-entity`: both rows are person-name lookups that currently surface transcripts through entity-aware retrieval.
- `hybrid`: these rows combine lexical and conceptual evidence and currently surface results with multiple local engines.
- `source-ref`: both rows are used to confirm that the chosen `filesystem:/mnt/...` ref points to the intended readable document, not only a semantically related neighbor.
- `mixed-ru-en`: each query intentionally mixes English product terms with Russian surrounding intent to keep bilingual retrieval quality visible.

## Evidence Ledger

Each row below was grounded in the active old-stack baseline via a live `dotmd search ...`
probe against the running `dotmd` container, plus captured read evidence from
`docker exec dotmd sed -n` on the target file when the anchor text needed a body check.

| Query ID | Query | Ref | Baseline evidence | Read evidence |
|----------|-------|-----|-------------------|---------------|
| `sq-001` | `глубина резкости` | `filesystem:/mnt/knowledgebase/voicenotes/20250330-1646-N1RvC7ox/transcript.md` | `dotmd search --mode keyword --no-rerank --no-expand -n 3 "глубина резкости"` returned this ref as the only active filesystem hit. | Frontmatter/title plus body line: `глубина резкости комфортная с 40 до 60 сантиметров`. |
| `sq-002` | `Ctrl+B M статус-лайн` | `filesystem:/mnt/knowledgebase/llm-chats/perplexity/Dev - tmux/491a48c7-e136-4e71-98db-9a23c429103d.md` | `dotmd search --mode keyword --no-rerank --no-expand -n 3 "статус лайн"` returned this ref in the top local slots. | Captured heading/body anchor: `Показать статус мыши в статус-лайне`. |
| `sq-003` | `Jarvis` | `filesystem:/mnt/knowledgebase/voicenotes/20250802-1302-VFZ4Bt5e/transcript.md` | `dotmd search --mode keyword --no-rerank --no-expand -n 3 Jarvis` returned this ref as rank 1 local filesystem hit. | Frontmatter confirms `tags: [Jarvis]`; title is `Идея для интеграции Jarvis и Perplexity`. |
| `sq-004` | `Jarvis YouTube` | `filesystem:/mnt/knowledgebase/voicenotes/20250804-1845-QjP27Uu1/transcript.md` | `dotmd search --mode hybrid --no-rerank --no-expand -n 3 "Jarvis YouTube подкаст"` returned this ref as rank 1 filesystem hit. | Frontmatter confirms `tags: [Jarvis, подкаст]`; title is `Транскрипция вебинаров и подкастов из YouTube`. |
| `sq-005` | `быстрый дофаминовый цикл` | `filesystem:/mnt/knowledgebase/voicenotes/20260218-0858-U5PQp7Gi/transcript.md` | `dotmd search --mode keyword --no-rerank --no-expand -n 3 "быстрый дофаминовый цикл"` returned this ref as the top hit. | Body anchor captured from transcript: `появился быстрый дофаминовый цикл`. |
| `sq-006` | `интернализация обучение` | `filesystem:/mnt/knowledgebase/voicenotes/20250921-2122-H4n43FMk/transcript.md` | `dotmd search --mode keyword --no-rerank --no-expand -n 3 "интернализация обучение"` returned this ref as the only active filesystem hit. | Body anchor: `Дорофеев говорит про интернализацию`. |
| `sq-007` | `build link graph structured metadata` | `filesystem:/mnt/knowledgebase/llm-chats/perplexity/cbc82bdb-5882-4496-a4de-f5c0ff2d2b3a.md` | `dotmd search --mode semantic --no-rerank --no-expand -n 3 "build link graph structured metadata"` returned this ref in all top slots. | Captured body anchor: `extract structured data` / `build link graph`. |
| `sq-008` | `context layer for AI agents database` | `filesystem:/mnt/knowledgebase/llm-chats/perplexity/ce9298ca-0010-42e9-a452-c9afb49c5b25.md` | `dotmd search --mode semantic --no-rerank --no-expand -n 3 "context layer for AI agents database"` returned this ref at rank 1. | Captured body anchor: `SurrealDB is the context layer for AI agents`. |
| `sq-009` | `Дмитрий Тимошин` | `filesystem:/mnt/knowledgebase/voicenotes/20260218-0858-U5PQp7Gi/transcript.md` | `dotmd search --mode graph --no-rerank --no-expand -n 3 "Дмитрий Тимошин"` returned this ref with local engine evidence. | Frontmatter participants include `Дмитрий Тимошин`; transcript body repeats the name. |
| `sq-010` | `Сергей Хабаров` | `filesystem:/mnt/knowledgebase/voicenotes/20260127-1620-cDSsrRHS/transcript.md` | `dotmd search --mode graph --no-rerank --no-expand -n 3 "Сергей Хабаров"` returned this ref at rank 1 with `graph_direct, keyword`. | Frontmatter title and tags both contain `Сергей Хабаров`. |
| `sq-011` | `structured metadata graph` | `filesystem:/mnt/knowledgebase/llm-chats/perplexity/cbc82bdb-5882-4496-a4de-f5c0ff2d2b3a.md` | `dotmd search --mode hybrid --no-rerank --no-expand -n 3 "structured metadata graph"` returned this ref across the top local slots. | Captured body anchor: `raw content → extraction/normalization → structured metadata → graph write → hybrid retrieval`. |
| `sq-012` | `SurrealDB vectors graph` | `filesystem:/mnt/knowledgebase/llm-chats/perplexity/ce9298ca-0010-42e9-a452-c9afb49c5b25.md` | `dotmd search --mode hybrid --no-rerank --no-expand -n 3 "SurrealDB vectors graph"` returned this ref at rank 2 and as the strongest Surreal overview doc. | Captured body anchor: `One database for documents, graphs, vectors, and time-series`. |
| `sq-013` | `https://github.com/garrytan/gbrain` | `filesystem:/mnt/knowledgebase/llm-chats/perplexity/cbc82bdb-5882-4496-a4de-f5c0ff2d2b3a.md` | The live baseline search output for `https://github.com/garrytan/gbrain` mapped to this filesystem transcript rather than a remote-only result. | The file opens and begins with the exact repo URL in title and heading. |
| `sq-014` | `Интернализация и обучение через подкасты` | `filesystem:/mnt/knowledgebase/voicenotes/20250921-2122-H4n43FMk/transcript.md` | Exact-title lookup is intended as a source-ref round-trip to the short voicenote document. | Frontmatter title exactly matches the query. |
| `sq-015` | `Jarvis YouTube подкаст` | `filesystem:/mnt/knowledgebase/voicenotes/20250804-1845-QjP27Uu1/transcript.md` | `dotmd search --mode hybrid --no-rerank --no-expand -n 3 "Jarvis YouTube подкаст"` returned this ref at rank 1 with `graph_direct, keyword, semantic`. | Title/body anchor mentions both `Jarvis` and `YouTube`, plus frontmatter tag `подкаст`. |
| `sq-016` | `SurrealDB вектора graph` | `filesystem:/mnt/knowledgebase/llm-chats/perplexity/ce9298ca-0010-42e9-a452-c9afb49c5b25.md` | `dotmd search --mode hybrid --no-rerank --no-expand -n 3 "SurrealDB вектора graph"` returned this ref at rank 1. | Captured body anchor: `One database for documents, graphs, vectors, and time-series`. |

## Notes

- The active baseline currently emits unrelated Telegram/Gmail federated rows for some short tag queries. Those were not used as corpus anchors because Phase 40 needs stable local `filesystem:/mnt/...` refs.
- The review ledger deliberately records either a live local hit or explicit captured file evidence for every checked-in label so later acceptance decisions do not depend on unstated filesystem reads.
