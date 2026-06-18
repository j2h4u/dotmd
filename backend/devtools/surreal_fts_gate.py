"""Timed SurrealDB full-text gate for the standalone migration."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
    from dotmd.storage.surreal_schema import (
        build_analyzer_statement,
        build_fulltext_index_statement,
    )
except ModuleNotFoundError:  # pragma: no cover - import-time path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
    from dotmd.storage.surreal_schema import (
        build_analyzer_statement,
        build_fulltext_index_statement,
    )


class SurrealFtsConnection(Protocol):
    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any: ...

    def close(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class FtsGateConfig:
    analyzer_name: str = "dotmd_fts"
    title_index_name: str = "chunks_title_fts"
    text_index_name: str = "chunks_text_fts"
    apply_mode: str = "concurrent"
    limit: int = 5
    db_timeout_seconds: int = 30
    build_timeout_seconds: int = 600
    poll_interval_seconds: float = 60.0
    max_seconds: float = 5.0
    explain: bool = True
    probe_term: str | None = None


@dataclass(frozen=True, slots=True)
class FtsGateResult:
    sample_seconds: float
    analyzer_seconds: float
    title_seconds: float
    text_seconds: float
    title_rows: int
    text_rows: int
    passed: bool


def _default_connection_factory(config: SurrealStoreConfig) -> SurrealFtsConnection:
    return SurrealConnection(config)


def _close_quietly(connection: SurrealFtsConnection) -> None:
    try:
        connection.close()
    except NotImplementedError:
        return


def _emit(printer: Callable[..., None], message: str) -> None:
    printer(message, flush=True)


def _validate_identifier(name: str, *, label: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"invalid {label}: {name}")


def _first_term(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return "dotmd"
    for raw in cleaned.split():
        term = raw.strip(".,;:!?()[]{}<>\"'`")
        if term:
            return term
    return cleaned


def _result_row_count(result: Any) -> int:
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict) and isinstance(result.get("total_rows"), int):
        return result["total_rows"]
    return 0


def _collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        collected: list[str] = []
        for nested in value.values():
            collected.extend(_collect_strings(nested))
        return collected
    if isinstance(value, list):
        collected: list[str] = []
        for nested in value:
            collected.extend(_collect_strings(nested))
        return collected
    return []


def _plan_mentions_index(result: Any, index_name: str) -> bool:
    return index_name in set(_collect_strings(result))


def _extract_building(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        building = result.get("building")
        if isinstance(building, dict):
            return building
        if {"status", "initial", "pending", "updated"} & result.keys():
            return result
    if isinstance(result, list):
        for item in result:
            building = _extract_building(item)
            if building is not None:
                return building
    return None


def _format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "unknown"
    rounded = round(seconds)
    if rounded < 60:
        return f"{rounded}s"
    minutes, remainder = divmod(rounded, 60)
    if minutes < 60:
        return f"{minutes}m {remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _estimate_eta(
    previous: tuple[float, int | None] | None,
    current_elapsed: float,
    current_pending: int | None,
) -> str:
    if previous is None or current_pending is None:
        return "unknown"
    previous_elapsed, previous_pending = previous
    if previous_pending is None or previous_pending <= current_pending:
        return "unknown"
    elapsed_delta = current_elapsed - previous_elapsed
    pending_delta = previous_pending - current_pending
    if elapsed_delta <= 0 or pending_delta <= 0:
        return "unknown"
    rate = pending_delta / elapsed_delta
    if rate <= 0:
        return "unknown"
    return _format_eta(current_pending / rate)


def _fts_query_statement(
    *,
    field: str,
    limit: int,
    timeout_seconds: int,
    explain: bool,
) -> str:
    statement = (
        f"SELECT id, {field}, search::score(0) AS score FROM chunks "
        f"WHERE {field} @0@ $query ORDER BY score DESC LIMIT {limit} "
        f"TIMEOUT {timeout_seconds}s"
    )
    if explain:
        statement += " EXPLAIN FULL"
    return statement + ";"


def _fts_statements_for_config(gate_config: FtsGateConfig) -> tuple[str, ...]:
    concurrently = gate_config.apply_mode != "blocking"
    return (
        build_analyzer_statement(gate_config.analyzer_name),
        build_fulltext_index_statement(
            index_name=gate_config.title_index_name,
            table="chunks",
            field="title",
            analyzer_name=gate_config.analyzer_name,
            concurrently=concurrently,
        ),
        build_fulltext_index_statement(
            index_name=gate_config.text_index_name,
            table="chunks",
            field="text",
            analyzer_name=gate_config.analyzer_name,
            concurrently=concurrently,
        ),
    )


def _poll_fulltext_indexes(
    connection: SurrealFtsConnection,
    *,
    table: str,
    index_names: tuple[str, ...],
    timeout_seconds: int,
    poll_interval_seconds: float,
    printer: Callable[..., None],
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> None:
    started = clock()
    remaining = set(index_names)
    last_samples: dict[str, tuple[float, int | None]] = {}
    while remaining:
        for index_name in index_names:
            if index_name not in remaining:
                continue
            try:
                info = connection.query(f"INFO FOR INDEX {index_name} ON {table};")
            except Exception as exc:  # pragma: no cover - live DB dependent
                elapsed = clock() - started
                _emit(
                    printer,
                    (
                        "surreal fts gate: index="
                        f"{index_name} info unavailable elapsed={elapsed:.3f}s "
                        f"error={type(exc).__name__}: {exc}"
                    ),
                )
                if elapsed >= timeout_seconds:
                    raise TimeoutError(
                        f"timed out waiting for full-text index {index_name} on {table}"
                    ) from exc
                continue

            building = _extract_building(info)
            elapsed = clock() - started
            if building is None or building.get("status") == "ready":
                _emit(
                    printer,
                    (
                        "surreal fts gate: index="
                        f"{index_name} status=ready elapsed={elapsed:.3f}s"
                    ),
                )
                remaining.remove(index_name)
                continue

            pending = building.get("pending")
            initial = building.get("initial")
            updated = building.get("updated")
            eta = _estimate_eta(last_samples.get(index_name), elapsed, pending if isinstance(pending, int) else None)
            _emit(
                printer,
                (
                    "surreal fts gate: index="
                    f"{index_name} status={building.get('status', 'indexing')} "
                    f"initial={initial} pending={pending} updated={updated} "
                    f"elapsed={elapsed:.3f}s eta={eta}"
                ),
            )
            if isinstance(pending, int):
                last_samples[index_name] = (elapsed, pending)
        if not remaining:
            return
        elapsed = clock() - started
        if elapsed >= timeout_seconds:
            raise TimeoutError(
                f"timed out waiting for full-text indexes: {', '.join(sorted(remaining))}"
            )
        _emit(
            printer,
            (
                "surreal fts gate: waiting "
                f"elapsed={elapsed:.3f}s remaining={len(remaining)} "
                f"next_poll_in={poll_interval_seconds:.1f}s"
            ),
        )
        sleeper(poll_interval_seconds)


def run_gate(
    store_config: SurrealStoreConfig,
    gate_config: FtsGateConfig,
    *,
    connection_factory: Callable[[SurrealStoreConfig], SurrealFtsConnection] = _default_connection_factory,
    printer: Callable[..., None] = print,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> FtsGateResult:
    _validate_identifier(gate_config.analyzer_name, label="analyzer name")
    _validate_identifier(gate_config.title_index_name, label="title index name")
    _validate_identifier(gate_config.text_index_name, label="text index name")
    _emit(
        printer,
        (
            "surreal fts gate: connecting "
            f"url={store_config.url} namespace={store_config.namespace} "
            f"database={store_config.database}"
        ),
    )
    _emit(
        printer,
        (
            "surreal fts gate: config "
            f"analyzer={gate_config.analyzer_name} "
            f"title_index={gate_config.title_index_name} "
            f"text_index={gate_config.text_index_name} "
            f"apply_mode={gate_config.apply_mode} "
            f"limit={gate_config.limit} "
            f"db_timeout={gate_config.db_timeout_seconds}s "
            f"build_timeout={gate_config.build_timeout_seconds}s "
            f"poll_interval={gate_config.poll_interval_seconds:.1f}s "
            f"max_seconds={gate_config.max_seconds:.3f} "
            f"explain={gate_config.explain} "
            f"probe_term={gate_config.probe_term or 'auto'}"
        ),
    )
    if gate_config.apply_mode == "blocking":
        _emit(
            printer,
            (
                "surreal fts gate: warning blocking FTS build mode is explicit "
                "and may block on DEFINE INDEX"
            ),
        )
    connection = connection_factory(store_config)
    try:
        statements = _fts_statements_for_config(gate_config)
        _emit(
            printer,
            f"surreal fts gate: applying {len(statements)} schema statements",
        )
        for index, statement in enumerate(statements, start=1):
            step_started = clock()
            _emit(printer, f"[{index}/{len(statements)}] applying: {statement}")
            connection.query(statement)
            elapsed = clock() - step_started
            _emit(printer, f"[{index}/{len(statements)}] done in {elapsed:.3f}s")

        _poll_fulltext_indexes(
            connection,
            table="chunks",
            index_names=(gate_config.title_index_name, gate_config.text_index_name),
            timeout_seconds=gate_config.build_timeout_seconds,
            poll_interval_seconds=gate_config.poll_interval_seconds,
            printer=printer,
            clock=clock,
            sleeper=sleeper,
        )

        sample_started = clock()
        rows = connection.query("SELECT id, title, text FROM chunks LIMIT 1;")
        sample_seconds = clock() - sample_started
        _emit(
            printer,
            f"surreal fts gate: sample rows={len(rows)} elapsed={sample_seconds:.3f}s",
        )
        if not rows:
            raise RuntimeError("chunks table is empty")

        sample = rows[0]
        title_value = sample.get("title") if isinstance(sample, dict) else None
        text_value = sample.get("text") if isinstance(sample, dict) else None
        if not isinstance(title_value, str) or not title_value.strip():
            title_value = text_value if isinstance(text_value, str) and text_value.strip() else None
        if not isinstance(text_value, str) or not text_value.strip():
            text_value = title_value if isinstance(title_value, str) and title_value.strip() else None
        if not isinstance(title_value, str) and not isinstance(text_value, str):
            raise RuntimeError("sample chunk did not contain searchable title or text")

        title_probe = gate_config.probe_term or _first_term(title_value or text_value or "dotmd")
        text_probe = gate_config.probe_term or _first_term(text_value or title_value or "dotmd")
        _emit(
            printer,
            f"surreal fts gate: probes title={title_probe!r} text={text_probe!r}",
        )

        analyzer_started = clock()
        analyzer_result = connection.query(
            "RETURN search::analyze($analyzer, $probe);",
            {"analyzer": gate_config.analyzer_name, "probe": title_probe},
        )
        analyzer_seconds = clock() - analyzer_started
        _emit(
            printer,
            "surreal fts gate: analyzer "
            + json.dumps(analyzer_result, ensure_ascii=False, default=str),
        )
        _emit(
            printer,
            f"surreal fts gate: analyzer elapsed={analyzer_seconds:.3f}s",
        )

        title_started = clock()
        title_result = connection.query(
            _fts_query_statement(
                field="title",
                limit=gate_config.limit,
                timeout_seconds=gate_config.db_timeout_seconds,
                explain=gate_config.explain,
            ),
            {"query": title_probe},
        )
        title_seconds = clock() - title_started
        title_rows = _result_row_count(title_result)
        title_index_ok = (
            not gate_config.explain
            or _plan_mentions_index(title_result, gate_config.title_index_name)
        )
        if gate_config.explain:
            _emit(
                printer,
                "surreal fts gate: explain title "
                + json.dumps(title_result, ensure_ascii=False, default=str),
            )
        _emit(
            printer,
            (
                "surreal fts gate: title "
                f"rows={title_rows} elapsed={title_seconds:.3f}s "
                f"index={'ok' if title_index_ok else 'missing'}"
            ),
        )

        text_started = clock()
        text_result = connection.query(
            _fts_query_statement(
                field="text",
                limit=gate_config.limit,
                timeout_seconds=gate_config.db_timeout_seconds,
                explain=gate_config.explain,
            ),
            {"query": text_probe},
        )
        text_seconds = clock() - text_started
        text_rows = _result_row_count(text_result)
        text_index_ok = (
            not gate_config.explain or _plan_mentions_index(text_result, gate_config.text_index_name)
        )
        if gate_config.explain:
            _emit(
                printer,
                "surreal fts gate: explain text "
                + json.dumps(text_result, ensure_ascii=False, default=str),
            )
        _emit(
            printer,
            (
                "surreal fts gate: text "
                f"rows={text_rows} elapsed={text_seconds:.3f}s "
                f"index={'ok' if text_index_ok else 'missing'}"
            ),
        )

        passed = (
            sample_seconds <= gate_config.max_seconds
            and analyzer_seconds <= gate_config.max_seconds
            and title_seconds <= gate_config.max_seconds
            and text_seconds <= gate_config.max_seconds
            and title_rows > 0
            and text_rows > 0
            and title_index_ok
            and text_index_ok
        )
        _emit(
            printer,
            f"surreal fts gate: status={'pass' if passed else 'fail'}",
        )
        return FtsGateResult(
            sample_seconds=sample_seconds,
            analyzer_seconds=analyzer_seconds,
            title_seconds=title_seconds,
            text_seconds=text_seconds,
            title_rows=title_rows,
            text_rows=text_rows,
            passed=passed,
        )
    finally:
        _close_quietly(connection)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-term")
    parser.add_argument("--apply-mode", choices=("concurrent", "blocking"), default="concurrent")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--db-timeout-seconds", type=int, default=30)
    parser.add_argument("--build-timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-interval-seconds", type=float, default=60.0)
    parser.add_argument("--max-seconds", type=float, default=5.0)
    parser.add_argument("--analyzer-name", default="dotmd_fts")
    parser.add_argument("--title-index-name", default="chunks_title_fts")
    parser.add_argument("--text-index-name", default="chunks_text_fts")
    parser.add_argument("--explain", dest="explain", action="store_true")
    parser.add_argument("--no-explain", dest="explain", action="store_false")
    parser.set_defaults(explain=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_gate(
        SurrealStoreConfig.from_env(),
        FtsGateConfig(
            analyzer_name=args.analyzer_name,
            title_index_name=args.title_index_name,
            text_index_name=args.text_index_name,
            apply_mode=args.apply_mode,
            limit=args.limit,
            db_timeout_seconds=args.db_timeout_seconds,
            build_timeout_seconds=args.build_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            max_seconds=args.max_seconds,
            explain=args.explain,
            probe_term=args.probe_term,
        ),
    )
    return 0 if result.passed else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
