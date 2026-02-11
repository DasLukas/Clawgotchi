from __future__ import annotations

from io import BytesIO

from PIL import Image

from core.framebuffer import FrameBuffer1Bit


def test_framebuffer_set_pixel_and_png_encoding() -> None:
    framebuffer = FrameBuffer1Bit(width=16, height=8)
    framebuffer.clear(1)
    framebuffer.set_pixel(3, 2, 0)

    payload = framebuffer.to_png_bytes()

    with Image.open(BytesIO(payload)) as image:
        assert image.size == (16, 8)
        assert image.mode == "1"
        assert image.getpixel((3, 2)) == 0


def test_framebuffer_version_increments_on_mutation() -> None:
    framebuffer = FrameBuffer1Bit(width=8, height=8)

    initial_version = framebuffer.version
    framebuffer.set_pixel(0, 0, 1)
    assert framebuffer.version == initial_version

    framebuffer.set_pixel(0, 0, 0)
    after_black = framebuffer.version
    assert after_black == initial_version + 1

    framebuffer.set_pixel(0, 0, 0)
    assert framebuffer.version == after_black

    framebuffer.clear(1)
    assert framebuffer.version == after_black + 1
