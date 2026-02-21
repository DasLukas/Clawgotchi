from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_repo_root
from main import create_app


def test_settings_page_and_hardware_action(tmp_path: Path) -> None:
    database_path = tmp_path / "settings.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        page_response = client.get("/settings")
        assert page_response.status_code == 200
        assert "Settings" in page_response.text
        assert "Display backend" in page_response.text
        assert "Software Updates" in page_response.text
        assert "git pull --ff-only" in page_response.text

        hardware_response = client.post("/settings/hardware", data={"hardware_profile": "dummy"})
        assert hardware_response.status_code == 200
        assert "Dummy display backend is active." in hardware_response.text

        assert client.post("/settings/update").status_code == 404
        assert client.post("/settings/update/start").status_code == 404
        assert client.get("/settings/update/status").status_code == 404


def test_settings_manual_update_hint_contains_repo_path(tmp_path: Path) -> None:
    database_path = tmp_path / "settings.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        response = client.get("/settings")
        assert response.status_code == 200
        assert str(get_repo_root()) in response.text
