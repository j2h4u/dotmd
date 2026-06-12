# Phase 38 Plan 03 Retrieval Parity

## Recommendation Gate

- `recommendation_gate: fail`
- Blocking categories observed:
  - `defer: FTS weighting`
  - `reject: hybrid/RRF gap`
  - `fail: unavailable scale evidence`

This is **parity evidence**, not migration marketing. The current prototype does
not have migrate-ready retrieval parity.

## Inputs And Discipline

| Item | Value |
|---|---|
| Current-stack SQLite snapshot | `/tmp/dotmd-phase38-host-snapshot/index-phase38-host.db` |
| Snapshot provenance | copied from container snapshot `dotmd:/tmp/dotmd-phase38-snapshot/index-phase38.db` created in 38-01 |
| Surreal sample target | `/tmp/dotmd-phase38-host-snapshot/38-03-parity-surreal.db` |
| Production mutation | none |
| TEI calls | none |
| Source markdown indexing | none |
| Query embeddings | fixed; reused stored vector for chunk `e1eb5829c239c9cc6bd9a56d3e86c73a536526b4fc4b786e996a96823ee09a02` |

Representative copied sample:

- Query term: `Hiveon`
- Sample size: `15` chunks
- Construction:
  - `5` title-only matches (`title LIKE '%Hiveon%'` and body does not)
  - `5` body-only matches (`text LIKE '%Hiveon%'` and title does not)
  - `5` title+body matches

Graph-direct evidence remained fixture-backed in this plan:

- deterministic bounded `Section -> Entity/Tag -> Section` fixture
- production-derived graph sample parity was **not** established here

## Deterministic Tie Policy

Hybrid/RRF parity normalizes both baseline and Surreal candidate lists with a
stable tie-breaker:

1. fused score descending
2. `chunk_id` ascending

This tie policy is covered by `tests/search/test_surreal_retrieval_parity.py`
and is repeated through the parity harness.

## Parity Matrix

| Engine | Corpus | Current top result | Surreal top result | Top-k overlap | Status | Failure category |
|---|---|---|---|---:|---|---|
| FTS | representative copied sample (`Hiveon`, 15 chunks) | `e1eb5829...09a02` | `e1eb5829...09a02` | `0.8` | FAIL | `defer: FTS weighting` |
| Vector | representative copied sample (stored embedding query) | `e1eb5829...09a02` | `e1eb5829...09a02` | `1.0` | PASS | — |
| Graph-direct | deterministic fixture | `chunk-alpha` | `chunk-alpha` | `1.0` | PASS | — |
| Hybrid/RRF | representative copied sample (`Hiveon`, app-side RRF) | `e1eb5829...09a02` | `e1eb5829...09a02` | `1.0` | FAIL | `reject: hybrid/RRF gap` |

## FTS

Current-stack weighted FTS5 baseline (`title=5x`, `tags=3x`, `text=1x`) was
compared against a Surreal-side text-only proxy over the same imported corpus.
This is the honest comparison available from the prototype today: multi-field
weighted parity is not implemented.

Top-5 current-stack results:

| Rank | Chunk ID | Score |
|---|---|---:|
| 1 | `e1eb5829c239c9cc6bd9a56d3e86c73a536526b4fc4b786e996a96823ee09a02` | `10.7421919394` |
| 2 | `a9d4b68239e02f86d452ae3b5d49357df1f5ba1a1a7f241725c34b7026cb41a4` | `10.3770684431` |
| 3 | `9f04f46d714355e9852fdf1c421211ea29b25fc3861a487fa0e7f527f706fd12` | `10.3708788243` |
| 4 | `2fa332b7a82c5dc0df1d17db3c8e1af708d08e7ec529241b687a561f704e413c` | `10.1314880444` |
| 5 | `d0fd7c58793974cf0522ce0ea16fc68c892f434d4012f8689daffd26efed152f` | `9.9324031859` |

Top-5 Surreal text-only proxy results:

| Rank | Chunk ID | Score |
|---|---|---:|
| 1 | `e1eb5829c239c9cc6bd9a56d3e86c73a536526b4fc4b786e996a96823ee09a02` | `15.0` |
| 2 | `a9d4b68239e02f86d452ae3b5d49357df1f5ba1a1a7f241725c34b7026cb41a4` | `10.0` |
| 3 | `9f04f46d714355e9852fdf1c421211ea29b25fc3861a487fa0e7f527f706fd12` | `5.0` |
| 4 | `2fa332b7a82c5dc0df1d17db3c8e1af708d08e7ec529241b687a561f704e413c` | `3.0` |
| 5 | `e6852ae2087359b42585f27746ba9350b3a37a98158cf0203bada39f5e0bf07a` | `3.0` |

Observed mismatch:

- same top result
- top-5 overlap only `0.8`
- missing from Surreal top-5: `d0fd7c58793974cf0522ce0ea16fc68c892f434d4012f8689daffd26efed152f`
- unexpected in Surreal top-5: `e6852ae2087359b42585f27746ba9350b3a37a98158cf0203bada39f5e0bf07a`

Field evidence for classification:

- current weighted winners include `title` hits
- Surreal candidate side is `body`-only

Result:

- `failure_category: defer: FTS weighting`
- stop condition:
  - `FTS weighting mismatch blocks migrate-ready output until weighted-field parity is proven.`

## Vector

Vector parity was measured on the same 15 imported chunks with a fixed query
embedding taken from stored snapshot data. No TEI call was made.

Top-5 current vector results:

| Rank | Chunk ID | Score |
|---|---|---:|
| 1 | `e1eb5829c239c9cc6bd9a56d3e86c73a536526b4fc4b786e996a96823ee09a02` | `1.0000000000` |
| 2 | `2fa332b7a82c5dc0df1d17db3c8e1af708d08e7ec529241b687a561f704e413c` | `0.9830024123` |
| 3 | `9f04f46d714355e9852fdf1c421211ea29b25fc3861a487fa0e7f527f706fd12` | `0.9812835019` |
| 4 | `d0fd7c58793974cf0522ce0ea16fc68c892f434d4012f8689daffd26efed152f` | `0.9808219063` |
| 5 | `a9d4b68239e02f86d452ae3b5d49357df1f5ba1a1a7f241725c34b7026cb41a4` | `0.9726179344` |

Top-5 Surreal vector results were identical.

Result:

- exact top result match
- top-5 overlap `1.0`
- no missing IDs
- no score deltas
- `status: PASS`

## Graph-Direct

Graph-direct parity passed on the deterministic bounded fixture used by the new
parity harness:

- current related section IDs: `chunk-alpha`, `chunk-beta`
- normalized Surreal relation-table result IDs: `chunk-alpha`, `chunk-beta`
- relation labels and weights matched exactly:
  - `chunk-alpha -> MENTIONS -> 1.0`
  - `chunk-beta -> HAS_TAG -> 0.6`

Important limit:

- this plan did **not** establish production-derived graph-direct parity on a
  copied Falkor sample
- therefore graph-direct is only fixture-proven here, not scale-proven

## Hybrid / RRF

Hybrid parity reused the current app-side `fuse_results(...)` baseline on the
same representative copied sample. The top result stayed the same, but matched
engine attribution diverged because the Surreal FTS proxy did not reproduce the
same contributing result set.

Top-5 current hybrid results:

| Rank | Chunk ID | Score |
|---|---|---:|
| 1 | `e1eb5829c239c9cc6bd9a56d3e86c73a536526b4fc4b786e996a96823ee09a02` | `0.0327868852` |
| 2 | `2fa332b7a82c5dc0df1d17db3c8e1af708d08e7ec529241b687a561f704e413c` | `0.0317540323` |
| 3 | `9f04f46d714355e9852fdf1c421211ea29b25fc3861a487fa0e7f527f706fd12` | `0.0317460317` |
| 4 | `a9d4b68239e02f86d452ae3b5d49357df1f5ba1a1a7f241725c34b7026cb41a4` | `0.0315136476` |
| 5 | `d0fd7c58793974cf0522ce0ea16fc68c892f434d4012f8689daffd26efed152f` | `0.0310096154` |

Top-5 Surreal hybrid results:

| Rank | Chunk ID | Score |
|---|---|---:|
| 1 | `e1eb5829c239c9cc6bd9a56d3e86c73a536526b4fc4b786e996a96823ee09a02` | `0.0327868852` |
| 2 | `2fa332b7a82c5dc0df1d17db3c8e1af708d08e7ec529241b687a561f704e413c` | `0.0317540323` |
| 3 | `9f04f46d714355e9852fdf1c421211ea29b25fc3861a487fa0e7f527f706fd12` | `0.0317460317` |
| 4 | `a9d4b68239e02f86d452ae3b5d49357df1f5ba1a1a7f241725c34b7026cb41a4` | `0.0315136476` |
| 5 | `d0fd7c58793974cf0522ce0ea16fc68c892f434d4012f8689daffd26efed152f` | `0.0156250000` |

Observed mismatch:

- top result match: yes
- top-5 overlap: `1.0`
- matched engine attribution: **mismatch**
- score delta on rank 5 candidate:
  - `d0fd7c58793974cf0522ce0ea16fc68c892f434d4012f8689daffd26efed152f: -0.0153846154`

Result:

- `failure_category: reject: hybrid/RRF gap`
- stop condition:
  - `Hybrid/RRF gap blocks migrate-ready output until fused ordering and engine attribution match.`

## Failure Category Catalogue

| Category | Observed in 38-03 | Notes |
|---|---|---|
| `defer: FTS weighting` | yes | representative copied sample |
| `reject: vector recall gap` | no | vector parity passed on imported sample |
| `reject: graph semantic gap` | no | fixture graph-direct parity passed; production-derived graph sample still missing |
| `reject: hybrid/RRF gap` | yes | representative copied sample |
| `fail: unavailable scale evidence` | yes | HNSW build time unavailable |
| `info: accepted difference` | no | no informational-only parity difference was accepted |

## Scale Gate

Production-derived counts carried forward from 38-01:

| Metric | Value |
|---|---:|
| production chunks | `149739` |
| production embeddings | `149739` |
| production sections | `23857` |

Representative imported sample metrics:

| Metric | Value |
|---|---:|
| sample chunks | `15` |
| sample embeddings | `15` |
| SurrealKV stored bytes after sample import | `242864` |
| HNSW build time | unavailable |
| mixed query latency p50 | `0.170646 ms` |
| mixed query latency p95 | `22.470600 ms` |

Per-engine latency slices (7 runs each):

| Surface | p50 ms | p95 ms |
|---|---:|---:|
| current FTS | `2.7707` | `3.1002` |
| Surreal FTS proxy | `0.1706` | `0.1999` |
| current vector | `2.0429` | `2.0882` |
| Surreal vector | `22.2734` | `22.7545` |
| fixture graph-direct | `0.0163` | `0.0591` |
| current hybrid | `0.0033` | `0.0104` |
| Surreal hybrid | `0.0040` | `0.0069` |

Scale-gate result:

- `failure_category: fail: unavailable scale evidence`
- missing metric:
  - `HNSW build time`

Because the prototype did not build HNSW, the migration-readiness scale gate
cannot pass.

## Overall Conclusion

`38-03` does **not** support a migrate-ready recommendation.

Why the gate failed:

1. FTS parity is still blocked by weighted-field mismatch on a representative
   copied sample.
2. Hybrid parity still fails because the Surreal-side retrieval mix changes
   matched-engine attribution even when the top result stays the same.
3. Scale evidence is incomplete because no HNSW build timing was produced.

Net result for downstream recommendation work:

- current state is at best `defer`
- it is **not** `migrate`
- any later optimistic recommendation must first close:
  - weighted FTS parity
  - hybrid attribution parity
  - HNSW build-time evidence
