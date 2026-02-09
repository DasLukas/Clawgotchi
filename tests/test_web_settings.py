from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from main import create_app


def test_settings_page_and_update_action(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "settings.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    from app.presentation import web

    update_script_path = tmp_path / "update.sh"
    update_script_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    update_script_path.chmod(0o755)
    monkeypatch.setattr(web, "UPDATE_SCRIPT_PATH", update_script_path)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(web.subprocess, "run", fake_run)

    with TestClient(app) as client:
        page_response = client.get("/settings")
        assert page_response.status_code == 200
        assert "Settings" in page_response.text

        update_response = client.post("/settings/update")
        assert update_response.status_code == 200
        assert "Update erfolgreich abgeschlossen." in update_response.text
        assert "ok" in update_response.text
