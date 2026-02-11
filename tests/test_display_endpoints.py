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
