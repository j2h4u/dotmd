---
phase: "19"
plan: "01-reranker-protocol-registry"
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/search/reranker.py
  - backend/tests/test_reranker.py
autonomous: true
requirements:
  - RERANK-ADAPTER-01
  - RERANK-SELECT-04
requirements_addressed: [RERANK-ADAPTER-01, RERANK-SELECT-04]
must_haves:
  truths:
    - "Rerankers are selected by stable short name, not only raw model string"
    - "DotMDService can obtain a reranker through a factory/protocol boundary instead of constructing the concrete CrossEncoder wrapper directly"
    - "The production default remains one configured reranker: qwen3-0.6b"
    - "Unknown reranker names fail clearly and list available names"
    - "CrossEncoderReranker exposes warmup() through the protocol and delegates it to lazy model loading"
    - "All internal service construction goes through RerankerFactory; the Reranker alias is compatibility-only"
    - "Unit tests mock CrossEncoder and do not download model weights"
  artifacts:
    - path: "backend/src/dotmd/search/reranker.py"
      provides: "RerankerProtocol, registry specs, factory/cache, CrossEncoder adapter"
      contains: "class RerankerProtocol"
    - path: "backend/src/dotmd/core/config.py"
      provides: "name-based default and comparison settings"
      contains: "reranker_name: str = \"qwen3-0.6b\""
  key_links:
    - from: "Settings.reranker_name"
      to: "create_reranker / factory lookup"
      via: "stable registry name"
      pattern: "qwen3-0.6b"
---

# Phase 19 Plan 01: Reranker Protocol, Registry, and Factory

<objective>
Introduce the provider/adapter boundary requested by Phase 19 without changing search behavior yet.

This plan creates a `RerankerProtocol`, stable name registry, and factory/cache over the existing local CrossEncoder implementation. The default remains `qwen3-0.6b`, and legacy Qwen/MiniLM/GTE/BGE comparison names become resolvable by name for later plans.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Unknown reranker name silently falls back to production default | HIGH | Factory must raise `ValueError` containing `Unknown reranker` and all available names. |
| Registry refactor downloads models during tests | HIGH | Tests patch `sentence_transformers.CrossEncoder`; factory tests only inspect metadata or mocked instances. |
| Production default changes from one reranker to multi-reranker behavior | HIGH | This plan only creates one default `reranker_name`; comparison names are inert until explicitly used. |
| Existing imports of `Reranker` break | MEDIUM | Keep compatibility alias `Reranker = CrossEncoderReranker` or update all imports in the same plan. |
</threat_model>

<tasks>
<task id="1" type="auto" tdd="true">
<name>Task 1: Add name-based reranker settings</name>
<read_first>
- `backend/src/dotmd/core/config.py`
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-RESEARCH.md`
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-PATTERNS.md`
</read_first>
<files>
- `backend/src/dotmd/core/config.py`
- `backend/tests/test_reranker.py`
</files>
<behavior>
- Test 1: `Settings(embedding_url="http://test:8088").reranker_name == "qwen3-0.6b"`.
- Test 2: `Settings(...).parsed_reranker_compare_names == ["qwen3-0.6b", "msmarco-minilm", "mmarco-minilm", "gte-multilingual"]`.
- Test 3: empty entries in `reranker_compare_names` are ignored.
- Test 4: `Settings(..., reranker_compare_names="qwen3-0.6b, ,msmarco-minilm").parsed_reranker_compare_names` returns exactly `["qwen3-0.6b", "msmarco-minilm"]`.
</behavior>
<action>
In `Settings`, add stable-name settings immediately after the existing reranker fields:

```python
reranker_name: str = "qwen3-0.6b"
reranker_compare_names: str = "qwen3-0.6b,msmarco-minilm,mmarco-minilm,gte-multilingual"
```

Add a parsed property:

```python
@property
def parsed_reranker_compare_names(self) -> list[str]:
    return [name.strip() for name in self.reranker_compare_names.split(",") if name.strip()]
```

Do not delete `reranker_backend`, `reranker_url`, `reranker_model`, `reranker_relevance_floor`, `reranker_length_penalty`, or `reranker_min_length`; these remain adapter configuration inputs and backwards-compatible env knobs.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_reranker.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/core/config.py` contains `reranker_name: str = "qwen3-0.6b"`.
- `backend/src/dotmd/core/config.py` contains `reranker_compare_names: str = "qwen3-0.6b,msmarco-minilm,mmarco-minilm,gte-multilingual"`.
- `backend/src/dotmd/core/config.py` contains `def parsed_reranker_compare_names`.
- `backend/tests/test_reranker.py` asserts the default `reranker_name`.
- `backend/tests/test_reranker.py` asserts parsed comparison names.
- `backend/tests/test_reranker.py` asserts empty comma-separated comparison entries are ignored.
</acceptance_criteria>
<done>
Name-based settings exist and tests pin the default and parsed comparison list.
</done>
</task>

<task id="2" type="auto" tdd="true">
<name>Task 2: Introduce RerankerProtocol and registry specs</name>
<read_first>
- `backend/src/dotmd/search/reranker.py`
- `backend/src/dotmd/storage/base.py`
- `backend/tests/test_reranker.py`
</read_first>
<files>
- `backend/src/dotmd/search/reranker.py`
- `backend/tests/test_reranker.py`
</files>
<behavior>
- Test 1: `available_rerankers()` includes `qwen3-0.6b`, `msmarco-minilm`, `mmarco-minilm`, `gte-multilingual`, and `bge-v2-m3`.
- Test 2: the `qwen3-0.6b` spec maps to model `Qwen/Qwen3-Reranker-0.6B`.
- Test 3: the `msmarco-minilm` spec maps to model `cross-encoder/ms-marco-MiniLM-L-6-v2`.
</behavior>
<action>
Refactor `backend/src/dotmd/search/reranker.py`:

- Add imports:

```python
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
```

- Add:

```python
class RerankerProtocol(Protocol):
    name: str
    model_name: str

    def warmup(self) -> None: ...

    def rerank(
        self,
        query: str,
        chunk_ids: list[str],
        metadata_store: MetadataStoreProtocol,
        top_k: int = 5,
    ) -> list[tuple[str, float]]: ...
```

- Add:

```python
@dataclass(frozen=True)
class RerankerSpec:
    name: str
    model_name: str
    backend: str = "cross_encoder"
    description: str = ""
```

- Add `BUILTIN_RERANKERS` with these exact keys and model names:
  - `qwen3-0.6b` -> `Qwen/Qwen3-Reranker-0.6B`
  - `msmarco-minilm` -> `cross-encoder/ms-marco-MiniLM-L-6-v2`
  - `mmarco-minilm` -> `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
  - `gte-multilingual` -> `Alibaba-NLP/gte-multilingual-reranker-base`
  - `bge-v2-m3` -> `BAAI/bge-reranker-v2-m3`

- Add `available_rerankers() -> list[str]` returning sorted keys.

Keep all code in the existing `reranker.py` module for this phase unless the implementation becomes unwieldy.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_reranker.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/search/reranker.py` contains `class RerankerProtocol`.
- `backend/src/dotmd/search/reranker.py` contains `@dataclass(frozen=True)`.
- `backend/src/dotmd/search/reranker.py` contains `BUILTIN_RERANKERS`.
- `backend/src/dotmd/search/reranker.py` contains all five registry keys listed above.
- `backend/tests/test_reranker.py` verifies `available_rerankers()`.
</acceptance_criteria>
<done>
Registry metadata exists and is pinned by unit tests.
</done>
</task>

<task id="3" type="auto" tdd="true">
<name>Task 3: Add factory/cache over CrossEncoder adapter</name>
<read_first>
- `backend/src/dotmd/search/reranker.py`
- `backend/src/dotmd/core/config.py`
- `backend/tests/test_reranker.py`
</read_first>
<files>
- `backend/src/dotmd/search/reranker.py`
- `backend/tests/test_reranker.py`
</files>
<behavior>
- Test 1: `create_reranker("qwen3-0.6b", settings)` returns an object with `name == "qwen3-0.6b"` and `model_name == "Qwen/Qwen3-Reranker-0.6B"`.
- Test 2: `create_reranker("does-not-exist", settings)` raises `ValueError` containing `Unknown reranker` and `qwen3-0.6b`.
- Test 3: `RerankerFactory(settings).get("qwen3-0.6b") is RerankerFactory(settings).get("qwen3-0.6b")` on the same factory instance.
- Test 4: `CrossEncoderReranker.warmup()` calls the same lazy load path as `rerank()` without scoring any pairs.
- Test 5: `create_reranker("qwen3-0.6b", settings)` passes `settings.reranker_length_penalty`, `settings.reranker_min_length`, and `settings.reranker_relevance_floor` into `CrossEncoderReranker`.
- Test 6: existing `Reranker(...)` import path still works, but `DotMDService` does not construct `Reranker(` directly after Plan 02.
</behavior>
<action>
Rename the existing concrete class to `CrossEncoderReranker`, adding public attributes:

```python
self.name = name
self.model_name = model_name
```

Constructor target:

```python
def __init__(
    self,
    model_name: str,
    *,
    name: str | None = None,
    length_penalty: bool = True,
    min_length: int = 100,
    relevance_floor: float | None = None,
) -> None:
```

Add:

```python
Reranker = CrossEncoderReranker
```

Add a public warmup method to the concrete adapter:

```python
def warmup(self) -> None:
    self._load_model()
```

Add factory functions/classes:

```python
def create_reranker(name: str, settings: Settings) -> RerankerProtocol:
    ...

class RerankerFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._instances: dict[str, RerankerProtocol] = {}

    def get(self, name: str | None = None) -> RerankerProtocol:
        resolved = name or self._settings.reranker_name
        ...
```

Factory behavior:
- Look up `name` in `BUILTIN_RERANKERS`.
- For `qwen3-0.6b`, allow `settings.reranker_model` to override only if `settings.reranker_name == "qwen3-0.6b"` and the implementation needs backwards compatibility; otherwise use the registry model.
- Pass `settings.reranker_length_penalty`, `settings.reranker_min_length`, and `settings.reranker_relevance_floor` to the adapter.
- Reject unsupported `spec.backend` values clearly.
- Treat `Reranker = CrossEncoderReranker` as a backwards-compatibility alias only. New internal construction paths must use `RerankerFactory.get(...)`.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_reranker.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/search/reranker.py` contains `class CrossEncoderReranker`.
- `backend/src/dotmd/search/reranker.py` contains `def create_reranker`.
- `backend/src/dotmd/search/reranker.py` contains `class RerankerFactory`.
- `backend/src/dotmd/search/reranker.py` contains `Reranker = CrossEncoderReranker`.
- `backend/src/dotmd/search/reranker.py` contains `def warmup(self) -> None`.
- `backend/tests/test_reranker.py` tests unknown-name failure.
- `backend/tests/test_reranker.py` tests factory caching.
- `backend/tests/test_reranker.py` tests `warmup()` on `CrossEncoderReranker`.
- `backend/tests/test_reranker.py` tests settings-derived length penalty, min length, and relevance floor are passed into the adapter.
- `cd backend && uv run pytest tests/test_reranker.py -q` exits 0.
</acceptance_criteria>
<done>
All reranker construction flows through the name registry and factory while existing tests remain green.
</done>
</task>
</tasks>

<verification>
```bash
cd backend && uv run pytest tests/test_reranker.py -q
cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py tests/test_reranker.py
```
</verification>

<success_criteria>
- `RerankerProtocol`, registry, and factory exist.
- Default single-reranker setting is `qwen3-0.6b`.
- Built-in names cover Qwen, MiniLM legacy, multilingual MiniLM, GTE, and BGE.
- Unknown reranker names fail loudly.
- No test downloads model weights.
</success_criteria>
