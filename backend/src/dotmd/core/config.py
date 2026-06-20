"""Application settings via pydantic-settings."""

from pathlib import Path
from typing import Literal, cast

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, TomlConfigSettingsSource

from dotmd.core.models import ExtractDepth

DEFAULT_INDEXING_EXCLUDE: tuple[str, ...] = (
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
)
DEFAULT_FALKORDB_URL = "redis://localhost:6379"
DEFAULT_FALKORDB_GRAPH_NAME = "dotmd"
DEFAULT_MAX_CHUNK_TOKENS = 512
DEFAULT_CHUNK_OVERLAP_TOKENS = 50
DEFAULT_TEI_BATCH_SIZE = 4
DEFAULT_DEFAULT_TOP_K = 10
DEFAULT_FUSION_K = 60
DEFAULT_RERANK_POOL_SIZE = 20
DEFAULT_SEMANTIC_SCORE_FLOOR = 0.85
DEFAULT_SNIPPET_LENGTH = 300
DEFAULT_POLL_INTERVAL_SECONDS = 3600.0
DEFAULT_GRAPH_MAX_HOPS = 2
DEFAULT_RERANKER_MIN_LENGTH = 50
DEFAULT_RERANKER_LENGTH_PENALTY = True
DEFAULT_SURREAL_URL = "http://127.0.0.1:8000"
DEFAULT_SURREAL_NAMESPACE = "dotmd"
DEFAULT_SURREAL_HNSW_EF = 40
DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE = "F32"
DEFAULT_SURREAL_EMBEDDING_SHARD_COUNT = 1
SUPPORTED_SURREAL_HNSW_VECTOR_INDEX_TYPES = (
    "F64",
    "F32",
    "F16",
    "I64",
    "I32",
    "I16",
    "I8",
    "U8",
)
RUNTIME_DATA_DIR = Path("/mnt")
RUNTIME_INDEX_DIR = Path("/dotmd-index")


def _path_spec_is_absolute(path_spec: str) -> bool:
    """Return whether a directory/glob path spec is anchored at an absolute path."""
    wildcard_positions = [
        pos for pos in (path_spec.find("*"), path_spec.find("?"), path_spec.find("[")) if pos != -1
    ]
    prefix = path_spec[: min(wildcard_positions)] if wildcard_positions else path_spec
    prefix = prefix.rstrip("/")
    if not prefix:
        return path_spec.startswith("/")
    return Path(prefix).is_absolute()


class Settings(BaseSettings):
    """Global configuration for dotMD.

    Values can be set via environment variables prefixed with DOTMD_,
    a TOML config file at ~/.dotmd/config.toml, or programmatically.

    Priority order (highest wins): init_settings > env vars > TOML file > defaults.
    """

    model_config = {
        "env_prefix": "DOTMD_",
        "toml_file": str(Path.home() / ".dotmd" / "config.toml"),
        "populate_by_name": True,
    }

    # Paths
    data_dir: Path = Path()
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

    # Reranker
    reranker_backend: Literal["cross_encoder"] = "cross_encoder"
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_name: str = "mmarco-minilm"
    reranker_compare_names: str = "mmarco-minilm"
    reranker_relevance_floor: float | None = None
    reranker_length_penalty: bool = DEFAULT_RERANKER_LENGTH_PENALTY
    reranker_min_length: int = DEFAULT_RERANKER_MIN_LENGTH

    # Chunking
    chunk_strategy: str = "heading_512_50"
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS
    chunk_overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS

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
    tei_batch_size: int = DEFAULT_TEI_BATCH_SIZE

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
            raise ValueError(f"embedding_weights: weights must sum to 1.0 (got {total:.4f})")
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

    @field_validator("surreal_retrieval_vector_index_type", mode="before")
    @classmethod
    def validate_surreal_retrieval_vector_index_type(cls, v: object) -> str:
        """Normalize and validate the Surreal HNSW vector element type."""
        if not isinstance(v, str):
            raise ValueError("surreal_retrieval_vector_index_type must be a string")
        normalized = v.strip().upper()
        if normalized not in SUPPORTED_SURREAL_HNSW_VECTOR_INDEX_TYPES:
            raise ValueError(
                "surreal_retrieval_vector_index_type must be one of "
                f"{', '.join(SUPPORTED_SURREAL_HNSW_VECTOR_INDEX_TYPES)}"
            )
        return normalized

    # Search
    search_backend: Literal["sqlite", "surreal"] = "sqlite"
    default_top_k: int = DEFAULT_DEFAULT_TOP_K
    fusion_k: int = DEFAULT_FUSION_K
    rerank_pool_size: int = DEFAULT_RERANK_POOL_SIZE
    semantic_score_floor: float = DEFAULT_SEMANTIC_SCORE_FLOOR
    snippet_length: int = DEFAULT_SNIPPET_LENGTH

    # Indexing paths (multi-path discovery)
    # Directories (full recursive .md scan) or glob patterns (e.g., "/home/**/README.md")
    indexing_paths: list[str] = []
    # Legacy replace-only exclude config. Prefer indexing_extra_exclude for
    # operator additions, and effective_indexing_exclude for call sites.
    indexing_exclude: list[str] = list(DEFAULT_INDEXING_EXCLUDE)
    indexing_extra_exclude: list[str] = []

    # Trickle indexer settings
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    profile_indexing: bool = False  # DOTMD_PROFILE_INDEXING=true → per-phase timing in logs
    allow_destructive_startup_repair: bool = False

    # Graph
    graph_max_hops: int = DEFAULT_GRAPH_MAX_HOPS
    # FalkorDB connection URL (Redis protocol).
    falkordb_url: str = DEFAULT_FALKORDB_URL
    falkordb_graph_name: str = DEFAULT_FALKORDB_GRAPH_NAME

    # Standalone SurrealDB search runtime.
    surreal_retrieval_url: str = DEFAULT_SURREAL_URL
    surreal_retrieval_namespace: str = DEFAULT_SURREAL_NAMESPACE
    surreal_retrieval_database: str | None = None
    surreal_retrieval_username: str | None = None
    surreal_retrieval_password: str | None = None
    surreal_retrieval_access_token: str | None = None
    surreal_retrieval_embedding_dimension: int | None = None
    surreal_retrieval_hnsw_ef: int = DEFAULT_SURREAL_HNSW_EF
    surreal_retrieval_vector_index_type: str = DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE
    surreal_retrieval_embedding_shard_count: int = DEFAULT_SURREAL_EMBEDDING_SHARD_COUNT

    # Base URL for OAuth 2.0 endpoints served by FastMCP.
    # Must be the full Tailscale-facing URL including path prefix
    # (e.g. https://senbonzakura.tailf87223.ts.net/dotmd).
    # Note: Tailscale Serve strips the /dotmd prefix before forwarding to the
    # container, so FastMCP mounts routes at root / (no mount_path needed).
    # When unset, OAuth auth is disabled; stdio and internal-network transports
    # work as before.
    # Set DOTMD_BASE_URL in docker-compose env or /opt/docker/dotmd/.env.
    base_url: str | None = None

    # UNIX socket for the existing mcp-telegram daemon JSON API.
    # DOTMD_TELEGRAM_DAEMON_SOCKET is the only Phase 29 live transport.
    telegram_daemon_socket: Path | None = None

    # Gmail federated search credentials. In production these are loaded from
    # ~/.secrets/dotmd-gmail.env via docker-compose env_file.
    gmail_client_id: str | None = None
    gmail_client_secret: str | None = None
    gmail_refresh_token: str | None = None
    gmail_search_result_limit: int = Field(
        default=20,
        ge=1,
        le=500,
    )

    # Background Telegram sync polling interval (Phase 36).
    # DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS overrides the default.
    telegram_sync_interval_seconds: float = 300.0

    # Federated search settings (Phase 34)
    federated_timeout_seconds: float = 4.0
    """Per-source soft timeout for federated providers (3-5s default range, D-09).

    Applies only to federated providers running via asyncio.to_thread, not to local
    engines which run sequentially with no timeout. Configurable via
    DOTMD_FEDERATED_TIMEOUT_SECONDS env var.
    """

    federated_engine_weights: dict[str, float] = {}
    """Per-federated-engine weights for RRF fusion (D-06, Phase 34).

    Format: {"tg:fts": 1.0, "gmail:native": 1.2, ...}. Default 1.0 for any
    unspecified engine. Parsed from env if convenient; currently config-only
    (env wiring deferred to future phase).
    """

    federated_result_quota: int = 3
    """Number of result slots reserved for federated (non-local) sources in each
    search response. Controls how many federated candidates appear alongside local
    semantic results.

    Score-based merge is impossible across heterogeneous sources: local uses cosine
    similarity (0.52-0.96); mcp-telegram returns no scores so fused_score=0.0.
    Quota is honest — it reserves slots based on what we know (daemon ranking) and
    avoids fabricating cross-source scores that would silently mislead rerankers.

    The slot count is adaptive: fed_slots = min(fed_quota, len(filtered_fed)).
    This handles daemon-down (0 fed → full top_k to local), sparse results, and
    normal operation with one code path.
    """

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
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            TomlConfigSettingsSource(settings_cls),
        ]
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
        return [name.strip() for name in self.reranker_compare_names.split(",") if name.strip()]

    @property
    def effective_indexing_exclude(self) -> list[str]:
        """Return resolved exclude patterns with built-ins and operator extras."""
        patterns = self.indexing_exclude or list(DEFAULT_INDEXING_EXCLUDE)
        result: list[str] = []
        seen: set[str] = set()
        for pattern in [*patterns, *self.indexing_extra_exclude]:
            if pattern in seen:
                continue
            seen.add(pattern)
            result.append(pattern)
        return result

    def validate_for_runtime(self) -> None:
        """Validate settings used by long-running runtime service entrypoints."""
        errors: list[str] = []
        if not self.data_dir.is_absolute():
            errors.append("data_dir must be absolute for runtime startup")
        elif self.data_dir != RUNTIME_DATA_DIR:
            errors.append("data_dir must be /mnt for runtime startup")
        if not self.index_dir.is_absolute():
            errors.append("index_dir must be absolute for runtime startup")
        elif self.index_dir != RUNTIME_INDEX_DIR:
            errors.append("index_dir must be /dotmd-index for runtime startup")
        if not self.indexing_paths:
            errors.append("indexing_paths must not be empty for runtime startup")
        elif any(not _path_spec_is_absolute(path_spec) for path_spec in self.indexing_paths):
            errors.append("indexing_paths must contain absolute paths for runtime startup")
        if not self.embedding_url:
            errors.append("embedding_url must not be empty for runtime startup")
        if self.search_backend == "surreal":
            if not self.surreal_retrieval_url:
                errors.append("surreal_retrieval_url must be set for Surreal search runtime")
            if not self.surreal_retrieval_namespace:
                errors.append(
                    "surreal_retrieval_namespace must be set for Surreal search runtime"
                )
            if not self.surreal_retrieval_database:
                errors.append(
                    "surreal_retrieval_database must be set for Surreal search runtime"
                )
            if self.surreal_retrieval_embedding_dimension is None:
                errors.append(
                    "surreal_retrieval_embedding_dimension must be set for "
                    "Surreal search runtime"
                )
            has_username = bool(self.surreal_retrieval_username)
            has_password = bool(self.surreal_retrieval_password)
            if has_username != has_password:
                errors.append(
                    "surreal_retrieval_username and surreal_retrieval_password "
                    "must be set together"
                )
            if (has_username or has_password) and self.surreal_retrieval_access_token:
                errors.append(
                    "surreal_retrieval_access_token must not be combined with "
                    "username/password auth"
                )
            if self.surreal_retrieval_hnsw_ef < 1:
                errors.append(
                    "surreal_retrieval_hnsw_ef must be >= 1 for Surreal search runtime"
                )
            if self.surreal_retrieval_embedding_shard_count < 1:
                errors.append(
                    "surreal_retrieval_embedding_shard_count must be >= 1 for "
                    "Surreal search runtime"
                )

        identity_fields = {
            "embedding_model": self.embedding_model,
            "chunk_strategy": self.chunk_strategy,
            "ner_model_name": self.ner_model_name,
            "reranker_name": self.reranker_name,
            "reranker_model": self.reranker_model,
            "reranker_backend": self.reranker_backend,
            "embedding_weights": self.embedding_weights,
        }
        for field_name, value in identity_fields.items():
            if value == "":
                errors.append(f"{field_name} must not be empty for runtime startup")

        if not self.falkordb_url:
            errors.append("falkordb_url must be set for runtime startup")
        elif self.falkordb_url == DEFAULT_FALKORDB_URL:
            errors.append("falkordb_url must not use DEFAULT_FALKORDB_URL for runtime startup")

        if errors:
            raise ValueError("; ".join(errors))

    @property
    def config_path(self) -> Path:
        """Path to the TOML config file."""
        toml_file = cast(
            str, self.model_config.get("toml_file", str(self.index_dir / "config.toml"))
        )
        return Path(toml_file)

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
            return (
                "Instruct: Given a search query, retrieve relevant passages that answer the query"
            )
        return ""

    @property
    def index_db_path(self) -> Path:
        """Path to the unified SQLite index database (metadata + vec + FTS5)."""
        return self.index_dir / "index.db"

    @property
    def acronyms_path(self) -> Path:
        return self.index_dir / "acronyms.json"


def load_settings(**overrides: object) -> Settings:
    """Construct Settings while preserving BaseSettings env/config loading.

    `embedding_url` is intentionally provided by environment/config in
    production. Pyright treats it as a required constructor argument because it
    cannot model pydantic-settings sources.
    """
    return Settings(**overrides)  # type: ignore[call-arg]


def load_runtime_settings(**overrides: object) -> Settings:
    """Construct and validate Settings for long-running service startup."""
    settings = load_settings(**overrides)
    settings.validate_for_runtime()
    return settings
