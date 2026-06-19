from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import devtools.surreal_source_export_runner as runner
import pytest


class _FakeQueryResult:
    def __init__(self, rows: list[object]) -> None:
        self.result_set = rows


def _node_row(
    node_id: str,
    *,
    internal_id: str | None = None,
    **properties: object,
) -> tuple[SimpleNamespace]:
    return (
        SimpleNamespace(
            id=internal_id or node_id,
            properties={"id": node_id, **properties},
        ),
    )


def _relation_row(
    source_id: str,
    target_id: str,
    relation_type: str,
    weight: float,
    **properties: object,
) -> tuple[object, object, object, object, SimpleNamespace]:
    return (
        source_id,
        target_id,
        relation_type,
        weight,
        SimpleNamespace(properties={"rel_type": relation_type, "weight": weight, **properties}),
    )


class _FakeGraph:
    def __init__(
        self,
        *,
        counts: dict[str, int],
        rows: dict[str, list[object]],
    ) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.counts = counts
        self.rows = rows

    def _paged_rows(self, category: str, params: dict[str, object] | None) -> list[object]:
        skip = int((params or {}).get("skip", 0) or 0)
        limit = int((params or {}).get("limit", 0) or 0)
        return self.rows[category][skip : skip + limit]

    def ro_query(self, statement: str, params: dict[str, object] | None = None) -> _FakeQueryResult:
        self.calls.append((statement, params))
        if statement == "MATCH (n:File) RETURN count(n)":
            return _FakeQueryResult([(self.counts["File"],)])
        if statement == "MATCH (n:File) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit":
            return _FakeQueryResult(self._paged_rows("File", params))
        if statement == "MATCH (n:Section) RETURN count(n)":
            return _FakeQueryResult([(self.counts["Section"],)])
        if statement == "MATCH (n:Section) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit":
            return _FakeQueryResult(self._paged_rows("Section", params))
        if statement == "MATCH (n:Tag) RETURN count(n)":
            return _FakeQueryResult([(self.counts["Tag"],)])
        if statement == "MATCH (n:Tag) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit":
            return _FakeQueryResult(self._paged_rows("Tag", params))
        if statement == "MATCH (n:Entity) RETURN count(n)":
            return _FakeQueryResult([(self.counts["Entity"],)])
        if statement == "MATCH (n:Entity) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit":
            return _FakeQueryResult(self._paged_rows("Entity", params))
        if statement == "MATCH (s:Section)-[:REL]->(e:Entity) WHERE e.source = 'ner' RETURN count(*)":
            return _FakeQueryResult([(self.counts["Section NER links"],)])
        if statement == (
            "MATCH (s:Section)-[:REL]->(e:Entity) "
            "WHERE e.source = 'ner' "
            "RETURN s.id, e.id ORDER BY s.id, e.id SKIP $skip LIMIT $limit"
        ):
            return _FakeQueryResult(self._paged_rows("Section NER links", params))
        if statement == "MATCH (a)-[r]->(b) RETURN count(r)":
            return _FakeQueryResult([(self.counts["relations"],)])
        if statement == (
            "MATCH (a)-[r]->(b) "
            "RETURN a.id, b.id, r.rel_type, r.weight, r "
            "SKIP $skip LIMIT $limit"
        ):
            return _FakeQueryResult(self._paged_rows("relations", params))
        raise AssertionError(f"unexpected query: {statement!r}")


class _FakeGraphStore:
    last_instance: ClassVar[_FakeGraphStore | None] = None
    counts: ClassVar[dict[str, int]] = {}
    rows: ClassVar[dict[str, list[object]]] = {}

    def __init__(self, url: str, graph_name: str) -> None:
        self.url = url
        self.graph_name = graph_name
        self._graph = _FakeGraph(counts=self.counts, rows=self.rows)
        _FakeGraphStore.last_instance = self

    def get_graph_data(self) -> dict[str, object]:
        raise AssertionError("run_export_command should not call get_graph_data()")


class _FakeFeedbackStore:
    init_paths: ClassVar[list[Path]] = []

    def __init__(self, db_path: Path) -> None:
        self.init_paths.append(db_path)

    def list_all(self, limit: int = 50, include_closed: bool = False) -> list[dict[str, object]]:
        assert include_closed is True
        assert limit == 1_000_000
        return [
            {
                "id": 2,
                "submitted_at": 20,
                "message": "Newest",
                "severity": "bug",
                "status": "open",
                "context": "ctx",
                "model": "gpt-5",
                "harness": "cli",
                "status_comment": "note",
                "extra": {"a": 1},
            },
            {
                "id": 1,
                "submitted_at": 10,
                "message": "Older",
                "severity": None,
                "status": "done",
            },
        ]


def test_build_parser_accepts_explicit_feedback_db_or_index_dir() -> None:
    parser = runner.build_parser()

    args = parser.parse_args(
        [
            "--graph-output",
            "graph.json",
            "--feedback-output",
            "feedback.json",
            "--falkordb-url",
            "redis://example:6379",
            "--feedback-db",
            "feedback.sqlite",
        ]
    )

    assert args.graph_output == Path("graph.json")
    assert args.feedback_output == Path("feedback.json")
    assert args.feedback_db == Path("feedback.sqlite")
    assert args.index_dir is None


def test_main_requires_feedback_source() -> None:
    with pytest.raises(SystemExit, match="--index-dir or --feedback-db is required"):
        runner.main(
            [
                "--graph-output",
                "graph.json",
                "--feedback-output",
                "feedback.json",
                "--falkordb-url",
                "redis://example:6379",
            ]
        )


def test_run_export_command_writes_paged_graph_and_feedback_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_output = tmp_path / "graph-export.json"
    feedback_output = tmp_path / "feedback-export.json"

    progress_messages: list[str] = []
    _FakeGraphStore.counts = {
        "File": 3,
        "Section": 3,
        "Tag": 3,
        "Entity": 3,
        "Section NER links": 3,
        "relations": 3,
    }
    _FakeGraphStore.rows = {
        "File": [
            _node_row("file-a", title="Alpha", note="keep-a"),
            _node_row("file-b", title="Beta", note="keep-b"),
            _node_row("file-c", title="Gamma", note="keep-c"),
        ],
        "Section": [
            _node_row(
                "section-a",
                file_path="file-a",
                heading="Heading A",
                level=1,
                text_preview="Preview A",
            ),
            _node_row(
                "section-b",
                file_path="file-b",
                heading="Heading B",
                level=2,
                text_preview="Preview B",
            ),
            _node_row(
                "section-c",
                file_path="file-c",
                heading="Heading C",
                level=3,
                text_preview="Preview C",
            ),
        ],
        "Tag": [
            _node_row("tag-a", color="red"),
            _node_row("tag-b", color="blue"),
            _node_row("tag-c", color="green"),
        ],
        "Entity": [
            _node_row("entity-a", source="section-a", type="PERSON", z=1),
            _node_row("entity-b", source="section-b", type="ORG", z=2),
            _node_row("entity-c", source="section-c", type="LOC", z=3),
        ],
        "Section NER links": [
            ("section-a", "entity-a"),
            ("section-b", "entity-b"),
            ("section-c", "entity-c"),
        ],
        "relations": [
            _relation_row("section-a", "entity-a", "MENTIONS", 0.5, evidence="quoted-a"),
            _relation_row("section-b", "entity-b", "MENTIONS", 0.75, evidence="quoted-b"),
            _relation_row("section-c", "entity-c", "MENTIONS", 1.0, evidence="quoted-c"),
        ],
    }
    monkeypatch.setattr(runner, "FalkorDBGraphStore", _FakeGraphStore)
    monkeypatch.setattr(runner, "FeedbackStore", _FakeFeedbackStore)
    monkeypatch.setattr(runner, "_progress", progress_messages.append)
    monkeypatch.setattr(runner, "GRAPH_EXPORT_PAGE_SIZE", 2)

    result = runner.run_export_command(
        runner.SurrealSourceExportRunnerConfig(
            graph_output=graph_output,
            feedback_output=feedback_output,
            falkordb_url="redis://example:6379",
            graph_name="dotmd",
            index_dir=tmp_path,
            progress_interval_seconds=9999.0,
        )
    )

    graph_payload = json.loads(graph_output.read_text(encoding="utf-8"))
    feedback_payload = json.loads(feedback_output.read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert result.graph_output == graph_output
    assert result.feedback_output == feedback_output
    assert graph_payload["rows"]["files"] == [
        {
            "id": "file-a",
            "original_id": "file-a",
            "file_path": "file-a",
            "path": "file-a",
            "title": "Alpha",
            "metadata": {"note": "keep-a"},
        },
        {
            "id": "file-b",
            "original_id": "file-b",
            "file_path": "file-b",
            "path": "file-b",
            "title": "Beta",
            "metadata": {"note": "keep-b"},
        },
        {
            "id": "file-c",
            "original_id": "file-c",
            "file_path": "file-c",
            "path": "file-c",
            "title": "Gamma",
            "metadata": {"note": "keep-c"},
        },
    ]
    assert graph_payload["rows"]["sections"] == [
        {
            "id": "section-a",
            "original_id": "section-a",
            "chunk_id": "section-a",
            "heading": "Heading A",
            "level": 1,
            "file_path": "file-a",
            "text_preview": "Preview A",
            "metadata": {"ner_entities": ["entity-a"]},
        },
        {
            "id": "section-b",
            "original_id": "section-b",
            "chunk_id": "section-b",
            "heading": "Heading B",
            "level": 2,
            "file_path": "file-b",
            "text_preview": "Preview B",
            "metadata": {"ner_entities": ["entity-b"]},
        },
        {
            "id": "section-c",
            "original_id": "section-c",
            "chunk_id": "section-c",
            "heading": "Heading C",
            "level": 3,
            "file_path": "file-c",
            "text_preview": "Preview C",
            "metadata": {"ner_entities": ["entity-c"]},
        },
    ]
    assert graph_payload["rows"]["entities"] == [
        {
            "id": "entity-a",
            "original_id": "entity-a",
            "name": "entity-a",
            "entity_type": "PERSON",
            "source": "section-a",
            "metadata": {"z": 1},
        },
        {
            "id": "entity-b",
            "original_id": "entity-b",
            "name": "entity-b",
            "entity_type": "ORG",
            "source": "section-b",
            "metadata": {"z": 2},
        },
        {
            "id": "entity-c",
            "original_id": "entity-c",
            "name": "entity-c",
            "entity_type": "LOC",
            "source": "section-c",
            "metadata": {"z": 3},
        },
    ]
    assert graph_payload["rows"]["tags"] == [
        {
            "id": "tag-a",
            "original_id": "tag-a",
            "name": "tag-a",
            "metadata": {"color": "red"},
        },
        {
            "id": "tag-b",
            "original_id": "tag-b",
            "name": "tag-b",
            "metadata": {"color": "blue"},
        },
        {
            "id": "tag-c",
            "original_id": "tag-c",
            "name": "tag-c",
            "metadata": {"color": "green"},
        },
    ]
    assert graph_payload["rows"]["relations"] == [
        {
            "relation_id": graph_payload["rows"]["relations"][0]["relation_id"],
            "source_id": "section-a",
            "target_id": "entity-a",
            "relation_type": "MENTIONS",
            "weight": 0.5,
            "properties": {"evidence": "quoted-a"},
        },
        {
            "relation_id": graph_payload["rows"]["relations"][1]["relation_id"],
            "source_id": "section-b",
            "target_id": "entity-b",
            "relation_type": "MENTIONS",
            "weight": 0.75,
            "properties": {"evidence": "quoted-b"},
        },
        {
            "relation_id": graph_payload["rows"]["relations"][2]["relation_id"],
            "source_id": "section-c",
            "target_id": "entity-c",
            "relation_type": "MENTIONS",
            "weight": 1.0,
            "properties": {"evidence": "quoted-c"},
        },
    ]
    assert graph_payload["inventory"]["node_counts"] == {
        "Entity": 3,
        "File": 3,
        "Section": 3,
        "Tag": 3,
    }
    assert graph_payload["inventory"]["edge_count"] == 3
    assert progress_messages[:20] == [
        "graph export: reading File nodes",
        "graph export: planned File nodes (3 rows)",
        "graph export: File nodes page 1 applied 2/3",
        "graph export: File nodes page 2 applied 3/3",
        "graph export: completed reading File nodes (3/3 rows)",
        "graph export: reading Section nodes",
        "graph export: planned Section nodes (3 rows)",
        "graph export: Section nodes page 1 applied 2/3",
        "graph export: Section nodes page 2 applied 3/3",
        "graph export: completed reading Section nodes (3/3 rows)",
        "graph export: reading Tag nodes",
        "graph export: planned Tag nodes (3 rows)",
        "graph export: Tag nodes page 1 applied 2/3",
        "graph export: Tag nodes page 2 applied 3/3",
        "graph export: completed reading Tag nodes (3/3 rows)",
        "graph export: reading Entity nodes",
        "graph export: planned Entity nodes (3 rows)",
        "graph export: Entity nodes page 1 applied 2/3",
        "graph export: Entity nodes page 2 applied 3/3",
        "graph export: completed reading Entity nodes (3/3 rows)",
    ]
    assert "graph export: planned Section NER links (3 rows)" in progress_messages
    assert "graph export: Section NER links page 1 applied 2/3" in progress_messages
    assert "graph export: Section NER links page 2 applied 3/3" in progress_messages
    assert "graph export: completed reading Section NER links (3/3 rows)" in progress_messages
    assert "graph export: planned relations (3 rows)" in progress_messages
    assert "graph export: relations page 1 applied 2/3" in progress_messages
    assert "graph export: relations page 2 applied 3/3" in progress_messages
    assert "graph export: completed reading relations (3/3 rows)" in progress_messages
    assert "graph export: transforming files (3 rows)" in progress_messages
    assert "graph export: transforming sections (3 rows)" in progress_messages
    assert "graph export: transforming tags (3 rows)" in progress_messages
    assert "graph export: transforming entities (3 rows)" in progress_messages
    assert "graph export: transforming relations (3 rows)" in progress_messages
    assert "feedback export: transforming 2 rows" in progress_messages
    assert "feedback export: completed 2 rows" in progress_messages
    assert "export complete: graph_rows=15 feedback_rows=2" in progress_messages
    assert f"wrote graph export to {graph_output}" in progress_messages
    assert f"wrote feedback export to {feedback_output}" in progress_messages
    assert feedback_payload["truncated"] is False
    assert feedback_payload["rows"] == [
        {
            "id": 2,
            "submitted_at": 20,
            "message": "Newest",
            "severity": "bug",
            "status": "open",
            "context": "ctx",
            "model": "gpt-5",
            "harness": "cli",
            "status_comment": "note",
            "metadata": {"extra": {"a": 1}},
        },
        {
            "id": 1,
            "submitted_at": 10,
            "message": "Older",
            "severity": None,
            "status": "done",
            "context": None,
            "model": None,
            "harness": None,
            "status_comment": None,
            "metadata": {},
        },
    ]
    assert feedback_payload["inventory"] == {
        "generated_at": feedback_payload["inventory"]["generated_at"],
        "severity_counts": {"bug": 1},
        "status_counts": {"done": 1, "open": 1},
        "total_feedback": 2,
    }
    assert _FakeFeedbackStore.init_paths[-1] == tmp_path / "feedback.db"

    calls = _FakeGraphStore.last_instance._graph.calls if _FakeGraphStore.last_instance else []
    assert any(
        statement == "MATCH (n:File) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit"
        and params == {"skip": 0, "limit": 2}
        for statement, params in calls
    )
    assert any(
        statement == "MATCH (n:File) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit"
        and params == {"skip": 2, "limit": 2}
        for statement, params in calls
    )


def test_run_export_command_raises_when_paged_graph_rows_are_truncated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_output = tmp_path / "graph-export.json"
    feedback_output = tmp_path / "feedback-export.json"

    _FakeGraphStore.counts = {
        "File": 3,
        "Section": 0,
        "Tag": 0,
        "Entity": 0,
        "Section NER links": 0,
        "relations": 0,
    }
    _FakeGraphStore.rows = {
        "File": [
            _node_row("file-a", title="Alpha", note="keep-a"),
            _node_row("file-b", title="Beta", note="keep-b"),
        ],
        "Section": [],
        "Tag": [],
        "Entity": [],
        "Section NER links": [],
        "relations": [],
    }
    monkeypatch.setattr(runner, "FalkorDBGraphStore", _FakeGraphStore)
    monkeypatch.setattr(runner, "FeedbackStore", _FakeFeedbackStore)
    monkeypatch.setattr(runner, "GRAPH_EXPORT_PAGE_SIZE", 2)

    with pytest.raises(RuntimeError, match="File nodes count mismatch: expected 3, got 2"):
        runner.run_export_command(
            runner.SurrealSourceExportRunnerConfig(
                graph_output=graph_output,
                feedback_output=feedback_output,
                falkordb_url="redis://example:6379",
                graph_name="dotmd",
                index_dir=tmp_path,
                progress_interval_seconds=9999.0,
            )
        )


def test_read_graph_rows_uses_property_id_not_falkor_internal_node_id() -> None:
    graph_store = SimpleNamespace(
        _graph=_FakeGraph(
            counts={
                "File": 0,
                "Section": 1,
                "Tag": 0,
                "Entity": 1,
                "Section NER links": 0,
                "relations": 1,
            },
            rows={
                "File": [],
                "Section": [
                    _node_row(
                        "section-property-id",
                        internal_id="123",
                        file_path="file-a",
                        heading="Heading",
                        level=1,
                        text_preview="Preview",
                    )
                ],
                "Tag": [],
                "Entity": [
                    _node_row(
                        "entity-property-id",
                        internal_id="456",
                        source="ner",
                        type="PERSON",
                    )
                ],
                "Section NER links": [],
                "relations": [
                    _relation_row(
                        "section-property-id",
                        "entity-property-id",
                        "MENTIONS",
                        1.0,
                    )
                ],
            },
        )
    )

    graph_data = runner._read_graph_rows(graph_store)  # type: ignore[arg-type]

    assert graph_data["nodes"] == [
        {
            "id": "section-property-id",
            "label": "Section",
            "properties": {
                "file_path": "file-a",
                "heading": "Heading",
                "level": 1,
                "text_preview": "Preview",
            },
        },
        {
            "id": "entity-property-id",
            "label": "Entity",
            "properties": {"source": "ner", "type": "PERSON"},
        },
    ]
    assert graph_data["edges"] == [
        {
            "source": "section-property-id",
            "target": "entity-property-id",
            "relation_type": "MENTIONS",
            "weight": 1.0,
        }
    ]
