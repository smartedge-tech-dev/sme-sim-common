# Changelog

All notable changes to sme-sim-common are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - YYYY-MM-DD

First release. The API below is the 1.x compatibility promise.

### Added
- Static assets (served under `/sme-sim-common`): web shell (`shell.js` / `shell.css`: header, menu bar,
  status area, footer, About dialog with the common library version, toasts, system / light / dark theme,
  i18n helper), `brand/` assets, `vendor/` (`vendor.js`: preset `Shell.vendors.smartEdge`, `vendor.*` strings,
  `--vendor-accent` token) and `common.js` (`common.*` strings in en / ja / zh).
- `config`: YAML / JSON config loading (`parse_text`) and atomic writing (`atomic_write_text`).
- `web`: `mount_common`, `mount_product_static`, `bad` (HTTP errors, pydantic `ValidationError` flattened) and
  `make_base_app` returning a `fastapi.FastAPI` with the standard routes (`/api/version`, `/api/state`,
  `/api/config*`, `/ws`, and the optional xlsx / templates / devices / simulation groups); product routes are
  passed as `APIRouter`, Starlette `Router` or route lists via `product_routers`.
- `engine`: `EngineProtocol` and `BaseEngine` (event log with `event_history(limit)`, subscribe / publish
  fan-out, simulation clock).
- `behaviors`: behavior definitions and compilation.
- `templates`: `TemplateRegistry` (built-in and user device templates, `--templates-dir`).
- `xlsx`: `XlsxSchema` (Excel export / import / blank template; extra `[xlsx]`).
- `cli`: `add_common_args`, `run_web`, `add_validate_args`, `run_validate`.
- `testing`: pytest plugin (asyncio timeout + hang dump) and `check_i18n_keys` for the reserved
  `shell.*` / `vendor.*` / `common.*` prefixes.
- PyInstaller hook that collects the common static files and the uvicorn hidden imports.
- `templates/`: CI, docs, release (Windows exe, PyPI trusted publishing, optional Docker), PyInstaller spec,
  mkdocs, pyproject, page / style / i18n skeletons, LICENSE, CHANGELOG, README and the adoption checklist.
