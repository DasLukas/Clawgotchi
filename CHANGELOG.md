# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-09
### Added
- Initial layered Clawgotchi architecture (`domain`, `application`, `infrastructure`, `presentation`).
- FastAPI REST API, setup wizard UI, plugin registry UI, and theme registry UI.
- SQLite persistence with state snapshots, import/export support, and versioned state.
- Filesystem plugin and theme loaders with sample plugin and sample theme.
- Async command queue worker, async tick loop worker, and dummy hardware drivers.
- Smoke test skeleton and repository workflow documentation.
