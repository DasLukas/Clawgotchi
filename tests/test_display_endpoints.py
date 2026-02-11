from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from main import create_app


def test_display_capabilities_endpoint(tmp_path: Path) -> None:
    database_path = tmp_path / "display-capabilities.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        response = client.get("/api/display/capabilities")
        assert response.status_code == 200
        assert response.json() == {"width": 264, "height": 176, "mode": "1bit"}

        meta = client.get("/api/display/frame.meta")
        assert meta.status_code == 200
        assert meta.json()["width"] == response.json()["width"]
        assert meta.json()["height"] == response.json()["height"]


def test_display_frame_png_changes_after_framebuffer_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "display-frame.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        initial_meta = client.get("/api/display/frame.meta")
        assert initial_meta.status_code == 200
        initial_version = initial_meta.json()["version"]

        initial_png = client.get("/api/display/frame.png")
        assert initial_png.status_code == 200
        assert initial_png.headers["content-type"] == "image/png"

        with Image.open(BytesIO(initial_png.content)) as image:
            assert image.size == (264, 176)
            assert image.mode == "1"

        container = app.state.container
        current = container.framebuffer.to_pil_image().getpixel((0, 0))
        next_color = 1 if current == 0 else 0
        container.framebuffer.set_pixel(0, 0, next_color)
        container.display_manager.push(container.framebuffer)

        changed_meta = client.get("/api/display/frame.meta")
        assert changed_meta.status_code == 200
        changed_payload = changed_meta.json()
        assert changed_payload["version"] > initial_version

        changed_png = client.get("/api/display/frame.png")
        assert changed_png.status_code == 200
        assert changed_png.content != initial_png.content


def test_dashboard_contains_display_mirror_and_virtual_buttons_only(tmp_path: Path) -> None:
    database_path = tmp_path / "dashboard-display.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        setup_response = client.post(
            "/setup",
            data={
                "pet_name": "Mochi",
                "theme_id": "default",
                "hardware_profile": "dummy",
            },
            follow_redirects=False,
        )
        assert setup_response.status_code == 303

        response = client.get("/dashboard")
        assert response.status_code == 200

        html = response.text
        assert 'id="dashboard-display-frame"' in html
        assert "dashboard-display-card" in html
        assert "tamagotchi-shell" in html
        assert "virtual-control-button" in html

        assert "Live Readout" not in html
        assert "Command Deck" not in html
        assert "Pet State" not in html
        assert "/api/display/frame.png" in html
        assert 'data-button="NEXT"' in html
        assert 'data-button="BACK"' in html
        assert 'data-button="CONFIRM"' in html
        assert 'data-button="SPECIAL"' in html
        assert html.count('data-button="') == 4


def test_separate_display_page_is_not_available(tmp_path: Path) -> None:
    database_path = tmp_path / "dashboard-no-display-page.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        response = client.get("/display")
        assert response.status_code == 404


def test_input_button_endpoint_accepts_valid_button(tmp_path: Path) -> None:
    database_path = tmp_path / "input-button.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        ok_response = client.post("/api/input/button", json={"button": "NEXT"})
        assert ok_response.status_code == 200
        assert ok_response.json() == {"ok": True}

        bad_response = client.post("/api/input/button", json={"button": "UNKNOWN"})
        assert bad_response.status_code == 400


def test_sidebar_is_rendered_into_framebuffer_output(tmp_path: Path) -> None:
    database_path = tmp_path / "sidebar-frame.db"
    app = create_app(
        {
            "database_url": f"sqlite:///{database_path}",
            "tick_interval_seconds": 120.0,
            "plugin_directory": "./plugins",
            "theme_directory": "./themes",
        }
    )

    with TestClient(app) as client:
        response = client.get("/api/display/frame.png")
        assert response.status_code == 200

        with Image.open(BytesIO(response.content)) as image:
            mono = image.convert("1")
            width, height = mono.size
            sidebar_probe_width = min(72, max(1, int(width * 0.25)))
            sidebar = mono.crop((0, 0, sidebar_probe_width, height))

            # In mode "1", black pixel is 0.
            black_pixels = sum(1 for value in sidebar.getdata() if value == 0)
            assert black_pixels > 0
