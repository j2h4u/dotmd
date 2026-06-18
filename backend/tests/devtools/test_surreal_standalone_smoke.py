from __future__ import annotations

import argparse
from typing import Any

import pytest
from devtools.surreal_standalone_smoke import SmokeConfig, load_config, run_smoke

pytestmark = pytest.mark.real_schema_check


class FakeSurreal:
    def __init__(self, _url: str) -> None:
        self.queries: list[tuple[str, dict[str, Any] | None]] = []

    def signin(self, credentials: dict[str, str]) -> None:
        assert credentials == {"username": "root", "password": "secret"}

    def use(self, namespace: str, database: str) -> None:
        assert (namespace, database) == ("dotmd", "phase43")

    def version(self) -> str:
        return "surrealdb-3.1.4"

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> list[dict[str, str]]:
        self.queries.append((statement, variables))
        if statement.startswith("SELECT created_by"):
            return [{"created_by": "dotmd smoke"}]
        return []

    def close(self) -> None:
        raise NotImplementedError


def test_load_config_reads_surreal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SURREAL_PASS", "secret")
    args = argparse.Namespace(
        url=None,
        username=None,
        password=None,
        namespace="dotmd",
        database="phase43",
        write_probe=True,
    )

    config = load_config(args)

    assert config.url == "ws://127.0.0.1:8000/rpc"
    assert config.username == "root"
    assert config.password == "secret"
    assert config.write_probe is True


def test_load_config_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SURREAL_PASS", raising=False)
    monkeypatch.delenv("SURREALDB_PASS", raising=False)
    args = argparse.Namespace(
        url=None,
        username=None,
        password=None,
        namespace="dotmd",
        database="phase43",
        write_probe=False,
    )

    with pytest.raises(ValueError, match="password is required"):
        load_config(args)


def test_run_smoke_checks_version_and_write_probe() -> None:
    config = SmokeConfig(
        url="ws://surrealdb:8000/rpc",
        username="root",
        password="secret",
        namespace="dotmd",
        database="phase43",
        write_probe=True,
    )

    result = run_smoke(config, connection_factory=FakeSurreal)

    assert result.server_version == "surrealdb-3.1.4"
    assert result.write_probe is True
