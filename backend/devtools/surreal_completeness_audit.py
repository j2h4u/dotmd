"""Read-only SurrealDB completeness audit for dotMD retrieval data.

The audit reads the live retrieval settings from dotMD Settings / nested DOTMD_*
configuration, runs a bounded set of read-only queries, and emits a JSON report
plus a short human summary. It never writes to SurrealDB.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotmd.core.config import Settings
from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
from dotmd.storage.surreal_schema import (
    DEFAULT_HNSW_M,
    build_surreal_embedding_hnsw_index_statement,
    surreal_embedding_hnsw_index_name,
    surreal_embedding_shard_tables,
)

_GRAPH_TABLES = ("files", "sections", "entities", "tags", "relations")
_CHUNK_TABLE = "chunks"
_PROVENANCE_TABLE = "provenance"


@dataclass(slots=True, frozen=True)
class SurrealCompletenessAuditSettings:
    url: str
    namespace: str
    database: str
    username: str | None
    password: str | None
    access_token: str | None
    embedding_dimension: int
    embedding_shard_count: int
    hnsw_ef: int
    vector_index_type: str
    hnsw_m: int = DEFAULT_HNSW_M


@dataclass(slots=True, frozen=True)
class SurrealCompletenessAuditReportSettings:
    url: str
    namespace: str
    database: str
    auth_mode: str
    has_username: bool
    embedding_dimension: int
    embedding_shard_count: int
    hnsw_ef: int
    vector_index_type: str
    hnsw_m: int = DEFAULT_HNSW_M


@dataclass(slots=True, frozen=True)
class TableIndexAudit:
    table: str
    expected_index_names: tuple[str, ...]
    expected_index_statements: tuple[str, ...]
    observed_index_names: tuple[str, ...]
    observed_index_statements: tuple[str, ...]
    missing_index_names: tuple[str, ...]
    definition_mismatches: tuple[dict[str, str], ...]
    unexpected_index_names: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class CompletenessAuditReport:
    generated_at: str
    status: str
    settings: SurrealCompletenessAuditReportSettings
    counts: dict[str, Any]
    coverage: dict[str, Any]
    provenance_fanout_by_chunk_id: list[dict[str, Any]]
    duplicate_provenance_keys: list[dict[str, Any]]
    embedding_distribution: dict[str, Any]
    index_audits: dict[str, TableIndexAudit]
    graph_table_counts: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: object) -> str:
    return str(value)


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _query_with_progress(
    connection: Any,
    statement: str,
    variables: dict[str, Any] | None = None,
    *,
    label: str,
    raw: bool = False,
) -> Any:
    started_at = perf_counter()
    _print_progress(f"[audit] {label}: start")
    try:
        if raw:
            result = connection.query_raw(statement, variables)
        else:
            result = connection.query(statement, variables)
    except Exception:
        elapsed = perf_counter() - started_at
        _print_progress(f"[audit] {label}: failed after {elapsed:.3f}s")
        raise
    elapsed = perf_counter() - started_at
    _print_progress(f"[audit] {label}: done in {elapsed:.3f}s")
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _coerce_int(raw: str | None, *, field_name: str, default: int | None = None) -> int:
    if raw is None or raw == "":
        if default is None:
            raise ValueError(f"{field_name} must be set")
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def read_settings_from_env() -> SurrealCompletenessAuditSettings:
    settings = Settings()
    url = (settings.surreal_retrieval.url or "").strip()
    namespace = settings.surreal_retrieval.namespace.strip()
    database = (settings.surreal_retrieval.database or "").strip()
    if not url:
        raise ValueError("surreal_retrieval.url must be set")
    if not namespace:
        raise ValueError("surreal_retrieval.namespace must be set")
    if not database:
        raise ValueError("surreal_retrieval.database must be set")

    username = settings.surreal_retrieval.username
    password = settings.surreal_retrieval.password
    access_token = settings.surreal_retrieval.access_token
    has_username = bool(username)
    has_password = bool(password)
    if has_username != has_password:
        raise ValueError(
            "surreal_retrieval.username and surreal_retrieval.password must be set together"
        )
    if (has_username or has_password) and access_token:
        raise ValueError(
            "surreal_retrieval.access_token must not be combined with username/password auth"
        )

    if settings.surreal_retrieval.embedding_dimension is None:
        raise ValueError("surreal_retrieval.embedding_dimension must be set")
    embedding_dimension = settings.surreal_retrieval.embedding_dimension
    embedding_shard_count = settings.surreal_retrieval.embedding_shard_count
    hnsw_ef = settings.surreal_retrieval.hnsw_ef
    vector_index_type = settings.surreal_retrieval.vector_index_type.strip().upper()
    hnsw_m = _coerce_int(
        os.environ.get("DOTMD_SURREAL_RETRIEVAL__HNSW_M"),
        field_name="DOTMD_SURREAL_RETRIEVAL__HNSW_M",
        default=DEFAULT_HNSW_M,
    )
    return SurrealCompletenessAuditSettings(
        url=url,
        namespace=namespace,
        database=database,
        username=username,
        password=password,
        access_token=access_token,
        embedding_dimension=embedding_dimension,
        embedding_shard_count=embedding_shard_count,
        hnsw_ef=hnsw_ef,
        vector_index_type=vector_index_type,
        hnsw_m=hnsw_m,
    )


def _report_settings_from_settings(
    settings: SurrealCompletenessAuditSettings,
) -> SurrealCompletenessAuditReportSettings:
    if settings.access_token:
        auth_mode = "access_token"
    elif settings.username or settings.password:
        auth_mode = "username_password"
    else:
        auth_mode = "none"
    return SurrealCompletenessAuditReportSettings(
        url=settings.url,
        namespace=settings.namespace,
        database=settings.database,
        auth_mode=auth_mode,
        has_username=bool(settings.username),
        embedding_dimension=settings.embedding_dimension,
        embedding_shard_count=settings.embedding_shard_count,
        hnsw_ef=settings.hnsw_ef,
        vector_index_type=settings.vector_index_type,
        hnsw_m=settings.hnsw_m,
    )


def build_connection(settings: SurrealCompletenessAuditSettings) -> SurrealConnection:
    return SurrealConnection(
        SurrealStoreConfig(
            url=settings.url,
            namespace=settings.namespace,
            database=settings.database,
            username=settings.username,
            password=settings.password,
            access_token=settings.access_token,
        )
    )


def _normalize_result(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(item) for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        if "result" in result:
            return _normalize_result(result["result"])
        if "count" in result:
            return [dict(result)]
    return []


def _safe_query_rows(
    connection: Any, statement: str, variables: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    try:
        return _normalize_result(
            _query_with_progress(connection, statement, variables, label=statement)
        )
    except Exception as exc:
        if "does not exist" in str(exc).lower():
            return []
        raise


def _safe_query_raw(
    connection: Any, statement: str, variables: dict[str, Any] | None = None
) -> Any:
    try:
        return _query_with_progress(connection, statement, variables, label=statement, raw=True)
    except Exception as exc:
        if "does not exist" in str(exc).lower():
            return {}
        raise


def _count_table(connection: Any, table_name: str) -> int:
    rows = _safe_query_rows(connection, f"SELECT count() AS count FROM {table_name} GROUP ALL;")
    if not rows:
        return 0
    count = rows[0].get("count", 0)
    try:
        return int(count)
    except (TypeError, ValueError):
        return 0


def _fetch_table_rows(connection: Any, table_name: str, fields: str = "*") -> list[dict[str, Any]]:
    return _safe_query_rows(connection, f"SELECT {fields} FROM {table_name};")


def _fetch_table_rows_limited(
    connection: Any,
    table_name: str,
    *,
    fields: str = "*",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = f"SELECT {fields} FROM {table_name}"
    if limit is not None:
        statement += f" LIMIT {limit}"
    return _safe_query_rows(connection, f"{statement};")


def _surreal_string_array_literal(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(value, ensure_ascii=False) for value in values) + "]"


def _not_in_chunk_ids_clause(table_name: str) -> str:
    return f"chunk_id NOT IN (SELECT chunk_id FROM {table_name} GROUP ALL)"


def _table_index_definitions(info_payload: Any) -> dict[str, str]:
    index_definitions: dict[str, str] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            indexes = node.get("indexes")
            if isinstance(indexes, dict):
                for name, definition in indexes.items():
                    if isinstance(name, str):
                        index_definitions.setdefault(name, _definition_to_string(definition))
            elif isinstance(indexes, list):
                for item in indexes:
                    visit(item)

            name = node.get("name")
            definition = (
                node.get("statement")
                or node.get("definition")
                or node.get("sql")
                or node.get("value")
            )
            if isinstance(name, str) and isinstance(definition, str):
                index_definitions.setdefault(name, definition)

            for key, value in node.items():
                if key in {"indexes", "name", "statement", "definition", "sql", "value"}:
                    continue
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, str) and node.startswith("DEFINE INDEX "):
            name = node.split(" ", 3)[2] if len(node.split(" ", 3)) >= 3 else node
            index_definitions.setdefault(name, node)

    visit(info_payload)
    return index_definitions


def _definition_to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("statement", "definition", "sql"):
            item = value.get(key)
            if isinstance(item, str):
                return item
        return json.dumps(value, sort_keys=True, default=_json_default)
    if isinstance(value, list):
        return json.dumps(value, sort_keys=True, default=_json_default)
    return str(value)


def _normalize_index_identifier(value: str) -> str:
    return value.strip().strip("`").lower()


def _index_definition_signature(statement: str) -> tuple[Any, ...] | None:
    tokens = [
        token for token in re.findall(r"[^\s,;]+|,|;", statement.strip()) if token not in {",", ";"}
    ]
    if len(tokens) < 6:
        return None
    if tokens[0].upper() != "DEFINE" or tokens[1].upper() != "INDEX" or tokens[3].upper() != "ON":
        return None

    index_name = _normalize_index_identifier(tokens[2])
    position = 4
    if position < len(tokens) and tokens[position].upper() == "TABLE":
        position += 1
    if position >= len(tokens):
        return None

    table_name = _normalize_index_identifier(tokens[position])
    position += 1
    if position >= len(tokens):
        return None

    mode = tokens[position].upper()
    position += 1
    if mode not in {"COLUMNS", "FIELDS"}:
        return None

    field_tokens: list[str] = []
    while position < len(tokens) and tokens[position].upper() not in {"HNSW", "UNIQUE"}:
        field_tokens.append(tokens[position])
        position += 1

    fields = tuple(
        _normalize_index_identifier(field) for field in field_tokens if field and field != ","
    )

    if position < len(tokens) and tokens[position].upper() == "HNSW":
        position += 1
        hnsw_params: dict[str, str] = {}
        while position < len(tokens):
            key = tokens[position].upper()
            position += 1
            if position >= len(tokens):
                break
            hnsw_params[key] = tokens[position]
            position += 1
        return (
            "hnsw",
            index_name,
            table_name,
            fields,
            tuple(
                (
                    key,
                    hnsw_params.get(key, "").upper()
                    if key == "DIST" or key == "TYPE"
                    else hnsw_params.get(key, ""),
                )
                for key in ("DIMENSION", "DIST", "TYPE", "EFC", "M")
            ),
        )

    unique = any(token.upper() == "UNIQUE" for token in tokens[position:])
    return ("regular", index_name, table_name, fields, unique)


def _index_definition_matches(expected_statement: str, observed_statement: str) -> bool:
    expected_signature = _index_definition_signature(expected_statement)
    observed_signature = _index_definition_signature(observed_statement)
    if expected_signature is not None and observed_signature is not None:
        return expected_signature == observed_signature
    return expected_statement.strip() == observed_statement.strip()


def _expected_chunk_index_names() -> tuple[str, ...]:
    return ("chunks_chunk_id_idx", "chunks_ref_idx")


def _expected_chunk_index_statements() -> tuple[str, ...]:
    # Reuse the schema catalog for the authoritative chunk index definitions.
    from dotmd.storage.surreal_schema import build_dotmd_surreal_schema_plan

    schema_plan = build_dotmd_surreal_schema_plan()
    chunks_table = next(table for table in schema_plan.tables if table.name == _CHUNK_TABLE)
    return tuple(
        f"DEFINE INDEX {index.name} ON TABLE {_CHUNK_TABLE} COLUMNS {', '.join(index.columns)}"
        f"{' UNIQUE' if index.unique else ''};"
        for index in chunks_table.indexes
    )


def _expected_embedding_schema_index_names() -> tuple[str, ...]:
    from dotmd.storage.surreal_schema import build_dotmd_surreal_schema_plan

    schema_plan = build_dotmd_surreal_schema_plan()
    embeddings_table = next(table for table in schema_plan.tables if table.name == "embeddings")
    return tuple(index.name for index in embeddings_table.indexes)


def _expected_embedding_schema_index_statements() -> tuple[str, ...]:
    from dotmd.storage.surreal_schema import build_dotmd_surreal_schema_plan

    schema_plan = build_dotmd_surreal_schema_plan()
    embeddings_table = next(table for table in schema_plan.tables if table.name == "embeddings")
    return tuple(
        f"DEFINE INDEX {index.name} ON TABLE embeddings COLUMNS {', '.join(index.columns)}"
        f"{' UNIQUE' if index.unique else ''};"
        for index in embeddings_table.indexes
    )


def _expected_embedding_hnsw_index_statement(
    *,
    table_name: str,
    shard_index: int | None,
    settings: SurrealCompletenessAuditSettings,
) -> tuple[str, str]:
    index_name = (
        surreal_embedding_hnsw_index_name()
        if shard_index is None
        else surreal_embedding_hnsw_index_name(shard_index)
    )
    statement = build_surreal_embedding_hnsw_index_statement(
        table_name=table_name,
        index_name=index_name,
        embedding_dimension=settings.embedding_dimension,
        hnsw_m=settings.hnsw_m,
        hnsw_ef=settings.hnsw_ef,
        vector_index_type=settings.vector_index_type,
    )
    return index_name, statement


def _audit_index_table(
    connection: Any,
    *,
    table_name: str,
    expected_index_names: tuple[str, ...],
    expected_index_statements: tuple[str, ...],
) -> TableIndexAudit:
    info_payload = _safe_query_raw(connection, f"INFO FOR TABLE {table_name};")
    observed = _table_index_definitions(info_payload)
    observed_names = tuple(sorted(observed))
    observed_statements = tuple(sorted(observed.values()))
    expected_names = tuple(expected_index_names)
    missing = tuple(sorted(set(expected_names) - set(observed_names)))
    unexpected = tuple(sorted(set(observed_names) - set(expected_names)))
    definition_mismatches = tuple(
        {
            "index_name": name,
            "expected": expected_statement,
            "observed": observed.get(name, ""),
        }
        for name, expected_statement in zip(expected_names, expected_index_statements, strict=False)
        if name in observed and not _index_definition_matches(expected_statement, observed[name])
    )
    return TableIndexAudit(
        table=table_name,
        expected_index_names=expected_names,
        expected_index_statements=expected_index_statements,
        observed_index_names=observed_names,
        observed_index_statements=observed_statements,
        missing_index_names=missing,
        definition_mismatches=definition_mismatches,
        unexpected_index_names=unexpected,
    )


def _audit_embedding_distribution(
    rows: list[dict[str, Any]],
    *,
    configured_dimension: int,
    full_vector_dimension_scan: bool,
    sample_size: int,
    sampled_row_count: int,
) -> dict[str, Any]:
    model_counts: Counter[str] = Counter()
    dimension_counts: Counter[int | None] = Counter()
    model_dimension_counts: Counter[tuple[str, int | None]] = Counter()

    for row in rows:
        model = str(row.get("embedding_model") or "unknown")
        dimension_value = row.get("embedding_dimension")
        weight_value = row.get("count", 1)
        weight = int(weight_value) if isinstance(weight_value, (int, float)) else 1
        dimension = int(dimension_value) if isinstance(dimension_value, (int, float)) else None
        model_counts[model] += weight
        dimension_counts[dimension] += weight
        model_dimension_counts[(model, dimension)] += weight

    return {
        "configured_embedding_dimension": configured_dimension,
        "scan_mode": "exact" if full_vector_dimension_scan else "sample",
        "sample_size": sample_size,
        "sampled_row_count": sampled_row_count,
        "model_counts": dict(sorted(model_counts.items())),
        "dimension_counts": {
            ("null" if dimension is None else str(dimension)): count
            for dimension, count in sorted(
                dimension_counts.items(),
                key=lambda item: (-1 if item[0] is None else int(item[0]), item[1]),
            )
        },
        "model_dimension_counts": [
            {
                "embedding_model": model,
                "dimension": dimension,
                "count": count,
            }
            for (model, dimension), count in sorted(model_dimension_counts.items())
        ],
        "configured_dimension_mismatch_count": sum(
            count
            for (model, dimension), count in model_dimension_counts.items()
            if dimension not in (None, configured_dimension)
        ),
    }


def _audit_embedding_field_coverage(
    rows: list[dict[str, Any]],
    *,
    scan_mode: str,
    sample_size: int,
) -> dict[str, Any]:
    fields = ("chunk_id", "embedding_model", "chunk_strategy", "text_hash")
    present_counts: Counter[str] = Counter()
    missing_counts: Counter[str] = Counter()
    distinct_values: dict[str, set[str]] = {field: set() for field in fields}

    for row in rows:
        weight_value = row.get("count", 1)
        weight = int(weight_value) if isinstance(weight_value, (int, float)) else 1
        for field in fields:
            value = row.get(field)
            if isinstance(value, str) and value:
                present_counts[field] += weight
                distinct_values[field].add(value)
            else:
                missing_counts[field] += weight

    return {
        "scan_mode": scan_mode,
        "sample_size": sample_size,
        "row_count": sum(
            int(row.get("count", 1)) if isinstance(row.get("count", 1), (int, float)) else 1
            for row in rows
        ),
        "present_counts": {field: present_counts.get(field, 0) for field in fields},
        "missing_counts": {field: missing_counts.get(field, 0) for field in fields},
        "distinct_value_counts": {field: len(distinct_values[field]) for field in fields},
    }


def _build_provenance_fanout_by_chunk_id(
    provenance_keys: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    fanout_by_chunk_id: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for chunk_id, namespace, document_ref in provenance_keys:
        fanout_by_chunk_id[chunk_id].add((namespace, document_ref))
    return [
        {"chunk_id": chunk_id, "count": len(keys)}
        for chunk_id, keys in sorted(fanout_by_chunk_id.items())
        if len(keys) > 1
    ]


def _build_duplicate_provenance_keys(
    provenance_key_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": str(row["chunk_id"]),
            "namespace": str(row["namespace"]),
            "document_ref": str(row["document_ref"]),
            "count": int(row.get("count", 1))
            if isinstance(row.get("count", 1), (int, float))
            else 1,
        }
        for row in provenance_key_rows
        if all(
            isinstance(row.get(field), str) for field in ("chunk_id", "namespace", "document_ref")
        )
        and (int(row.get("count", 1)) if isinstance(row.get("count", 1), (int, float)) else 1) > 1
    ]


def _provenance_keys_from_rows(
    provenance_key_rows: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    return [
        (
            str(row["chunk_id"]),
            str(row["namespace"]),
            str(row["document_ref"]),
        )
        for row in provenance_key_rows
        if all(
            isinstance(row.get(field), str) for field in ("chunk_id", "namespace", "document_ref")
        )
    ]


def _audit_completeness(
    connection: Any,
    settings: SurrealCompletenessAuditSettings,
    *,
    dimension_sample_size: int = 100,
    exact_counts: bool = False,
    exact_coverage: bool = False,
    exact_embedding_coverage: bool = False,
    full_vector_dimension_scan: bool | None = None,
) -> CompletenessAuditReport:
    if dimension_sample_size <= 0:
        raise ValueError("dimension_sample_size must be a positive integer")

    exact_embedding_coverage = exact_embedding_coverage or bool(full_vector_dimension_scan)
    sample_limit = min(20, dimension_sample_size)
    chunk_count = _count_table(connection, _CHUNK_TABLE) if exact_counts else None
    provenance_count = _count_table(connection, _PROVENANCE_TABLE) if exact_counts else None
    embedding_tables = surreal_embedding_shard_tables(settings.embedding_shard_count)
    embedding_counts_by_table: dict[str, int] = {}
    embedding_field_rows: list[dict[str, Any]] = []
    embedding_counts_mode = "exact" if exact_embedding_coverage else "sample"
    table_count = len(embedding_tables)
    base_limit, extra_limit = divmod(dimension_sample_size, table_count) if table_count else (0, 0)
    for table_name in embedding_tables:
        if exact_embedding_coverage:
            rows = _safe_query_rows(
                connection,
                (
                    "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, count() AS count "
                    f"FROM {table_name} GROUP BY chunk_id, embedding_model, chunk_strategy, text_hash "
                    "ORDER BY chunk_id ASC, embedding_model ASC, chunk_strategy ASC, text_hash ASC;"
                ),
            )
            embedding_counts_by_table[table_name] = _count_table(connection, table_name)
        else:
            table_index = len(embedding_counts_by_table)
            limit = base_limit + (1 if table_index < extra_limit else 0)
            rows = _fetch_table_rows_limited(
                connection,
                table_name,
                fields=(
                    "chunk_id, embedding_model, chunk_strategy, text_hash, "
                    "array::len(vector) AS embedding_dimension"
                ),
                limit=limit,
            )
            embedding_counts_by_table[table_name] = len(rows)
        embedding_field_rows.extend(rows)

    vector_rows: list[dict[str, Any]] = []
    vector_rows_by_table: dict[str, int] = {}
    if not embedding_tables:
        pass
    elif exact_embedding_coverage:
        for table_name in embedding_tables:
            rows = _fetch_table_rows(
                connection,
                table_name,
                fields="embedding_model, array::len(vector) AS embedding_dimension",
            )
            vector_rows.extend(rows)
            vector_rows_by_table[table_name] = len(rows)
    else:
        vector_rows = [
            row
            for row in embedding_field_rows
            if "embedding_dimension" in row or "embedding_model" in row
        ]
        vector_rows_by_table = {
            table_name: embedding_counts_by_table.get(table_name, 0)
            for table_name in embedding_tables
        }

    sampled_row_count = len(vector_rows)

    sampled_chunk_rows = _safe_query_rows(
        connection, f"SELECT chunk_id FROM chunks LIMIT {sample_limit};"
    )
    sampled_chunk_ids = [
        str(row["chunk_id"]) for row in sampled_chunk_rows if isinstance(row.get("chunk_id"), str)
    ]

    if exact_coverage:
        missing_provenance_rows = _safe_query_rows(
            connection,
            f"SELECT chunk_id FROM chunks WHERE {_not_in_chunk_ids_clause(_PROVENANCE_TABLE)} LIMIT {sample_limit};",
        )
        missing_provenance_count: int | None = _count_table(
            connection,
            f"chunks WHERE {_not_in_chunk_ids_clause(_PROVENANCE_TABLE)}",
        )
        missing_provenance = [
            str(row["chunk_id"])
            for row in missing_provenance_rows
            if isinstance(row.get("chunk_id"), str)
        ]
        missing_provenance_mode = "exact"
        missing_provenance_sample_size = sample_limit
    else:
        present_provenance_ids: set[str] = set()
        if sampled_chunk_ids:
            chunk_id_literal = _surreal_string_array_literal(sampled_chunk_ids)
            provenance_rows = _safe_query_rows(
                connection,
                f"SELECT chunk_id FROM provenance WHERE chunk_id IN {chunk_id_literal} LIMIT {sample_limit};",
            )
            present_provenance_ids.update(
                str(row["chunk_id"])
                for row in provenance_rows
                if isinstance(row.get("chunk_id"), str)
            )
        missing_provenance = [
            chunk_id for chunk_id in sampled_chunk_ids if chunk_id not in present_provenance_ids
        ]
        missing_provenance_count = None
        missing_provenance_mode = "sample"
        missing_provenance_sample_size = len(sampled_chunk_ids)

    if exact_coverage:
        missing_embeddings_clause = " AND ".join(
            _not_in_chunk_ids_clause(table_name) for table_name in embedding_tables
        )
        missing_embeddings_rows = _safe_query_rows(
            connection,
            f"SELECT chunk_id FROM chunks WHERE {missing_embeddings_clause} LIMIT {sample_limit};",
        )
        missing_embeddings_count: int | None = _count_table(
            connection,
            f"chunks WHERE {missing_embeddings_clause}",
        )
        missing_embeddings = [
            str(row["chunk_id"])
            for row in missing_embeddings_rows
            if isinstance(row.get("chunk_id"), str)
        ]
        missing_embeddings_mode = "exact"
        missing_embeddings_sample_size = sample_limit
    else:
        # Do not query embeddings by chunk_id on the default path. Without a
        # chunk_id-only index that predicate can scan the vector table and
        # timeout even for tiny IN lists. Use exact coverage or targeted
        # record-id checks for embedding completeness.
        missing_embeddings = []
        missing_embeddings_count = None
        missing_embeddings_mode = "not_run"
        missing_embeddings_sample_size = 0

    if exact_coverage:
        orphan_provenance_rows = _safe_query_rows(
            connection,
            f"SELECT chunk_id FROM provenance WHERE {_not_in_chunk_ids_clause(_CHUNK_TABLE)} LIMIT {sample_limit};",
        )
        orphan_provenance_count: int | None = _count_table(
            connection,
            f"provenance WHERE {_not_in_chunk_ids_clause(_CHUNK_TABLE)}",
        )
        orphan_provenance = [
            str(row["chunk_id"])
            for row in orphan_provenance_rows
            if isinstance(row.get("chunk_id"), str)
        ]
        orphan_provenance_mode = "exact"
        orphan_provenance_sample_size = sample_limit
    else:
        sampled_provenance_rows = _safe_query_rows(
            connection, f"SELECT chunk_id FROM provenance LIMIT {sample_limit};"
        )
        sampled_provenance_chunk_ids = [
            str(row["chunk_id"])
            for row in sampled_provenance_rows
            if isinstance(row.get("chunk_id"), str)
        ]
        present_chunk_ids: set[str] = set()
        if sampled_provenance_chunk_ids:
            chunk_id_literal = _surreal_string_array_literal(sampled_provenance_chunk_ids)
            chunk_rows = _safe_query_rows(
                connection,
                f"SELECT chunk_id FROM chunks WHERE chunk_id IN {chunk_id_literal} LIMIT {sample_limit};",
            )
            present_chunk_ids.update(
                str(row["chunk_id"]) for row in chunk_rows if isinstance(row.get("chunk_id"), str)
            )
        orphan_provenance = [
            chunk_id
            for chunk_id in sampled_provenance_chunk_ids
            if chunk_id not in present_chunk_ids
        ]
        orphan_provenance_count = None
        orphan_provenance_mode = "sample"
        orphan_provenance_sample_size = len(sampled_provenance_chunk_ids)

    orphan_embeddings_count: int | None = None
    orphan_embeddings: list[str] = []
    if exact_coverage:
        orphan_embeddings_sample_size = sample_limit
        for table_name in embedding_tables:
            rows = _safe_query_rows(
                connection,
                f"SELECT chunk_id FROM {table_name} WHERE {_not_in_chunk_ids_clause(_CHUNK_TABLE)} LIMIT {sample_limit};",
            )
            orphan_embeddings.extend(
                str(row["chunk_id"]) for row in rows if isinstance(row.get("chunk_id"), str)
            )
            table_orphan_count = _count_table(
                connection, f"{table_name} WHERE {_not_in_chunk_ids_clause(_CHUNK_TABLE)}"
            )
            orphan_embeddings_count = (
                0 if orphan_embeddings_count is None else orphan_embeddings_count
            ) + table_orphan_count
        orphan_embeddings_mode = "exact"
    else:
        sampled_embedding_rows_total = 0
        for table_name in embedding_tables:
            rows = _safe_query_rows(
                connection, f"SELECT chunk_id FROM {table_name} LIMIT {sample_limit};"
            )
            sampled_embedding_rows_total += len(rows)
            sampled_embedding_chunk_ids = [
                str(row["chunk_id"]) for row in rows if isinstance(row.get("chunk_id"), str)
            ]
            if sampled_embedding_chunk_ids:
                chunk_id_literal = _surreal_string_array_literal(sampled_embedding_chunk_ids)
                chunk_rows = _safe_query_rows(
                    connection,
                    f"SELECT chunk_id FROM chunks WHERE chunk_id IN {chunk_id_literal} LIMIT {sample_limit};",
                )
                present_chunk_ids = {
                    str(row["chunk_id"])
                    for row in chunk_rows
                    if isinstance(row.get("chunk_id"), str)
                }
                orphan_embeddings.extend(
                    chunk_id
                    for chunk_id in sampled_embedding_chunk_ids
                    if chunk_id not in present_chunk_ids
                )
        orphan_embeddings = sorted(set(orphan_embeddings))
        orphan_embeddings_count = None
        orphan_embeddings_mode = "sample"
        orphan_embeddings_sample_size = sampled_embedding_rows_total

    if exact_counts:
        provenance_key_rows = _safe_query_rows(
            connection,
            "SELECT chunk_id, namespace, document_ref, count() AS count "
            "FROM provenance GROUP BY chunk_id, namespace, document_ref "
            "ORDER BY chunk_id ASC, namespace ASC, document_ref ASC;",
        )
    else:
        provenance_key_rows = _safe_query_rows(
            connection,
            f"SELECT chunk_id, namespace, document_ref, 1 AS count FROM provenance LIMIT {sample_limit};",
        )
    provenance_keys = _provenance_keys_from_rows(provenance_key_rows)
    duplicate_provenance_keys = _build_duplicate_provenance_keys(provenance_key_rows)
    provenance_fanout_by_chunk_id = _build_provenance_fanout_by_chunk_id(provenance_keys)

    counts = {
        "chunks": chunk_count,
        "chunks_mode": "exact" if exact_counts else "not_run",
        "provenance": provenance_count,
        "provenance_mode": "exact" if exact_counts else "not_run",
        "embeddings": sum(embedding_counts_by_table.values()),
        "embedding_rows_by_table": embedding_counts_by_table,
        "embedding_vector_sample_rows_by_table": vector_rows_by_table,
        "embeddings_mode": embedding_counts_mode,
        "embeddings_sample_size": dimension_sample_size,
    }
    duplicate_provenance_key_count = len(duplicate_provenance_keys)
    provenance_fanout_count = len(provenance_fanout_by_chunk_id)
    coverage = {
        "chunks_without_provenance_count": missing_provenance_count,
        "chunks_without_provenance_sample": missing_provenance,
        "chunks_without_provenance_count_mode": missing_provenance_mode,
        "chunks_without_provenance_sample_size": missing_provenance_sample_size,
        "chunks_without_embeddings_count": missing_embeddings_count,
        "chunks_without_embeddings_sample": missing_embeddings,
        "chunks_without_embeddings_count_mode": missing_embeddings_mode,
        "chunks_without_embeddings_sample_size": missing_embeddings_sample_size,
        "orphan_provenance_count": orphan_provenance_count,
        "orphan_provenance_sample": orphan_provenance,
        "orphan_provenance_count_mode": orphan_provenance_mode,
        "orphan_provenance_sample_size": orphan_provenance_sample_size,
        "orphan_embeddings_count": orphan_embeddings_count,
        "orphan_embeddings_sample": orphan_embeddings,
        "orphan_embeddings_count_mode": orphan_embeddings_mode,
        "orphan_embeddings_sample_size": orphan_embeddings_sample_size,
        "duplicate_provenance_key_count": duplicate_provenance_key_count,
        "duplicate_provenance_key_sample": duplicate_provenance_keys[:sample_limit],
        "provenance_fanout_count": provenance_fanout_count,
        "provenance_fanout_sample": provenance_fanout_by_chunk_id[:sample_limit],
        "embedding_fields": _audit_embedding_field_coverage(
            embedding_field_rows,
            scan_mode=embedding_counts_mode,
            sample_size=dimension_sample_size,
        ),
    }

    index_audits = {
        _CHUNK_TABLE: _audit_index_table(
            connection,
            table_name=_CHUNK_TABLE,
            expected_index_names=_expected_chunk_index_names(),
            expected_index_statements=_expected_chunk_index_statements(),
        ),
        "embeddings": _audit_index_table(
            connection,
            table_name="embeddings",
            expected_index_names=(
                *_expected_embedding_schema_index_names(),
                _expected_embedding_hnsw_index_statement(
                    table_name="embeddings",
                    shard_index=None,
                    settings=settings,
                )[0],
            ),
            expected_index_statements=(
                *_expected_embedding_schema_index_statements(),
                _expected_embedding_hnsw_index_statement(
                    table_name="embeddings",
                    shard_index=None,
                    settings=settings,
                )[1],
            ),
        ),
    }
    if settings.embedding_shard_count > 1:
        for shard_index, table_name in enumerate(embedding_tables):
            hnsw_name, hnsw_statement = _expected_embedding_hnsw_index_statement(
                table_name=table_name,
                shard_index=shard_index,
                settings=settings,
            )
            index_audits[table_name] = _audit_index_table(
                connection,
                table_name=table_name,
                expected_index_names=(hnsw_name,),
                expected_index_statements=(hnsw_statement,),
            )

    graph_table_counts: dict[str, Any] = (
        {table_name: _count_table(connection, table_name) for table_name in _GRAPH_TABLES}
        if exact_counts
        else dict.fromkeys(_GRAPH_TABLES)
    )

    return CompletenessAuditReport(
        generated_at=_utc_now(),
        status=(
            "ok"
            if not any(
                [
                    duplicate_provenance_keys,
                    missing_provenance,
                    missing_embeddings,
                    orphan_provenance,
                    orphan_embeddings,
                    any(
                        audit.missing_index_names or audit.definition_mismatches
                        for audit in index_audits.values()
                    ),
                ]
            )
            else "needs_attention"
        ),
        settings=_report_settings_from_settings(settings),
        counts=counts,
        coverage=coverage,
        provenance_fanout_by_chunk_id=provenance_fanout_by_chunk_id,
        duplicate_provenance_keys=duplicate_provenance_keys,
        embedding_distribution=_audit_embedding_distribution(
            vector_rows,
            configured_dimension=settings.embedding_dimension,
            full_vector_dimension_scan=exact_embedding_coverage,
            sample_size=dimension_sample_size,
            sampled_row_count=sampled_row_count,
        ),
        index_audits=index_audits,
        graph_table_counts=graph_table_counts,
    )


def _human_summary(report: CompletenessAuditReport) -> str:
    index_missing = sum(len(audit.missing_index_names) for audit in report.index_audits.values())
    index_mismatches = sum(
        len(audit.definition_mismatches) for audit in report.index_audits.values()
    )
    scan_mode = str(report.embedding_distribution["scan_mode"])
    if scan_mode == "exact":
        vector_scan = f"exact({report.embedding_distribution['sampled_row_count']})"
    else:
        vector_scan = (
            f"sample({report.embedding_distribution['sampled_row_count']}/"
            f"{report.embedding_distribution['sample_size']})"
        )
    embeddings_mode = str(report.counts.get("embeddings_mode", "exact"))
    if embeddings_mode == "exact":
        embeddings_count = f"exact({report.counts['embeddings']})"
    else:
        embeddings_count = f"sample({report.counts['embeddings']}/{report.counts.get('embeddings_sample_size', 0)})"

    def _format_gap(name: str) -> str:
        mode = str(report.coverage.get(f"{name}_count_mode", "exact"))
        count = report.coverage.get(f"{name}_count")
        if mode == "exact":
            return f"exact({count})"
        if mode == "not_run":
            return "not_run"
        sample_size = int(report.coverage.get(f"{name}_sample_size", 0) or 0)
        sample_count = len(report.coverage.get(f"{name}_sample", []))
        return f"sample({sample_count}/{sample_size})/unknown"

    def _format_optional_count(name: str) -> str:
        mode = str(report.counts.get(f"{name}_mode", "exact"))
        value = report.counts.get(name)
        return f"{value}" if mode == "exact" else mode

    graph_relations = report.graph_table_counts.get("relations")
    graph_relations_text = str(graph_relations) if isinstance(graph_relations, int) else "not_run"

    return (
        f"status={report.status} "
        f"chunks={_format_optional_count('chunks')} "
        f"provenance={_format_optional_count('provenance')} "
        f"embeddings={embeddings_count} "
        f"vector_dims={vector_scan} "
        f"missing_provenance={_format_gap('chunks_without_provenance')} "
        f"missing_embeddings={_format_gap('chunks_without_embeddings')} "
        f"provenance_fanout_chunks={len(report.provenance_fanout_by_chunk_id)} "
        f"duplicate_provenance_keys={len(report.duplicate_provenance_keys)} "
        f"index_missing={index_missing} "
        f"index_mismatches={index_mismatches} "
        f"graph_relations={graph_relations_text}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path to write the audit JSON report.",
    )
    parser.add_argument(
        "--dimension-sample-size",
        type=int,
        default=100,
        help="Bounded sample size for vector dimension distribution when not using a full scan.",
    )
    parser.add_argument(
        "--exact-counts",
        action="store_true",
        help="Run exact table counts and full provenance duplicate grouping.",
    )
    parser.add_argument(
        "--exact-coverage",
        action="store_true",
        help="Run the heavy exact cross-table coverage audit, including anti-join counts.",
    )
    parser.add_argument(
        "--exact-embedding-coverage",
        action="store_true",
        help="Run the heavy exact embedding coverage audit, including full-table embedding scans.",
    )
    parser.add_argument(
        "--full-vector-dimension-scan",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = read_settings_from_env()
    with build_connection(settings) as connection:
        report = _audit_completeness(
            connection,
            settings,
            dimension_sample_size=args.dimension_sample_size,
            exact_counts=args.exact_counts,
            exact_coverage=args.exact_coverage,
            exact_embedding_coverage=args.exact_embedding_coverage
            or args.full_vector_dimension_scan,
        )
    report_json = asdict(report)
    if args.json_output is not None:
        _write_json(args.json_output, report_json)
    print(
        json.dumps(report_json, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
    )
    print(_human_summary(report), file=sys.stderr)
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
