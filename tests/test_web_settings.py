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
        assert "Display backend" in page_response.text
        assert "update-start-form" in page_response.text

        hardware_response = client.post("/settings/hardware", data={"hardware_profile": "dummy"})
        assert hardware_response.status_code == 200
        assert "Dummy display backend is active." in hardware_response.text

        update_response = client.post("/settings/update")
        assert update_response.status_code == 200
        assert "Update finished successfully." in update_response.text
        assert "ok" in update_response.text


def test_settings_async_update_start_and_status(tmp_path: Path, monkeypatch) -> None:
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

    status_file = tmp_path / "update-status.env"
    monkeypatch.setattr(web, "UPDATE_STATUS_FILE", status_file)
    monkeypatch.setattr(web.shutil, "which", lambda command: "/usr/bin/systemctl" if command == "systemctl" else None)
    monkeypatch.setattr(web.os, "geteuid", lambda: 1000)

    def fake_run(*args, **kwargs):
        command = args[0]

        if command[:3] == ["systemctl", "show", web.UPDATE_SERVICE_NAME]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="ActiveState=inactive\nSubState=dead\nResult=success\n",
                stderr="",
            )

        if command[:4] == ["sudo", "-n", "systemctl", "start"]:
            status_file.write_text(
                "\n".join(
                    [
                        "state=running",
                        "message=Update is running.",
                        "started_at=2026-02-11T10:00:00Z",
                        "updated_at=2026-02-11T10:00:01Z",
                        "reboot_required=false",
                        "reboot_scheduled=false",
                        "exit_code=0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(web.subprocess, "run", fake_run)

    with TestClient(app) as client:
        start_response = client.post("/settings/update/start")
        assert start_response.status_code == 200
        start_payload = start_response.json()
        assert start_payload["ok"] is True
        assert start_payload["status"]["state"] == "running"
        assert start_payload["status"]["running"] is True

        status_response = client.get("/settings/update/status")
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["state"] == "running"
        assert status_payload["running"] is True

        status_file.write_text(
            "\n".join(
                [
                    "state=succeeded",
                    "message=Update finished successfully.",
                    "started_at=2026-02-11T10:00:00Z",
                    "updated_at=2026-02-11T10:01:00Z",
                    "reboot_required=true",
                    "reboot_scheduled=true",
                    "exit_code=0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        finished_response = client.get("/settings/update/status")
        assert finished_response.status_code == 200
        finished_payload = finished_response.json()
        assert finished_payload["state"] == "succeeded"
        assert finished_payload["running"] is False
        assert finished_payload["reboot_required"] is True
        assert finished_payload["reboot_scheduled"] is True


def test_settings_update_falls_back_to_synchronous_mode_without_systemctl(tmp_path: Path, monkeypatch) -> None:
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

    monkeypatch.setattr(web.shutil, "which", lambda command: None if command == "systemctl" else None)

    with TestClient(app) as client:
        response = client.get("/settings")
        assert response.status_code == 200
        assert 'data-async-enabled="false"' in response.text
        assert 'action="/settings/update"' in response.text
        assert "Falling back to synchronous execution." in response.text
