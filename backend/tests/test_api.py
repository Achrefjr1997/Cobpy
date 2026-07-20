from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cobol_migrator.api import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_start_migration(client: TestClient) -> None:
    """Test starting a migration returns a run_id."""
    response = client.post(
        "/api/migrations",
        json={
            "source_type": "snippet",
            "source_ref": "DISPLAY 'HI'",
            "step_budget": 5,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert len(data["run_id"]) == 32


def test_start_migration_invalid_source_type(client: TestClient) -> None:
    """Test that invalid source_type returns 400."""
    response = client.post(
        "/api/migrations",
        json={
            "source_type": "invalid",
            "source_ref": "test",
        },
    )
    assert response.status_code == 400


def test_get_unknown_migration(client: TestClient) -> None:
    """Test that getting an unknown run returns 404."""
    response = client.get("/api/migrations/nonexistent123")
    assert response.status_code == 404


def test_sse_unknown_run(client: TestClient) -> None:
    """Test SSE for unknown run returns error event."""
    with client.stream("GET", "/api/migrations/unknown/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                import json

                data = json.loads(line[6:])
                events.append(data)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "not found" in events[0]["message"].lower()
