"""Application settings via pydantic-settings."""

import warnings
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, TomlConfigSettingsSource

from dotmd.core.models import ExtractDepth


class Settings(BaseSettings):
    """Global configuration for dotMD.

    Values can be set via environment variables prefixed with DOTMD_,
    a TOML config file at ~/.dotmd/config.toml, or programmatically.

    Priority order (highest wins): init_settings > env vars > TOML file > defaults.
    """

    model_config = {
        "env_prefix": "DOTMD_",
        "toml_file": str(Path.home() / ".dotmd" / "config.toml"),
    }

    # Paths
    data_dir: Path = Path(".")
    index_dir: Path = Path.home() / ".dotmd"

    # Local SentenceTransformers model — used only when embedding_url is unset.
    # When TEI is configured, the actual model is determined by TEI (query /info).
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # URL to a TEI-compatible embedding server (e.g. http://host:8088).
    # Required — dotMD is designed to run with an external embedding server.
    # Set DOTMD_EMBEDDING_URL in your environment or docker-compose.yml.
    embedding_url: str

    # Whether the active embedding model uses E5-family instruction prefixes.
    # E5 models require "query: " / "passage: " prefixes. pplx-embed does not.
    # Auto-detected from embedding_model name if not explicitly set.
    embedding_uses_prefix: bool | None = None

    # Instruction prefix for query encoding (Qwen3-style models).
    # If set, queries are encoded as: "<instruction>\nQuery: <query>"
    # Auto-detected from embedding_model name if not explicitly set.
    embedding_query_instruction: str | None = None

    vector_backend: Literal["lancedb", "sqlite-vec"] = "sqlite-vec"

    # Reranker
    reranker_backend: Literal["cross_encoder"] = "cross_encoder"
    reranker_url: str | None = None
    reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
    reranker_name: str = "qwen3-0.6b"
    reranker_compare_names: str = "qwen3-0.6b,msmarco-minilm,mmarco-minilm,gte-multilingual"
    reranker_relevance_floor: float | None = None
    reranker_length_penalty: bool = True  # penalize very short chunks
    reranker_min_length: int = 50  # chars below which penalty applies

    # Chunking
    chunk_strategy: str = "heading_512_50"
    max_chunk_tokens: int = 512
    chunk_overlap_tokens: int = 50

    # Extraction
    extract_depth: ExtractDepth = ExtractDepth.NER
    ner_entity_types: list[str] = [
        "person",
        "organization",
        "technology",
        "concept",
        "location",
        "object",
        "activity",
        "date_time",
    ]
    # GLiNER model for NER extraction. Changing this clears the extraction_cache.
    ner_model_name: str = "urchade/gliner_multi-v2.1"

    # Initial TEI batch size for embedding requests. Auto-tuned down on 413 errors.
    # Small batches (4-8) are often faster on CPU due to lower TEI queue/inference time.
    tei_batch_size: int = 4

    # Fusion weights for N-vector unified embeddings (Phase 999.12).
    # Format: "text=0.7,meta=0.3" — component names to float weights, comma-separated.
    # Must sum to 1.0 (±0.001 tolerance). Validated at startup — fails fast.
    # Must include both "text" and "meta" keys (dual-encoder architecture requires both).
    # Recomputing e_fused after weight change is local math only (no TEI calls).
    embedding_weights: str = "text=0.7,meta=0.3"

    @field_validator("embedding_weights")
    @classmethod
    def validate_embedding_weights(cls, v: str) -> str:
        """Parse and validate embedding_weights string.

        Expected format: "text=0.7,meta=0.3"
        Raises ValueError if:
        - Any entry is not in key=value format
        - Any value is not a valid float
        - Values do not sum to 1.0 (±0.001 tolerance)
        - Either "text" or "meta" key is missing (dual-encoder requires both)
        """
        pairs = [p.strip() for p in v.split(",") if p.strip()]
        parsed: dict[str, float] = {}
        total = 0.0
        for pair in pairs:
            if "=" not in pair:
                raise ValueError(
                    f"embedding_weights: invalid entry {pair!r} — expected key=value format"
                )
            key, val = pair.split("=", 1)
            key = key.strip()
            try:
                w = float(val.strip())
            except ValueError:
                raise ValueError(
                    f"embedding_weights: value for {key!r} is not a float: {val!r}"
                ) from None
            parsed[key] = w
            total += w
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"embedding_weights: weights must sum to 1.0 (got {total:.4f})"
            )
        # Require both "text" and "meta" keys — dual-encoder architecture requires both
        # components. Accepting arbitrary keys would silently omit a component from fusion.
        if "text" not in parsed:
            raise ValueError(
                "embedding_weights: missing required key 'text' "
                "(dual-encoder requires both 'text' and 'meta')"
            )
        if "meta" not in parsed:
            raise ValueError(
                "embedding_weights: missing required key 'meta' "
                "(dual-encoder requires both 'text' and 'meta')"
            )
        return v

    @field_validator("reranker_relevance_floor", mode="before")
    @classmethod
    def empty_reranker_floor_is_none(cls, v: object) -> object:
        """Allow DOTMD_RERANKER_RELEVANCE_FLOOR= to mean no raw-score filter."""
        if v == "":
            return None
        return v

    # Search
    default_top_k: int = 10
    fusion_k: int = 60  # RRF constant
    rerank_pool_size: int = 20  # candidates to rerank
    semantic_score_floor: float = 0.85  # ratio of top hit: keep results within 85% of best score
    snippet_length: int = 300  # display snippet character limit

    # Indexing paths (multi-path discovery)
    # Directories (full recursive .md scan) or glob patterns (e.g., "/home/**/README.md")
    indexing_paths: list[str] = []
    # Exclude patterns -- glob patterns to filter out (e.g., "**/node_modules")
    indexing_exclude: list[str] = [
        "**/node_modules",
        "**/.git",
        "**/__pycache__",
        "**/.pytest_cache",
        "**/.ruff_cache",
        "**/.mypy_cache",
        "**/.tox",
        "**/.nox",
        "**/.venv",
        "**/venv",
        "**/dist",
        "**/build",
        "**/.cache",
    ]

    # Trickle indexer settings
    poll_interval_seconds: float = 3600.0  # 1 hour fallback poll
    profile_indexing: bool = False  # DOTMD_PROFILE_INDEXING=true → per-phase timing in logs

    # Graph
    graph_max_hops: int = 2
    graph_backend: Literal["ladybugdb", "falkordb"] = "ladybugdb"
    # FalkorDB connection URL (Redis protocol). Only used when graph_backend="falkordb".
    falkordb_url: str = "redis://localhost:6379"

    # Base URL for OAuth 2.0 endpoints served by FastMCP.
    # Must be the full Tailscale-facing URL including path prefix
    # (e.g. https://senbonzakura.tailf87223.ts.net/dotmd).
    # Note: Tailscale Serve strips the /dotmd prefix before forwarding to the
    # container, so FastMCP mounts routes at root / (no mount_path needed).
    # When unset, OAuth auth is disabled; stdio and internal-network transports
    # work as before.
    # Set DOTMD_BASE_URL in docker-compose env or /opt/docker/dotmd/.env.
    base_url: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        """Normalize and validate the public OAuth base URL."""
        if v is None:
            return None
        v = v.rstrip("/")
        if not v.startswith("https://") and not v.startswith("http://localhost"):
            raise ValueError(
                f"DOTMD_BASE_URL must use HTTPS (got {v!r}). "
                "OAuth 2.0 requires HTTPS except for localhost."
            )
        return v

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Set priority: init > env > dotenv > file_secret > TOML > defaults."""
        toml_path = Path(cls.model_config.get("toml_file", ""))
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        ]
        if toml_path.exists():
            sources.append(TomlConfigSettingsSource(settings_cls))
        return tuple(sources)

    @property
    def parsed_embedding_weights(self) -> dict[str, float]:
        """Return embedding_weights as {component_name: weight} dict."""
        result: dict[str, float] = {}
        for pair in self.embedding_weights.split(","):
            pair = pair.strip()
            if "=" in pair:
                key, val = pair.split("=", 1)
                result[key.strip()] = float(val.strip())
        return result

    @property
    def parsed_reranker_compare_names(self) -> list[str]:
        """Return configured reranker comparison names as a cleaned list."""
        return [
            name.strip()
            for name in self.reranker_compare_names.split(",")
            if name.strip()
        ]

    @property
    def config_path(self) -> Path:
        """Path to the TOML config file."""
        return Path(self.model_config.get("toml_file", str(self.index_dir / "config.toml")))

    @property
    def needs_embedding_prefix(self) -> bool:
        """Whether the embedding model requires E5-style instruction prefixes."""
        if self.embedding_uses_prefix is not None:
            return self.embedding_uses_prefix
        # Auto-detect: E5 family and BGE models need prefixes, others don't
        model_lower = self.embedding_model.lower()
        return "e5" in model_lower or "bge" in model_lower

    @property
    def query_instruction(self) -> str:
        """Instruction string for query encoding, or empty string if not needed.

        Qwen3-Embedding and similar instruction-aware models encode queries as:
        ``"<instruction>\\nQuery: <query>"`` and documents without any prefix.
        """
        if self.embedding_query_instruction is not None:
            return self.embedding_query_instruction
        model_lower = self.embedding_model.lower()
        if "qwen3-embedding" in model_lower:
            return "Instruct: Given a search query, retrieve relevant passages that answer the query"
        return ""

    @property
    def lancedb_path(self) -> Path:
        return self.index_dir / "lancedb"

    @property
    def index_db_path(self) -> Path:
        """Path to the unified SQLite index database (metadata + vec + FTS5)."""
        return self.index_dir / "index.db"

    @property
    def sqlite_vec_path(self) -> Path:
        warnings.warn(
            "sqlite_vec_path is deprecated — use index_db_path",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.index_db_path

    @property
    def graph_db_path(self) -> Path:
        return self.index_dir / f"graphdb_{self.chunk_strategy}"

    @property
    def sqlite_path(self) -> Path:
        warnings.warn(
            "sqlite_path is deprecated — use index_db_path",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.index_db_path

    @property
    def acronyms_path(self) -> Path:
        return self.index_dir / "acronyms.json"
