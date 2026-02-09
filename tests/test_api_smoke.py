from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import create_app


def test_command_endpoint_accepts_feed(tmp_path: Path) -> None:
    database_path = tmp_path / "smoke.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={"type": "feed", "intensity": 0.8, "source": "api"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["accepted"] is True
        assert isinstance(payload["command_id"], str)
        assert payload["state_version"] >= 1


def test_export_import_dry_run(tmp_path: Path) -> None:
    database_path = tmp_path / "transfer.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        export_response = client.get("/api/v1/state/export")
        assert export_response.status_code == 200

        import_response = client.post(
            "/api/v1/state/import",
            json={"snapshot": export_response.json(), "dry_run": True},
        )
        assert import_response.status_code == 200
        payload = import_response.json()
        assert payload["dry_run"] is True
        assert payload["valid"] is True
