from __future__ import annotations

import json
import subprocess
import types
from pathlib import Path

import devtools.surreal_operational_probe as probe
import pytest
import requests


class _FakeResponse:
    def __init__(self, status_code: int, payload: object, text: str) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self) -> object:
        return self._payload


def test_main_reports_success_and_redacts_docker_logs(monkeypatch, capsys, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    secrets = {
        "username": "probe-user",
        "password": "probe-pass",
        "token": "probe-token",
    }

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        calls.append(("get", url))
        if url.endswith("/health"):
            assert kwargs["auth"] == (secrets["username"], secrets["password"])
            return _FakeResponse(200, None, "")
        if url.endswith("/metrics"):
            return _FakeResponse(200, None, "metrics_total 1")
        raise AssertionError(url)

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        calls.append(("post", url))
        assert kwargs["auth"] == (secrets["username"], secrets["password"])
        assert kwargs["data"] == b"RETURN 1;"
        return _FakeResponse(200, [{"status": "OK", "result": 1}], '[{"status":"OK","result":1}]')

    monkeypatch.setattr(
        probe,
        "requests",
        types.SimpleNamespace(get=fake_get, post=fake_post, exceptions=requests.exceptions),
    )
    monkeypatch.setattr(
        probe.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None
    )

    def fake_run(argv: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        assert timeout_seconds == 5.0
        if argv[1] == "stats":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="surrealdb 12.5% 256MiB / 1GiB 25.0%\n",
                stderr="",
            )
        if argv[1] == "logs":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    "SurrealDB 2.0.0\n"
                    "banner line 2\n"
                    f"boot username={secrets['username']} password={secrets['password']}\n"
                    "line 4\n"
                    "line 5\n"
                    "line 6\n"
                    "line 7\n"
                ),
                stderr="",
            )
        raise AssertionError(argv)

    monkeypatch.setattr(probe, "_run_subprocess", fake_run)
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__URL", "ws://surreal.example:8000/rpc")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__NAMESPACE", "dotmd")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__DATABASE", "production")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__USERNAME", secrets["username"])
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__PASSWORD", secrets["password"])
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL__ACCESS_TOKEN", raising=False)

    json_output = tmp_path / "probe.json"
    exit_code = probe.main(["--json-output", str(json_output)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["base_url"] == "http://surreal.example:8000/rpc"
    assert payload["request_url"] == "http://surreal.example:8000/rpc/sql"
    assert [check["status"] for check in payload["checks"]] == ["ok", "ok", "ok", "ok", "ok"]
    assert payload["checks"][0]["detail"] == "200"
    assert calls == [
        ("get", "http://surreal.example:8000/rpc/health"),
        ("get", "http://surreal.example:8000/rpc/metrics"),
        ("post", "http://surreal.example:8000/rpc/sql"),
    ]
    assert json_output.exists()
    assert json.loads(json_output.read_text(encoding="utf-8")) == payload
    assert secrets["username"] not in captured.out
    assert secrets["password"] not in captured.out
    assert secrets["token"] not in captured.out
    assert secrets["username"] not in captured.err
    assert secrets["password"] not in captured.err
    assert secrets["token"] not in captured.err
    assert (
        payload["checks"][4]["detail"]
        == "boot username=[redacted] password=[redacted]\nline 4\nline 5\nline 6\nline 7"
    )
    assert len(payload["checks"][4]["detail"]) <= 1000
    assert "SurrealDB 2.0.0" not in payload["checks"][4]["detail"]
    assert "[redacted]" in payload["checks"][4]["detail"]


@pytest.mark.parametrize(
    ("payload", "text", "expected_detail"),
    [
        (None, "", "200"),
        ({"status": "ok"}, '{"status":"ok"}', "200 ok"),
        (None, "ok", "200 ok"),
    ],
)
def test_http_get_accepts_surreal_health_variants(
    monkeypatch, payload: object, text: str, expected_detail: str
) -> None:
    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        assert url.endswith("/health")
        return _FakeResponse(200, payload, text)

    monkeypatch.setattr(
        probe,
        "requests",
        types.SimpleNamespace(get=fake_get, post=None, exceptions=requests.exceptions),
    )

    result = probe._http_get(
        probe.ProbeSettings(
            url="http://surreal.example:8000",
            namespace="dotmd",
            database="production",
            username=None,
            password=None,
            access_token=None,
            container="surrealdb",
            timeout_seconds=5.0,
            json_output=None,
        ),
        "/health",
    )

    assert result.status == "ok"
    assert result.detail == expected_detail


def test_main_distinguishes_connect_and_read_timeouts(monkeypatch, capsys) -> None:
    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        if url.endswith("/health"):
            raise requests.exceptions.ConnectTimeout("connect timed out")
        if url.endswith("/metrics"):
            return _FakeResponse(200, None, "metrics_total 1")
        raise AssertionError(url)

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        raise requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(
        probe,
        "requests",
        types.SimpleNamespace(get=fake_get, post=fake_post, exceptions=requests.exceptions),
    )
    monkeypatch.setattr(
        probe.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None
    )

    def fake_run(argv: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        assert timeout_seconds == 5.0
        if argv[1] == "stats":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    "surrealdb 12.5% 256MiB / 1GiB 25.0%\n"
                    "older log line\n"
                    "older log line\n"
                    "older log line\n"
                    "older log line\n"
                    "older log line\n"
                ),
                stderr="",
            )
        if argv[1] == "logs":
            return subprocess.CompletedProcess(argv, 0, stdout="log line", stderr="")
        raise AssertionError(argv)

    monkeypatch.setattr(probe, "_run_subprocess", fake_run)
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__URL", "http://surreal.example:8000")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__NAMESPACE", "dotmd")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__DATABASE", "production")
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL__USERNAME", raising=False)
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL__PASSWORD", raising=False)
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL__ACCESS_TOKEN", raising=False)

    exit_code = probe.main([])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["checks"][0]["status"] == "timeout"
    assert payload["checks"][0]["detail"] == "connect timeout"
    assert payload["checks"][2]["status"] == "timeout"
    assert payload["checks"][2]["detail"] == "read timeout"
    assert payload["checks"][3]["status"] == "ok"
    assert payload["summary"] == {
        "fatal": True,
        "health_ok": False,
        "sql_ok": False,
        "diagnosis": "process_alive_http_query_plane_unavailable",
    }
    assert "health=timeout" in captured.err
    assert "sql=timeout" in captured.err
    assert "diagnosis=process_alive_http_query_plane_unavailable" in captured.err


def test_main_classifies_health_alive_sql_unavailable(monkeypatch, capsys) -> None:
    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        if url.endswith("/health"):
            return _FakeResponse(200, {"status": "ok"}, '{"status":"ok"}')
        if url.endswith("/metrics"):
            return _FakeResponse(200, None, "metrics_total 1")
        raise AssertionError(url)

    def fake_post(url: str, **kwargs: object) -> _FakeResponse:
        raise requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(
        probe,
        "requests",
        types.SimpleNamespace(get=fake_get, post=fake_post, exceptions=requests.exceptions),
    )
    monkeypatch.setattr(probe.shutil, "which", lambda name: None)
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__URL", "http://surreal.example:8000")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__NAMESPACE", "dotmd")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL__DATABASE", "production")
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL__USERNAME", raising=False)
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL__PASSWORD", raising=False)
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL__ACCESS_TOKEN", raising=False)

    exit_code = probe.main([])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["summary"] == {
        "fatal": True,
        "health_ok": True,
        "sql_ok": False,
        "diagnosis": "health_alive_sql_unavailable",
    }
    assert "diagnosis=health_alive_sql_unavailable" in captured.err


def test_redact_text_covers_username_password_and_token_values() -> None:
    text = "username=alice password=secret token=tok-123 other=keep"

    redacted = probe._redact_text(text, ["secret", "tok-123", "alice"])

    assert redacted == "username=[redacted] password=[redacted] token=[redacted] other=keep"
