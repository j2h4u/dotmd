"""Minimal host-side SurrealDB operational probe for dotMD.

This script checks the live SurrealDB retrieval endpoint without external
collectors. It reports short machine-readable results to stdout and a compact
human summary to stderr.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from dotmd.core.config import Settings

_DOCKER_LOG_TAIL = 200
_DOCKER_LOG_DETAIL_LINES = 5
_DOCKER_LOG_DETAIL_MAX_CHARS = 1000


@dataclass(slots=True, frozen=True)
class ProbeSettings:
    url: str
    namespace: str
    database: str
    username: str | None
    password: str | None
    access_token: str | None
    container: str
    timeout_seconds: float
    json_output: str | None


@dataclass(slots=True, frozen=True)
class CheckResult:
    name: str
    status: str
    elapsed_ms: int
    detail: str


@dataclass(slots=True, frozen=True)
class ProbeReport:
    generated_at: str
    settings: dict[str, Any]
    base_url: str
    request_url: str
    checks: list[CheckResult]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme in {"ws", "wss"}:
        scheme = "http" if parsed.scheme == "ws" else "https"
        return urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return url


def _redact_text(text: str, secrets: list[str | None]) -> str:
    redacted = text
    for secret in sorted({secret for secret in secrets if secret}, key=len, reverse=True):
        redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _tail_non_empty_lines(text: str, max_lines: int, max_chars: int) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    tail = lines[-max_lines:]
    if not tail:
        return ""
    return "\n".join(tail)[:max_chars]


def _read_settings_from_env() -> ProbeSettings:
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

    return ProbeSettings(
        url=url,
        namespace=namespace,
        database=database,
        username=username,
        password=password,
        access_token=access_token,
        container="surrealdb",
        timeout_seconds=5.0,
        json_output=None,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal SurrealDB operational probe")
    parser.add_argument("--url", default=None, help="Override surreal_retrieval.url.")
    parser.add_argument(
        "--container",
        default="surrealdb",
        help="Docker container name for stats/logs collection.",
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-check timeout in seconds.")
    parser.add_argument(
        "--json-output",
        default=None,
        help="Optional path to write the JSON report in addition to stdout.",
    )
    return parser


def _parse_settings(args: argparse.Namespace) -> ProbeSettings:
    base = _read_settings_from_env()
    return ProbeSettings(
        url=args.url or base.url,
        namespace=base.namespace,
        database=base.database,
        username=base.username,
        password=base.password,
        access_token=base.access_token,
        container=args.container,
        timeout_seconds=float(args.timeout),
        json_output=args.json_output,
    )


def _request_headers(settings: ProbeSettings) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Surreal-NS": settings.namespace,
        "Surreal-DB": settings.database,
    }
    if settings.access_token:
        headers["Authorization"] = f"Bearer {settings.access_token}"
    return headers


def _request_auth(settings: ProbeSettings) -> tuple[str, str] | None:
    if settings.username and settings.password:
        return (settings.username, settings.password)
    return None


def _request_timeout_error(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "connect timeout"
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "read timeout"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    return "error"


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _http_get(settings: ProbeSettings, path: str) -> CheckResult:
    started_at = perf_counter()
    url = f"{_coerce_url(settings.url).rstrip('/')}{path}"
    try:
        response = requests.get(
            url,
            headers=_request_headers(settings),
            auth=_request_auth(settings),
            timeout=settings.timeout_seconds,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        elapsed_ms = _elapsed_ms(started_at)
        status = _request_timeout_error(exc)
        if status in {"connect timeout", "read timeout", "timeout"}:
            return CheckResult(
                name=path.lstrip("/"), status="timeout", elapsed_ms=elapsed_ms, detail=status
            )
        return CheckResult(
            name=path.lstrip("/"), status="error", elapsed_ms=elapsed_ms, detail=str(exc)
        )

    body_text = (response.text or "").strip()
    if path == "/health":
        try:
            payload = response.json()
        except ValueError:
            payload = None
        health_ok = response.status_code == 200 and (
            body_text == ""
            or payload == {"status": "ok"}
            or (isinstance(payload, dict) and payload.get("status") == "ok")
            or body_text == "ok"
        )
        if health_ok:
            detail = "200" if body_text == "" else "200 ok"
            status = "ok"
        else:
            detail = f"{response.status_code} {body_text[:120]}".strip()
            status = "error"
    else:
        if response.status_code == 200:
            detail = f"200 {body_text[:120]}".strip()
            status = "ok"
        else:
            detail = f"{response.status_code} {body_text[:120]}".strip()
            status = "error"
    return CheckResult(
        name=path.lstrip("/"), status=status, elapsed_ms=_elapsed_ms(started_at), detail=detail
    )


def _sql_return_one(settings: ProbeSettings) -> CheckResult:
    started_at = perf_counter()
    request_url = f"{_coerce_url(settings.url).rstrip('/')}/sql"
    try:
        response = requests.post(
            request_url,
            headers={
                **_request_headers(settings),
                "Content-Type": "application/surrealql",
            },
            auth=_request_auth(settings),
            data=b"RETURN 1;",
            timeout=settings.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        elapsed_ms = _elapsed_ms(started_at)
        status = _request_timeout_error(exc)
        if status in {"connect timeout", "read timeout", "timeout"}:
            return CheckResult(name="sql", status="timeout", elapsed_ms=elapsed_ms, detail=status)
        return CheckResult(name="sql", status="error", elapsed_ms=elapsed_ms, detail=str(exc))

    result: Any
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            if first.get("status") == "ERR":
                detail = str(first.get("detail") or first.get("result") or first)
                return CheckResult(
                    name="sql",
                    status="error",
                    elapsed_ms=_elapsed_ms(started_at),
                    detail=detail,
                )
            result = first.get("result")
        else:
            result = first
    else:
        result = payload
    if result == 1:
        detail = "1"
        status = "ok"
    else:
        detail = f"unexpected result: {result!r}"
        status = "error"
    return CheckResult(name="sql", status=status, elapsed_ms=_elapsed_ms(started_at), detail=detail)


def _run_subprocess(argv: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, check=False, capture_output=True, text=True, timeout=timeout_seconds
    )


def _docker_stats(settings: ProbeSettings) -> CheckResult:
    started_at = perf_counter()
    if shutil.which("docker") is None:
        return CheckResult(
            name="docker_stats",
            status="skipped",
            elapsed_ms=_elapsed_ms(started_at),
            detail="docker not available",
        )
    argv = [
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{.Container}} {{.CPUPerc}} {{.MemUsage}} {{.MemPerc}}",
        settings.container,
    ]
    try:
        completed = _run_subprocess(argv, settings.timeout_seconds)
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="docker_stats",
            status="timeout",
            elapsed_ms=_elapsed_ms(started_at),
            detail="timeout",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult(
            name="docker_stats",
            status="error",
            elapsed_ms=_elapsed_ms(started_at),
            detail=str(exc),
        )

    output = (completed.stdout or completed.stderr or "").strip()
    output = _redact_text(output, [settings.username, settings.password, settings.access_token])
    if completed.returncode == 0:
        return CheckResult(
            name="docker_stats",
            status="ok",
            elapsed_ms=_elapsed_ms(started_at),
            detail=output[:120],
        )
    return CheckResult(
        name="docker_stats",
        status="error",
        elapsed_ms=_elapsed_ms(started_at),
        detail=output[:120],
    )


def _docker_logs(settings: ProbeSettings) -> CheckResult:
    started_at = perf_counter()
    if shutil.which("docker") is None:
        return CheckResult(
            name="docker_logs",
            status="skipped",
            elapsed_ms=_elapsed_ms(started_at),
            detail="docker not available",
        )
    argv = [
        "docker",
        "logs",
        "--tail",
        str(_DOCKER_LOG_TAIL),
        settings.container,
    ]
    try:
        completed = _run_subprocess(argv, settings.timeout_seconds)
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="docker_logs",
            status="timeout",
            elapsed_ms=_elapsed_ms(started_at),
            detail="timeout",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult(
            name="docker_logs",
            status="error",
            elapsed_ms=_elapsed_ms(started_at),
            detail=str(exc),
        )

    output = _redact_text(
        (completed.stdout or completed.stderr or "").strip(),
        [settings.username, settings.password, settings.access_token],
    )
    detail = _tail_non_empty_lines(output, _DOCKER_LOG_DETAIL_LINES, _DOCKER_LOG_DETAIL_MAX_CHARS)
    if completed.returncode == 0:
        return CheckResult(
            name="docker_logs",
            status="ok",
            elapsed_ms=_elapsed_ms(started_at),
            detail=detail,
        )
    return CheckResult(
        name="docker_logs",
        status="error",
        elapsed_ms=_elapsed_ms(started_at),
        detail=detail,
    )


def run_probe(settings: ProbeSettings) -> ProbeReport:
    base_url = _coerce_url(settings.url)
    checks = [
        _http_get(settings, "/health"),
        _http_get(settings, "/metrics"),
        _sql_return_one(settings),
        _docker_stats(settings),
        _docker_logs(settings),
    ]
    return ProbeReport(
        generated_at=_utc_now(),
        settings={
            "url": base_url,
            "namespace": settings.namespace,
            "database": settings.database,
            "has_username": bool(settings.username),
            "has_password": bool(settings.password),
            "has_access_token": bool(settings.access_token),
            "container": settings.container,
            "timeout_seconds": settings.timeout_seconds,
        },
        base_url=base_url,
        request_url=f"{base_url.rstrip('/')}/sql",
        checks=checks,
    )


def _json_payload(report: ProbeReport) -> dict[str, Any]:
    health_ok = report.checks[0].status == "ok"
    sql_ok = report.checks[2].status == "ok"
    docker_stats_ok = report.checks[3].status == "ok"
    if health_ok and sql_ok:
        diagnosis = "ok"
    elif (
        docker_stats_ok
        and report.checks[0].status == "timeout"
        and report.checks[2].status == "timeout"
    ):
        diagnosis = "process_alive_http_query_plane_unavailable"
    elif health_ok and report.checks[2].status == "timeout":
        diagnosis = "health_alive_sql_unavailable"
    else:
        diagnosis = "unavailable"
    return {
        "generated_at": report.generated_at,
        "settings": report.settings,
        "base_url": report.base_url,
        "request_url": report.request_url,
        "checks": [asdict(check) for check in report.checks],
        "summary": {
            "health_ok": health_ok,
            "sql_ok": sql_ok,
            "fatal": not (health_ok and sql_ok),
            "diagnosis": diagnosis,
        },
    }


def _human_summary(report: ProbeReport) -> str:
    payload = _json_payload(report)
    parts = [f"{check.name}={check.status}" for check in report.checks]
    return " ".join(parts) + f" diagnosis={payload['summary']['diagnosis']}"


def _write_json_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = _parse_settings(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report = run_probe(settings)
    payload = _json_payload(report)
    summary = _human_summary(report)
    print(summary, file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if settings.json_output:
        _write_json_output(Path(settings.json_output), payload)
    if payload["summary"]["fatal"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
