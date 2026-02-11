from __future__ import annotations

from io import BytesIO
import hashlib
import threading
import time

from PIL import Image


class FrameBuffer1Bit:
    """Thread-safe 1-bit framebuffer used as single source of truth for all display outputs."""

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("Framebuffer width and height must be positive integers.")

        self._width = int(width)
        self._height = int(height)
        self._stride = (self._width + 7) // 8
        self._buffer = bytearray([0xFF] * (self._stride * self._height))

        self._lock = threading.RLock()
        self._version = 0
        self._updated_at_ms = int(time.time() * 1000)

        self._png_cache_version = -1
        self._png_cache: bytes | None = None
        self._hash_cache_version = -1
        self._hash_cache: str | None = None

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    @property
    def updated_at_ms(self) -> int:
        with self._lock:
            return self._updated_at_ms

    def clear(self, color: int) -> None:
        normalized = self._normalize_color(color)
        fill_byte = 0xFF if normalized == 1 else 0x00

        with self._lock:
            changed = False
            tail_mask = self._tail_mask

            for row in range(self._height):
                base = row * self._stride
                for offset in range(self._stride):
                    idx = base + offset
                    target = fill_byte
                    if offset == self._stride - 1 and tail_mask != 0xFF and normalized == 0:
                        # Keep unused trailing bits white to avoid non-deterministic padding noise.
                        target = (~tail_mask) & 0xFF
                    if self._buffer[idx] != target:
                        self._buffer[idx] = target
                        changed = True

            if changed:
                self._touch_unlocked()

    def set_pixel(self, x: int, y: int, color: int) -> None:
        with self._lock:
            if self._set_pixel_unlocked(x, y, self._normalize_color(color)):
                self._touch_unlocked()

    def blit_mono_image(self, image: Image.Image, x: int, y: int) -> None:
        if not isinstance(image, Image.Image):
            raise TypeError("blit_mono_image expects a PIL.Image instance.")

        prepared = image.convert("L").point(lambda pixel: 255 if pixel >= 128 else 0, mode="1")
        source_pixels = prepared.load()

        start_x = max(0, -x)
        start_y = max(0, -y)
        end_x = min(prepared.width, self._width - x)
        end_y = min(prepared.height, self._height - y)

        if start_x >= end_x or start_y >= end_y:
            return

        with self._lock:
            changed = False
            for source_y in range(start_y, end_y):
                target_y = y + source_y
                for source_x in range(start_x, end_x):
                    target_x = x + source_x
                    pixel = source_pixels[source_x, source_y]
                    color = 1 if pixel else 0
                    if self._set_pixel_unlocked(target_x, target_y, color):
                        changed = True

            if changed:
                self._touch_unlocked()

    def replace_from_image(self, image: Image.Image) -> bool:
        if not isinstance(image, Image.Image):
            raise TypeError("replace_from_image expects a PIL.Image instance.")

        prepared = image.convert("L").point(lambda pixel: 255 if pixel >= 128 else 0, mode="1")
        if prepared.size != (self._width, self._height):
            raise ValueError(
                f"Image size {prepared.size} does not match framebuffer size {self._width}x{self._height}."
            )

        payload = prepared.tobytes()

        with self._lock:
            if payload == bytes(self._buffer):
                return False

            self._buffer[:] = payload
            self._touch_unlocked()
            return True

    def to_png_bytes(self) -> bytes:
        with self._lock:
            if self._png_cache is not None and self._png_cache_version == self._version:
                return self._png_cache

            image = Image.frombytes("1", (self._width, self._height), bytes(self._buffer))
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            self._png_cache = buffer.getvalue()
            self._png_cache_version = self._version
            return self._png_cache

    def to_pil_image(self) -> Image.Image:
        with self._lock:
            return Image.frombytes("1", (self._width, self._height), bytes(self._buffer))

    def to_mono_bytes(self) -> bytes:
        with self._lock:
            return bytes(self._buffer)

    def hash(self) -> str:
        with self._lock:
            if self._hash_cache is not None and self._hash_cache_version == self._version:
                return self._hash_cache

            digest = hashlib.sha256(bytes(self._buffer)).hexdigest()
            self._hash_cache = digest
            self._hash_cache_version = self._version
            return digest

    def _set_pixel_unlocked(self, x: int, y: int, color: int) -> bool:
        if x < 0 or x >= self._width or y < 0 or y >= self._height:
            raise IndexError(f"Pixel ({x}, {y}) is out of bounds for framebuffer {self._width}x{self._height}.")

        row_offset = y * self._stride
        byte_index = row_offset + (x // 8)
        bit_mask = 0x80 >> (x % 8)

        before = self._buffer[byte_index]
        if color == 1:
            after = before | bit_mask
        else:
            after = before & (~bit_mask & 0xFF)

        if before == after:
            return False

        self._buffer[byte_index] = after
        return True

    def _touch_unlocked(self) -> None:
        self._version += 1
        self._updated_at_ms = int(time.time() * 1000)

    @property
    def _tail_mask(self) -> int:
        remainder = self._width % 8
        if remainder == 0:
            return 0xFF
        return (0xFF << (8 - remainder)) & 0xFF

    @staticmethod
    def _normalize_color(color: int) -> int:
        if color in (0, 1):
            return int(color)
        raise ValueError("Color must be 0 (black) or 1 (white).")
