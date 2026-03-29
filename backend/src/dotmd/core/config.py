"""Application settings via pydantic-settings."""

from pathlib import Path
from typing import Literal

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

    # Embedding
    # Previous: sentence-transformers/all-MiniLM-L6-v2 (384-dim, 256 max tokens, speed-optimized)
    # Current: BAAI/bge-small-en-v1.5 (384-dim, 512 max tokens, retrieval-optimized)
    # Alternatives: all-mpnet-base-v2 (768-dim, general-purpose), bge-m3 (1024-dim, multilingual)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    # URL to a TEI-compatible embedding server (e.g. http://host:8088).
    # Required — dotMD is designed to run with an external embedding server.
    # Set DOTMD_EMBEDDING_URL in your environment or docker-compose.yml.
    embedding_url: str

    vector_backend: Literal["lancedb", "sqlite-vec"] = "sqlite-vec"

    # Reranker
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_length_penalty: bool = True  # penalize very short chunks
    reranker_min_length: int = 50  # chars below which penalty applies

    # Chunking
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

    # Initial TEI batch size for embedding requests. Auto-tuned down on 413 errors.
    # Small batches (4-8) are often faster on CPU due to lower TEI queue/inference time.
    tei_batch_size: int = 4

    # Search
    default_top_k: int = 10
    fusion_k: int = 60  # RRF constant
    graph_rrf_weight: float = 1.5  # boost graph-unique discoveries in RRF
    rerank_pool_size: int = 20  # candidates to rerank
    semantic_score_floor: float = 0.62  # BGE-small: <0.62 is noise (empirically verified)
    snippet_length: int = 300  # display snippet character limit

    # Indexing paths (multi-path discovery)
    # Directories (full recursive .md scan) or glob patterns (e.g., "/home/**/README.md")
    indexing_paths: list[str] = []
    # Exclude patterns -- glob patterns to filter out (e.g., "**/node_modules")
    indexing_exclude: list[str] = ["**/node_modules", "**/.git", "**/__pycache__"]

    # Trickle indexer settings
    poll_interval_seconds: float = 3600.0  # 1 hour fallback poll

    # Graph
    graph_max_hops: int = 2
    read_only: bool = False
    graph_backend: Literal["ladybugdb", "falkordb"] = "ladybugdb"
    # FalkorDB connection URL (Redis protocol). Only used when graph_backend="falkordb".
    falkordb_url: str = "redis://localhost:6379"
    # FalkorDB graph name. Must differ from Graphiti's "knowledgebase" graph.
    falkordb_graph_name: str = "dotmd"

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
    def config_path(self) -> Path:
        """Path to the TOML config file."""
        return Path(self.model_config.get("toml_file", str(self.index_dir / "config.toml")))

    @property
    def lancedb_path(self) -> Path:
        return self.index_dir / "lancedb"

    @property
    def sqlite_vec_path(self) -> Path:
        return self.index_dir / "vec.db"

    @property
    def graph_db_path(self) -> Path:
        return self.index_dir / "graphdb"

    @property
    def sqlite_path(self) -> Path:
        return self.index_dir / "metadata.db"

    @property
    def acronyms_path(self) -> Path:
        return self.index_dir / "acronyms.json"
