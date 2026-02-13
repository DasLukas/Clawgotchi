from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import ConfigResolver, assert_runtime_home_writable, ensure_runtime_layout, get_runtime_layout


@dataclass(slots=True)
class DoctorReport:
    """Structured report returned by Clawgotchi doctor checks.

    Attributes:
        python_version: Runtime Python version string.
        platform: Platform descriptor from `platform.platform()`.
        runtime_home: Resolved runtime home directory.
        database_url: Resolved database URL.
        plugin_directories: Ordered plugin discovery roots.
        theme_directories: Ordered theme discovery roots.
        status: Human-readable overall status message.
    """

    python_version: str
    platform: str
    runtime_home: str
    database_url: str
    plugin_directories: list[str]
    theme_directories: list[str]
    status: str


def _check_python_version(min_major: int = 3, min_minor: int = 11) -> None:
    """Validate Python version compatibility.

    Parameters:
        min_major: Required major version.
        min_minor: Required minor version.

    Raises:
        RuntimeError: If the current interpreter is older than required.
    """

    if sys.version_info < (min_major, min_minor):
        raise RuntimeError(
            "Python version is too old. "
            f"Detected {sys.version_info.major}.{sys.version_info.minor}, required >= {min_major}.{min_minor}."
        )


def _run_import_smoke() -> None:
    """Perform a lightweight import smoke test for core entrypoints.

    Raises:
        RuntimeError: If required modules cannot be imported.
    """

    try:
        import main  # noqa: F401
        from app.container import ApplicationContainer  # noqa: F401
    except Exception as exc:  # pragma: no cover - explicit diagnostic path
        raise RuntimeError(f"Import smoke test failed: {exc}") from exc


async def _run_startup_smoke_async(timeout_seconds: float) -> None:
    """Start and stop the application container once as a runtime smoke test.

    Parameters:
        timeout_seconds: Timeout budget for startup and shutdown.

    Raises:
        RuntimeError: If startup or shutdown fails or times out.
    """

    from app.container import ApplicationContainer

    container = ApplicationContainer(config_overrides={"display_type": "dummy"})
    try:
        await asyncio.wait_for(container.startup(), timeout=timeout_seconds)
    except Exception as exc:
        raise RuntimeError(f"Startup smoke test failed: {exc}") from exc
    finally:
        try:
            await asyncio.wait_for(container.shutdown(), timeout=timeout_seconds)
        except Exception as exc:
            raise RuntimeError(f"Shutdown smoke test failed: {exc}") from exc


def _run_startup_smoke(timeout_seconds: float) -> None:
    """Run startup smoke test using a dedicated event loop.

    Parameters:
        timeout_seconds: Timeout budget for startup and shutdown.
    """

    asyncio.run(_run_startup_smoke_async(timeout_seconds=timeout_seconds))


def build_report() -> DoctorReport:
    """Build a diagnostic report from resolved runtime configuration.

    Returns:
        A `DoctorReport` with normalized runtime configuration values.
    """

    resolver = ConfigResolver()
    config = resolver.resolve()
    ensure_runtime_layout(config.runtime_home)
    assert_runtime_home_writable(config.runtime_home)

    layout = get_runtime_layout(config.runtime_home)
    return DoctorReport(
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform=platform.platform(),
        runtime_home=str(config.runtime_home),
        database_url=config.database_url,
        plugin_directories=[str(path) for path in config.plugin_directories],
        theme_directories=[str(path) for path in config.theme_directories],
        status=f"Runtime layout is healthy at {layout['runtime_home']}",
    )


def _print_report(report: DoctorReport, as_json: bool) -> None:
    """Print doctor report in JSON or plain-text format.

    Parameters:
        report: Report payload to render.
        as_json: When true, print compact JSON output.
    """

    payload = asdict(report)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(f"Python: {report.python_version}")
    print(f"Platform: {report.platform}")
    print(f"Runtime home: {report.runtime_home}")
    print(f"Database URL: {report.database_url}")
    print("Plugin roots:")
    for path in report.plugin_directories:
        print(f"  - {path}")
    print("Theme roots:")
    for path in report.theme_directories:
        print(f"  - {path}")
    print(f"Status: {report.status}")


def main(argv: list[str] | None = None) -> int:
    """Run Clawgotchi installation diagnostics and smoke checks.

    Parameters:
        argv: Optional CLI argument list.

    Returns:
        Exit code (`0` for success, non-zero on failure).

    Usage example:
        `python -m clawgotchi.tools.doctor --smoke --check-startup`
    """

    parser = argparse.ArgumentParser(description="Run Clawgotchi diagnostics and smoke checks.")
    parser.add_argument("--json", action="store_true", help="Print report as JSON.")
    parser.add_argument("--smoke", action="store_true", help="Run module import smoke checks.")
    parser.add_argument(
        "--check-startup",
        action="store_true",
        help="Start and stop ApplicationContainer once.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=15.0,
        help="Timeout budget used by startup smoke checks.",
    )
    args = parser.parse_args(argv)

    try:
        _check_python_version()
        report = build_report()
        _print_report(report, as_json=args.json)

        if args.smoke:
            _run_import_smoke()
            print("Import smoke: OK")

        if args.check_startup:
            _run_startup_smoke(timeout_seconds=max(args.timeout_seconds, 1.0))
            print("Startup smoke: OK")
    except Exception as exc:
        print(f"Doctor failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
