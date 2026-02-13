from __future__ import annotations

from pathlib import Path

from app.config import ConfigResolver


def test_config_defaults_point_to_runtime_home(monkeypatch, tmp_path: Path) -> None:
    runtime_home = tmp_path / "runtime-home"
    monkeypatch.setenv("CLAW_RUNTIME_HOME", str(runtime_home))
    monkeypatch.delenv("CLAW_DATABASE_URL", raising=False)
    monkeypatch.delenv("CLAW_PLUGIN_DIRECTORY", raising=False)
    monkeypatch.delenv("CLAW_THEME_DIRECTORY", raising=False)

    config = ConfigResolver().resolve()

    assert config.runtime_home.resolve() == runtime_home.resolve()
    assert config.plugin_directory.resolve() == (runtime_home / "plugins").resolve()
    assert config.theme_directory.resolve() == (runtime_home / "themes").resolve()
    assert config.database_url == f"sqlite:///{(runtime_home / 'db' / 'clawgotchi.db').resolve().as_posix()}"
    assert config.plugin_directories[0].resolve() == (runtime_home / "plugins").resolve()
    assert config.theme_directories[0].resolve() == (runtime_home / "themes").resolve()


def test_relative_sqlite_database_url_is_resolved_against_runtime_home(monkeypatch, tmp_path: Path) -> None:
    runtime_home = tmp_path / "runtime-home"
    monkeypatch.setenv("CLAW_RUNTIME_HOME", str(runtime_home))
    monkeypatch.setenv("CLAW_DATABASE_URL", "sqlite:///relative.db")

    config = ConfigResolver().resolve()

    expected = runtime_home / "relative.db"
    assert config.database_url == f"sqlite:///{expected.resolve().as_posix()}"
