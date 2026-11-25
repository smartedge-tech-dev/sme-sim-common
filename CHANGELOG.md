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
- `web.make_base_app` extension points: `key_type` (device key type, inferred from the `device_key` field;
  path parameters are converted), `create_hook(engine, body)`, `duplicate_hook` called before the
  "already exists" check and allowed to change the key (default new key: `{key}_copy` for `str`, largest + 1
  for `int`), `simulation_hook(engine, rest)` for extra `POST /api/simulation` fields (result merged into the
  response), `import_hooks` (`POST /api/config/import` dispatched by file extension; `.xlsx` stays on the
  `XlsxSchema`; the event log records the warning count and the first 5 warnings).
- `web`: FastAPI `APIRouter` routes in `product_routers` are flattened into `app.routes` (still `APIRoute`, no
  `include_router` wrapper); error bodies with row errors also carry a top-level `errors` (`detail.errors` kept).
- `engine`: `BaseEngine.wake()` (thread-safe immediate `_on_tick` without advancing simulated time),
  `BaseEngine.logger_name` / `self.logger` for all engine logging, `EngineProtocol.config_path` typed
  `Union[str, Path, None]`.
- `cli`: `add_common_args(..., open_browser=True)` and `--browser` next to `--no-browser`.
- `web`: `duplicate_hook` gets the source device's key as `src_key` when it accepts that keyword (or `**kwargs`);
  404 `unknown device <key>` shows the converted key (`int` keys unquoted).
- `xlsx`: `open_columns` sheets export the scalar fields without a column as dynamic columns (`XlsxSchema.row`,
  collected by `XlsxSchema.extra_columns`); `export_rows` may return `(rows, extra_columns)` or
  `(rows, extra_columns, warnings)` (product warnings are reported before the shared ones);
  `Sheet.required_headers` (header must exist, cells may be empty) and `Sheet.skip_blank` (rows with an empty
  cell in these columns are skipped silently).
- `common.js`: `common.config.export_xlsx` (en / ja / zh).
- `behaviors`: behavior definitions and compilation.
- `templates`: `TemplateRegistry` (built-in and user device templates, `--templates-dir`).
- `xlsx`: `XlsxSchema` (Excel export / import / blank template; extra `[xlsx]`).
- `cli`: `add_common_args`, `run_web`, `add_validate_args`, `run_validate`.
- `testing`: pytest plugin (asyncio timeout + hang dump) and `check_i18n_keys` for the reserved
  `shell.*` / `vendor.*` / `common.*` prefixes.
- PyInstaller hook that collects the common static files and the uvicorn hidden imports.
- `templates/`: CI, docs, release (Windows exe, PyPI trusted publishing, optional Docker), PyInstaller spec,
  mkdocs, pyproject, page / style / i18n skeletons, LICENSE, CHANGELOG, README and the adoption checklist.
