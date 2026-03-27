"""Smoke test configuration -- runs against a live dotMD stack."""

import os

import httpx
import pytest

DOTMD_URL = os.environ.get("DOTMD_SMOKE_URL", "http://localhost:8321")


def pytest_collection_modifyitems(config, items):
    """Skip all smoke tests if the stack is unreachable."""
    try:
        r = httpx.get(f"{DOTMD_URL}/health", timeout=5.0)
        if r.status_code == 200:
            return
    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    skip_marker = pytest.mark.skip(
        reason=f"dotMD stack not reachable at {DOTMD_URL}"
    )
    for item in items:
        item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def ensure_indexed(client):
    """Skip smoke tests if no data has been indexed."""
    r = client.get("/status")
    data = r.json()
    if data["total_chunks"] == 0:
        pytest.skip("No data indexed -- smoke tests require indexed content")


@pytest.fixture(scope="session")
def api_url() -> str:
    """Base URL for the dotMD API."""
    return DOTMD_URL


@pytest.fixture(scope="session")
def client():
    """Reusable HTTP client for the test session."""
    with httpx.Client(base_url=DOTMD_URL, timeout=30.0) as c:
        yield c
