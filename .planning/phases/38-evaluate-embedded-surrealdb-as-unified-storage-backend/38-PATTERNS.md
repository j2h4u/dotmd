# Phase 38: evaluate-embedded-surrealdb-as-unified-storage-backend - Pattern Map

**Mapped:** 2026-06-12
**Files analyzed:** 12
**Analogs found:** 12 / 12

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/src/dotmd/storage/surreal_metadata.py` | model | CRUD | `backend/src/dotmd/storage/metadata.py` | exact |
| `backend/src/dotmd/storage/surreal_vector.py` | model | CRUD | `backend/src/dotmd/storage/sqlite_vec.py` | exact |
| `backend/src/dotmd/storage/surreal_graph.py` | model | graph request-response | `backend/src/dotmd/storage/falkordb_graph.py` | exact |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | utility | batch | `backend/src/dotmd/ingestion/migration.py` | exact |
| `backend/src/dotmd/core/config.py` | config | request-response | `backend/src/dotmd/core/config.py` | exact |
| `backend/pyproject.toml` | config | request-response | `backend/pyproject.toml` | exact |
| `backend/src/dotmd/ingestion/pipeline.py` | service | CRUD | `backend/src/dotmd/ingestion/pipeline.py` | exact |
| `backend/src/dotmd/api/service.py` | service | request-response | `backend/src/dotmd/api/service.py` | exact |
| `backend/src/dotmd/cli.py` | controller | request-response | `backend/src/dotmd/cli.py` | exact |
| `backend/tests/storage/test_surreal_metadata.py` | test | CRUD | `backend/tests/storage/test_metadata_m2m.py` | exact |
| `backend/tests/storage/test_surreal_vector.py` | test | CRUD | `backend/tests/test_vector_delete.py` | exact |
| `backend/tests/storage/test_surreal_graph.py` | test | request-response | `backend/tests/storage/test_falkordb_graph.py` | exact |
| `backend/tests/ingestion/test_surreal_migration.py` | test | batch | `backend/tests/ingestion/test_pipeline_purge.py` | role-match |
| `backend/tests/search/test_surreal_parity.py` | test | request-response | `backend/tests/ingestion/test_metadata_only_reindex.py` | dataflow-match |

## Pattern Assignments

### `backend/src/dotmd/storage/surreal_metadata.py` (model, CRUD)

**Analog:** `backend/src/dotmd/storage/metadata.py`

**Imports + shared-connection init** [`backend/src/dotmd/storage/metadata.py:340-375`]
```python
def __init__(
    self,
    db_path: Path | None = None,
    table_name: str = "chunks",
    fts_table_name: str = "chunks_fts",
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    self._db_path = db_path
    self._table = table_name
    self._fts_table = fts_table_name
    if conn is not None:
        self._conn = _ConnProxy(conn) if not isinstance(conn, _ConnProxy) else conn
    else:
        ...
        self._conn.execute("PRAGMA journal_mode=WAL")
    self._conn.execute(_CREATE_CHUNKS_TPL.format(table=self._table))
    self._conn.execute(_CREATE_STATS)
    self.ensure_source_document_table()
    self.ensure_resource_bindings_table()
    self.ensure_source_state_tables()
    self.backfill_resource_bindings_from_source_documents(conn=self._conn)
```

**Schema/bootstrap pattern** [`backend/src/dotmd/storage/metadata.py:395-417`]
```python
def ensure_chunk_source_provenance_table(self, strategy: str) -> None:
    table = f"chunk_source_provenance_{strategy}"
    idx_name = f"idx_chunk_source_provenance_{strategy}_chunk_id"
    self._conn.execute(_CREATE_CHUNK_SOURCE_PROVENANCE_TPL.format(table=table))
    self._conn.execute(
        _CREATE_CHUNK_SOURCE_PROVENANCE_IDX_TPL.format(
            idx_name=idx_name,
            table=table,
        )
    )
    self._conn.commit()

def ensure_m2m_table(self, strategy: str) -> None:
    m2m_table = f"chunk_file_paths_{strategy}"
    idx_name = f"idx_chunk_file_paths_{strategy}_file_path"
    self._conn.execute(_CREATE_M2M_TPL.format(m2m_table=m2m_table))
    self._conn.execute(_CREATE_M2M_IDX_TPL.format(idx_name=idx_name, m2m_table=m2m_table))
    self._conn.commit()
```

**Caller-owned transaction pattern for source state** [`backend/src/dotmd/storage/metadata.py:421-445`, `583-608`]
```python
def upsert_source_document(self, document: SourceDocument, *, conn: _SQLiteConn) -> None:
    conn.execute(
        _UPSERT_SOURCE_DOCUMENT,
        (
            document.namespace,
            document.document_ref,
            document.ref,
            document.source_uri,
            str(document.file_path) if document.file_path is not None else None,
            ...
        ),
    )

def commit_source_checkpoint(..., *, conn: _SQLiteConn, metadata_json: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO source_checkpoints (...) VALUES (?, ?, ?, NULL, ?) "
        "ON CONFLICT(namespace) DO UPDATE SET ...",
        (...),
    )
```

**Content-addressed chunk + holder pattern** [`backend/src/dotmd/storage/metadata.py:1179-1302`]
```python
def insert_chunk(..., _commit: bool = True) -> None:
    self._conn.execute(
        _INSERT_CHUNK_TPL.format(table=table),
        (chunk_id, json.dumps(heading_hierarchy), level, text),
    )
    if _commit:
        self._conn.commit()

def add_file_path(..., _commit: bool = True) -> None:
    self._conn.execute(
        _INSERT_M2M_TPL.format(m2m_table=m2m_table),
        (chunk_id, file_path, chunk_index),
    )

def get_file_paths_for_chunk_ids(...) -> dict[str, list[str]]:
    rows = self._conn.execute(
        f"SELECT chunk_id, file_path FROM {m2m_table} "
        f"WHERE chunk_id IN ({placeholders}) "
        f"ORDER BY chunk_id, file_path",
        list(chunk_ids),
    ).fetchall()
```

**Atomic purge boundary** [`backend/src/dotmd/storage/metadata.py:1397-1492`, `1554-1572`]
```python
def delete_m2m_for_file(..., conn: _SQLiteConn) -> list[str]:
    affected = [...]
    conn.execute(f"DELETE FROM {m2m_table} WHERE file_path = ?", (file_path,))
    still_held = {...}
    return [cid for cid in affected if cid not in still_held]

def delete_orphan_chunks(..., conn: _SQLiteConn) -> None:
    conn.execute(
        f"DELETE FROM {table} WHERE chunk_id IN ({placeholders})",
        list(chunk_ids),
    )

def delete_chunks_by_file(self, file_path: str) -> int:
    raw.execute("BEGIN")
    try:
        orphans = self.delete_m2m_for_file(strategy, file_path, conn=self._conn)
        self.delete_orphan_chunks(strategy, orphans, conn=self._conn)
        raw.execute("COMMIT")
```

**Apply to Surreal spike:** keep the same public method names and transaction ownership. The Surreal-backed store should preserve chunk/resource/provenance semantics first, not redesign them.

---

### `backend/src/dotmd/storage/surreal_vector.py` (model, CRUD)

**Analog:** `backend/src/dotmd/storage/sqlite_vec.py`

**Imports + table-name derivation** [`backend/src/dotmd/storage/sqlite_vec.py:45-84`]
```python
def __init__(..., table_name: str = "vec_chunks", *, conn: sqlite3.Connection | None = None) -> None:
    ...
    suffix = table_name.removeprefix("vec_chunks")
    self._META_TABLE = f"vec_meta{suffix}"
    self._CONFIG_TABLE = f"vec_config{suffix}"
```

**Metadata/config bootstrap** [`backend/src/dotmd/storage/sqlite_vec.py:86-118`]
```python
conn.execute(f"""
    CREATE TABLE IF NOT EXISTS {self._META_TABLE} (
        rowid INTEGER PRIMARY KEY AUTOINCREMENT,
        chunk_id TEXT NOT NULL UNIQUE,
        text_hash TEXT
    )
""")
self._maybe_add_text_hash_column(conn)
conn.execute(f"""
    CREATE TABLE IF NOT EXISTS {self._CONFIG_TABLE} (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
""")
```

**Add/search/delete contract** [`backend/src/dotmd/storage/sqlite_vec.py:199-248`, `250-353`, `434-474`]
```python
def add_chunks(..., overwrite: bool = True, text_hashes: dict[str, str] | None = None) -> None:
    if overwrite:
        conn.execute(f"DELETE FROM {self._VEC_TABLE}")
        conn.execute(f"DELETE FROM {self._META_TABLE}")
    for chunk, embedding in zip(chunks, embeddings, strict=False):
        th = text_hashes.get(chunk.chunk_id) if text_hashes else None
        cur = conn.execute(
            f"INSERT OR IGNORE INTO {self._META_TABLE} (chunk_id, text_hash) VALUES (?, ?)",
            (chunk.chunk_id, th),
        )
        if cur.rowcount and cur.lastrowid:
            conn.execute(
                f"INSERT INTO {self._VEC_TABLE} (rowid, embedding) VALUES (?, ?)",
                (cur.lastrowid, _serialize_f32(embedding)),
            )

def delete_by_chunk_ids(..., conn: sqlite3.Connection) -> int:
    vec_meta_tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"vec_meta_{strategy}_%",),
        ).fetchall()
    ]

def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
    rows = conn.execute(
        f"""
        SELECT m.chunk_id, v.distance
        FROM (
            SELECT rowid, distance
            FROM {self._VEC_TABLE}
            WHERE embedding MATCH ? AND k = ?
        ) v
        JOIN {self._META_TABLE} m ON m.rowid = v.rowid
        """,
        (_serialize_f32(query_embedding), top_k),
    ).fetchall()
    return [(row[0], 1.0 - row[1]) for row in rows]
```

**Embedding reuse hook** [`backend/src/dotmd/storage/sqlite_vec.py:367-432`]
```python
def lookup_embeddings_by_text_hash(self, text_hashes: list[str]) -> dict[str, list[float]]:
    rows = conn.execute(
        f"""
        SELECT vm.text_hash, vc.embedding
        FROM {self._META_TABLE} vm
        JOIN {self._VEC_TABLE} vc ON vm.rowid = vc.rowid
        WHERE vm.text_hash IN ({placeholders})
        """,
        batch,
    ).fetchall()
```

**Apply to Surreal spike:** mirror this contract exactly. The planner should treat imported embeddings as existing data, plus config/identity metadata, not as TEI work.

---

### `backend/src/dotmd/storage/surreal_graph.py` (model, graph request-response)

**Analog:** `backend/src/dotmd/storage/falkordb_graph.py`

**Connection-once pattern** [`backend/src/dotmd/storage/falkordb_graph.py:37-64`]
```python
def __init__(self, url: str = "redis://localhost:6379", graph_name: str = "dotmd") -> None:
    parsed = urlparse(url)
    ...
    self._db = FalkorDB(host=host, port=port)
    self._graph = self._db.select_graph(graph_name)
    ...
    for label in ("File", "Section", "Entity", "Tag", "Node"):
        try:
            self._graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
```

**Node/edge upsert pattern** [`backend/src/dotmd/storage/falkordb_graph.py:68-194`]
```python
self._graph.query(
    "MERGE (s:Section:Node {id: $id}) "
    "SET s.heading = $heading, s.level = $level, "
    "s.file_path = $file_path, s.text_preview = $text_preview",
    params={...},
)

self._graph.query(
    "MATCH (a:Node {id: $src}), (b:Node {id: $tgt}) "
    "MERGE (a)-[r:REL]->(b) "
    "SET r.rel_type = $rel_type, r.weight = $weight",
    params={...},
)
```

**Batch-write pattern** [`backend/src/dotmd/storage/falkordb_graph.py:198-249`]
```python
self._graph.query(
    "UNWIND $rows AS row "
    "MERGE (s:Section:Node {id: row.chunk_id}) "
    "SET s.heading = row.heading, s.level = row.level, "
    "s.file_path = row.file_path, s.text_preview = row.text_preview",
    params={"rows": sections},
)
```

**Bounded graph-direct retrieval** [`backend/src/dotmd/storage/falkordb_graph.py:253-275`]
```python
result = self._graph.ro_query(
    "MATCH (:Section {id: $id})-[r1:REL]->(mid:Node)<-[r2:REL]-(s:Section) "
    "WHERE (mid:Entity OR mid:Tag) "
    "AND r1.rel_type IN ['MENTIONS', 'HAS_TAG'] "
    "AND r2.rel_type IN ['MENTIONS', 'HAS_TAG'] "
    "RETURN DISTINCT s.id, r2.rel_type, coalesce(r2.weight, 1.0)",
    params={"id": chunk_id},
)
```

**Delete semantics** [`backend/src/dotmd/storage/falkordb_graph.py:279-356`, `384-400`]
```python
def delete_chunks_from_graph(self, chunk_ids: list[str]) -> None:
    ...
    self._graph.query(
        "MATCH (s:Section {id: $id}) DETACH DELETE s",
        params={"id": chunk_id},
    )

def delete_all(self) -> None:
    try:
        self._graph.delete()
    except _FALKOR_ERRORS:
        ...
    self._graph = self._db.select_graph(self._graph_name)
```

**Apply to Surreal spike:** preserve the bounded traversal semantics and the File/Section/Entity/Tag identity model even if Surreal relations look more flexible.

---

### `backend/src/dotmd/ingestion/migrate_surreal.py` (utility, batch)

**Analog:** `backend/src/dotmd/ingestion/migration.py`

**Top-level migration flow** [`backend/src/dotmd/ingestion/migration.py:30-119`]
```python
def run_migration(index_dir: Path, strategy: str = "heading_512_50", embedding_model: str = ...) -> None:
    ...
    shutil.copy2(metadata_path, index_dir / "metadata.db.bak")
    ...
    conn = sqlite3.connect(str(index_path))
    conn.execute("PRAGMA journal_mode=WAL")
    ...
    try:
        _copy_metadata(conn, metadata_path, strategy, model_suffix)
        if vec_path.exists():
            _copy_vectors(conn, vec_path, strategy, model_suffix)
        _rename_graph(index_dir, strategy)
        _verify(conn, strategy, model_suffix)
        conn.commit()
    except (sqlite3.Error, OSError):
        ...
        if index_path.exists():
            index_path.unlink()
```

**Transform-first row copy pattern** [`backend/src/dotmd/ingestion/migration.py:127-207`, `210-303`]
```python
conn.execute(f"ATTACH '{metadata_path}' AS meta_old")
conn.execute(f"CREATE TABLE chunks_{strategy} AS SELECT * FROM meta_old.chunks")
...
conn.execute(
    f"INSERT INTO chunks_fts_{strategy}(chunk_id, text) "
    "SELECT chunk_id, text FROM meta_old.chunks_fts"
)
...
rows = conn.execute(
    f"SELECT vm.rowid, vc.embedding "
    f"FROM vec_old.{old_meta} vm "
    f"JOIN vec_old.{old_vec} vc ON vm.rowid = vc.rowid"
).fetchall()
for rowid, embedding in rows:
    conn.execute(
        f"INSERT INTO {new_vec}(rowid, embedding) VALUES (?, ?)",
        (rowid, embedding),
    )
```

**CLI-safe standalone script pattern** [`backend/src/dotmd/ingestion/migration.py:343-353`]
```python
if __name__ == "__main__":
    ...
    index_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".dotmd"
    if needs_migration(index_dir):
        run_migration(index_dir)
```

**Supplemental dry-run/apply pattern** [`backend/src/dotmd/ingestion/migrate_fingerprints_to_blake3.py:83-129`, `132-211`]
```python
def _migrate_table(...) -> tuple[int, int, list[str]]:
    ...
    if apply and updates:
        conn.executemany(...)
    if apply and missing:
        conn.execute(...)

def run_migration(index_db_path: Path, apply: bool) -> int:
    ...
    conn.execute("BEGIN")
    try:
        ...
        if all_errors:
            conn.execute("ROLLBACK")
            return 3
        if apply:
            conn.execute("COMMIT")
        else:
            conn.execute("ROLLBACK")
```

**Apply to Surreal spike:** the migration tool should support copied snapshots, explicit verification, dry-run counting, and rollback-safe failure handling.

---

### `backend/src/dotmd/core/config.py` (config, request-response)

**Analog:** `backend/src/dotmd/core/config.py`

**BaseSettings + env prefix pattern** [`backend/src/dotmd/core/config.py:55-80`]
```python
class Settings(BaseSettings):
    model_config = {
        "env_prefix": "DOTMD_",
        "toml_file": str(Path.home() / ".dotmd" / "config.toml"),
        "populate_by_name": True,
    }
    data_dir: Path = Path()
    index_dir: Path = Path.home() / ".dotmd"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_url: str
```

**Add new storage settings here, matching existing field/validator style** [`backend/src/dotmd/core/config.py:205-208`, `333-370`, `415-429`]
```python
# Graph
graph_max_hops: int = DEFAULT_GRAPH_MAX_HOPS
falkordb_url: str = DEFAULT_FALKORDB_URL

def validate_for_runtime(self) -> None:
    ...
    if not self.falkordb_url:
        errors.append("falkordb_url must be set for runtime startup")

def load_settings(**overrides: object) -> Settings:
    return Settings(**overrides)
```

**Apply to Surreal spike:** add any `DOTMD_SURREAL_*` fields in this file, and preserve runtime validation at startup rather than deferring failures to first query.

---

### `backend/pyproject.toml` (config, request-response)

**Analog:** `backend/pyproject.toml`

**Dependency list pattern** [`backend/pyproject.toml:8-27`]
```toml
dependencies = [
    "blake3>=1.0",
    "click>=8.0",
    "sentence-transformers>=3.0",
    "sqlite-vec>=0.1.6",
    "FalkorDB>=1.6.0",
    "pydantic-settings[toml]>=2.14.1",
    "fastapi>=0.110",
    "httpx>=0.27",
]
```

**Layering constraint pattern** [`backend/pyproject.toml:143-171`]
```toml
[[tool.importlinter.contracts]]
name = "Storage layer does not depend on API or ingestion orchestration"
type = "forbidden"
source_modules = [
    "dotmd.storage",
]
forbidden_modules = [
    "dotmd.api",
    "dotmd.ingestion",
]
```

**Apply to Surreal spike:** if `surrealdb` is added, keep the storage-layer isolation intact and do not introduce storage-to-ingestion imports.

---

### `backend/src/dotmd/ingestion/pipeline.py` (service, CRUD)

**Analog:** `backend/src/dotmd/ingestion/pipeline.py`

**Backend factory + shared-store wiring** [`backend/src/dotmd/ingestion/pipeline.py:161-168`, `188-307`]
```python
def _create_graph_store(settings: Settings) -> GraphStoreProtocol:
    from dotmd.storage.falkordb_graph import FalkorDBGraphStore
    return FalkorDBGraphStore(url=settings.falkordb_url, graph_name="dotmd")

self._conn = sqlite3.connect(
    str(settings.index_db_path),
    check_same_thread=False,
    isolation_level=None,
)
...
self._metadata_store = SQLiteMetadataStore(...)
self._metadata_store.ensure_m2m_table(strategy)
self._vector_store: VectorStoreProtocol = SQLiteVecVectorStore(...)
self._graph_store = _create_graph_store(settings)
self._semantic_engine = SemanticSearchEngine(...)
self._keyword_engine = FTS5SearchEngine(self._conn, table_name=self._fts_table)
```

**Apply to Surreal spike:** if the spike includes real pipeline wiring, hide it behind the existing store factory boundary and keep one startup-loaded backend instance, per AGENTS.

---

### `backend/src/dotmd/api/service.py` (service, request-response)

**Analog:** `backend/src/dotmd/api/service.py`

**Facade wiring pattern** [`backend/src/dotmd/api/service.py:246-281`]
```python
self._settings = settings or load_settings()
self._pipeline = IndexingPipeline(self._settings)
self._semantic_engine = SemanticSearchEngine(...)
self._keyword_engine = self._pipeline.keyword_engine
self._graph_engine = GraphSearchEngine(
    self._pipeline.graph_store,
    cast(MetadataStoreProtocol, self._pipeline.metadata_store),
)
self._graph_direct_engine = GraphDirectEngine(
    self._pipeline.graph_store,
)
```

**Reindex entry point pattern** [`backend/src/dotmd/api/service.py:430-455`]
```python
def reindex(self, store: str) -> int:
    if store == "all":
        n = self._pipeline.reindex_fts5()
        self._pipeline.reindex_vectors()
        self._pipeline.reindex_graph()
        return n
```

**Drop/cleanup surface** [`backend/src/dotmd/api/service.py:1985-2008`]
```python
def drop_vectors(self) -> None:
    self._pipeline.drop_vectors()

def drop_chunks(self) -> None:
    self._pipeline.drop_chunks()
```

**Apply to Surreal spike:** if you expose spike commands through the service, keep them here rather than calling migration/backends directly from CLI code.

---

### `backend/src/dotmd/cli.py` (controller, request-response)

**Analog:** `backend/src/dotmd/cli.py`

**Root command + context override pattern** [`backend/src/dotmd/cli.py:22-55`]
```python
@click.group()
@click.option("--index-dir", ..., envvar="DOTMD_INDEX_DIR")
@click.pass_context
def main(ctx: click.Context, verbose: bool, index_dir: Path | None) -> None:
    setup_logging(verbose=verbose)
    ctx.ensure_object(dict)
    ctx.obj["index_dir"] = index_dir

def _get_service_from_ctx(ctx: click.Context, **overrides: object) -> DotMDService:
    index_dir = (ctx.obj or {}).get("index_dir")
    if index_dir is not None:
        overrides.setdefault("index_dir", index_dir)
    return _get_service(**overrides)
```

**Reindex subcommand shape** [`backend/src/dotmd/cli.py:327-380`]
```python
@main.group()
def reindex() -> None:
    """Rebuild a specific index from stored chunks."""

@reindex.command("vectors")
def reindex_vectors() -> None:
    service = _get_service()
    click.echo("Rebuilding vector index...")
    n = service.reindex("vectors")
```

**Feedback store path pattern for sidecar DBs** [`backend/src/dotmd/cli.py:599-603`, `661-732`]
```python
def _get_feedback_store(ctx: click.Context) -> FeedbackStore:
    index_dir = (ctx.obj or {}).get("index_dir")
    if index_dir is None:
        index_dir = load_settings().index_dir
    return FeedbackStore(Path(index_dir) / "feedback.db")
```

**Apply to Surreal spike:** if the phase adds a developer-only `surreal` or `storage-eval` command, copy the existing click grouping, `click.echo`, and service-delegation style.

---

### `backend/tests/storage/test_surreal_metadata.py` (test, CRUD)

**Analog:** `backend/tests/storage/test_metadata_m2m.py`

**Fixture/helper shape** [`backend/tests/storage/test_metadata_m2m.py:39-112`]
```python
def _build_m2m_store(tmp_path: Path) -> SQLiteMetadataStore:
    db_path = tmp_path / "metadata.db"
    store = SQLiteMetadataStore(db_path=db_path, table_name=f"chunks_{STRATEGY}")
    store.ensure_m2m_table(STRATEGY)
    return store

def _source_document(path: Path) -> SourceDocument:
    return SourceDocument(...)
```

**Idempotency + single-query assertions** [`backend/tests/storage/test_metadata_m2m.py:115-219`]
```python
store.insert_chunk(...)
store.insert_chunk(...)
count = conn.execute(...).fetchone()[0]
assert count == 1

store._conn.execute = counting_execute
result = store.get_file_paths_for_chunk_ids(STRATEGY, chunk_ids)
assert call_count["n"] <= 1
```

**Caller-owned transaction assertion** [`backend/tests/storage/test_metadata_m2m.py:222-251`]
```python
conn = store._conn
orphans = store.delete_m2m_for_file(STRATEGY, "/file_a.md", conn=conn)
conn.commit()
assert sole_cid in orphans
assert shared_cid not in orphans
```

**Apply to Surreal spike:** use this style to verify chunk/resource/provenance parity against a copied fixture corpus, not only happy-path inserts.

---

### `backend/tests/storage/test_surreal_vector.py` (test, CRUD)

**Analog:** `backend/tests/test_vector_delete.py`

**Chunk fixture shape** [`backend/tests/test_vector_delete.py:9-28`]
```python
def _make_chunk(chunk_id: str, file_path: str = "test.md") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        file_paths=[Path(file_path)],
        heading_hierarchy=["Test"],
        level=1,
        text=f"Content of {chunk_id}",
        chunk_index=0,
    )
```

**Behavior-driven vector tests** [`backend/tests/test_vector_delete.py:31-128`]
```python
deleted = vector_store.delete_vectors_by_chunk_ids(["c1", "c2"])
assert deleted == 2
assert vector_store.count() == 1

vector_store.add_chunks(new_chunks, new_embeddings, overwrite=False)
assert vector_store.count() == 5
results = vector_store.search(_make_embedding(), top_k=10)
```

**Apply to Surreal spike:** mirror these tests for imported embeddings, overwrite behavior, delete behavior, and search visibility.

---

### `backend/tests/storage/test_surreal_graph.py` (test, request-response)

**Analog:** `backend/tests/storage/test_falkordb_graph.py`

**Query-shape assertion pattern** [`backend/tests/storage/test_falkordb_graph.py:8-44`]
```python
store = FalkorDBGraphStore.__new__(FalkorDBGraphStore)
graph = _FakeGraph([...])
store.__dict__["_graph"] = graph

neighbors = store.get_related_sections("chunk-1")

assert "[*1.." not in graph.query_text
assert "(:Section {id: $id})-[r1:REL]->(mid:Node)<-[r2:REL]-(s:Section)" in graph.query_text
```

**Apply to Surreal spike:** assert SurrealQL stays bounded and does not drift into generic recursive traversal.

---

### `backend/tests/ingestion/test_surreal_migration.py` (test, batch)

**Analog:** `backend/tests/ingestion/test_pipeline_purge.py`

**Snapshot-fixture schema builder** [`backend/tests/ingestion/test_pipeline_purge.py:25-94`]
```python
def _build_post_v16_db(tmp_path: Path, strategy: str = "heading_512_50") -> Path:
    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(f"""
        CREATE TABLE chunks_{strategy} (...);
        CREATE TABLE chunk_file_paths_{strategy} (...);
        CREATE VIRTUAL TABLE chunks_fts_{strategy} USING fts5(...);
        CREATE TABLE vec_meta_{strategy}_{MODEL} (...);
        CREATE TABLE source_documents (...);
        CREATE TABLE resource_bindings (...);
        CREATE TABLE chunk_source_provenance_{strategy} (...);
    """)
```

**Fixture population helpers** [`backend/tests/ingestion/test_pipeline_purge.py:97-207`]
```python
def _insert_chunk(...): ...
def _add_m2m(...): ...
def _add_source_document(...): ...
def _add_resource_binding(...): ...
def _add_chunk_provenance(...): ...
```

**Apply to Surreal spike:** use this style to build deterministic SQLite/Falkor source fixtures and assert row-count parity after import, dry-run, and rollback paths.

---

### `backend/tests/search/test_surreal_parity.py` (test, request-response)

**Analog:** `backend/tests/ingestion/test_metadata_only_reindex.py`

**Mocked pipeline parity fixture** [`backend/tests/ingestion/test_metadata_only_reindex.py:78-116`]
```python
pipeline = IndexingPipeline(settings)
mock_engine = MagicMock()
mock_engine.encode_batch = mock_encode_batch
mock_engine.get_tei_model_id = MagicMock(return_value="test-model")
pipeline._semantic_engine = mock_engine
```

**Parity/invariant assertion style** [`backend/tests/ingestion/test_metadata_only_reindex.py:119-189`]
```python
pipeline.index(pipeline_settings.data_dir)
...
pipeline.index(pipeline_settings.data_dir)
assert len(encode_calls) == 1
assert len(encode_calls[0]) == 1
```

**Direct state inspection style** [`backend/tests/ingestion/test_metadata_only_reindex.py:24-60`]
```python
def _vector_chunk_ids(pipeline) -> set[str]:
    return {
        row[0]
        for row in pipeline._conn.execute(
            f"SELECT chunk_id FROM {pipeline._vector_store._META_TABLE}"
        ).fetchall()
    }

def _fts_meta_for_chunk(pipeline, chunk_id: str) -> tuple[str, str]:
    row = pipeline._conn.execute(
        f"SELECT title, tags FROM {pipeline._fts_table} WHERE chunk_id = ?",
        (chunk_id,),
    ).fetchone()
```

**Apply to Surreal spike:** build parity tests around exact result shapes and counts for FTS, vector, and graph-direct behavior from the same corpus.

## Shared Patterns

### Storage Protocol Boundary
**Source:** `backend/src/dotmd/storage/base.py:26-122`, `130-378`, `386-487`

Use the existing protocol surfaces verbatim for any Surreal-backed adapter:
```python
@runtime_checkable
class VectorStoreProtocol(Protocol):
    def add_chunks(..., overwrite: bool = True, text_hashes: dict[str, str] | None = None) -> None: ...
    def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]: ...
    def delete_vectors_by_chunk_ids(self, chunk_ids: list[str]) -> int: ...
    def count(self) -> int: ...
    def lookup_embeddings_by_text_hash(self, text_hashes: list[str]) -> dict[str, list[float]]: ...
```

### Startup-Loaded Backends
**Source:** `backend/src/dotmd/ingestion/pipeline.py:200-246`, `296-307`

All store/search backend construction happens once in pipeline startup:
```python
self._conn = sqlite3.connect(..., isolation_level=None)
...
self._metadata_store = SQLiteMetadataStore(...)
self._vector_store: VectorStoreProtocol = SQLiteVecVectorStore(...)
self._graph_store = _create_graph_store(settings)
self._semantic_engine = SemanticSearchEngine(...)
self._keyword_engine = FTS5SearchEngine(...)
```

Apply to any Surreal wiring. Do not create per-request clients.

### Service Facade Only
**Source:** `backend/src/dotmd/api/service.py:246-281`, `430-455`

Public orchestration belongs in `DotMDService`, not directly in storage or CLI:
```python
self._pipeline = IndexingPipeline(self._settings)
...
def reindex(self, store: str) -> int:
    ...
```

### Atomic Batch/Delete Semantics
**Source:** `backend/src/dotmd/storage/metadata.py:1397-1492`, `1554-1572`; `backend/src/dotmd/storage/sqlite_vec.py:282-353`; `backend/src/dotmd/search/fts5.py:196-223`

For batch mutation paths, keep caller-owned transaction boundaries and avoid internal commits when the caller supplies a connection.

### Search Parity Surfaces
**Source:** `backend/src/dotmd/search/fts5.py:17-33`, `131-168`, `273-308`; `backend/src/dotmd/search/semantic.py:72-90`, `127-192`, `232-251`; `backend/src/dotmd/search/graph_direct.py:37-125`

The Surreal evaluation must preserve:
- weighted full-text behavior with title/tags/body distinctions,
- vector search returning `(chunk_id, score)` pairs,
- graph-direct entity-catalog retrieval rather than generic graph traversal.

### Migration Discipline
**Source:** `backend/src/dotmd/ingestion/migration.py:60-119`; `backend/src/dotmd/ingestion/migrate_fingerprints_to_blake3.py:161-199`

Migration scripts in this repo follow:
- explicit backup/snapshot first,
- transform-only data movement,
- dry-run/apply or rollback-safe failure handling,
- verification logging before completion.

## No Analog Found

None. The codebase already contains strong analogs for storage adapters, migration scripts, backend wiring, CLI delegation, and parity-style tests.

## Metadata

**Analog search scope:** `backend/src/dotmd/{storage,ingestion,search,api,core}`, `backend/tests/{storage,ingestion}`
**Files scanned:** 60+
**Pattern extraction date:** 2026-06-12
