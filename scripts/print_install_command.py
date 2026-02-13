#!/usr/bin/env python3
from __future__ import annotations

import platform


RAW_BASE_URL = "https://raw.githubusercontent.com/DasLukas/Clawgotchi/main"


def main() -> int:
    """Print the recommended one-line installer command for this platform.

    Returns:
        Exit status code.
    """

    system_name = platform.system().lower()
    if system_name == "windows":
        print(f"irm {RAW_BASE_URL}/install.ps1 | iex")
        return 0

    print(f"curl -fsSL {RAW_BASE_URL}/install | bash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
