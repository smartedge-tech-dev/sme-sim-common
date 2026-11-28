# Changelog

All notable changes to sme-sim-common are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

Planned as 1.3.0.

### Added
- `sme_sim_common.mcp_server` (optional extra `sme-sim-common[mcp]`, official `mcp` SDK `>=2.3,<3`): an MCP
  server skeleton. `McpRegistry(name, version).register_tool(name, description, input_schema, handler)`
  (JSON schema dict or pydantic model; sync or async handler; `ToolError` / `bad()` / `ValueError` ... become
  MCP tool errors), `@registry.tool(...)`, `register_http_tool(name, description, method, path, ...)` (wraps
  one of the product's own routes, called in-process), `register_base_tools(registry, app)` (`get_version`,
  `get_state`, `export_config`, `set_simulation`), `mount(app, "/mcp", host=...)` (streamable HTTP on the
  product's own port, stateless, DNS-rebinding protection on loopback) and `run_stdio(app)`.
- `make_base_app`: `GET /healthz` (`{"status": "ok", "name", "version", "common_version"}`).
- `sme_sim_common.logs`: `setup_logging(verbose=, log_format="text"|"json")` and `JsonFormatter` (one JSON
  object per line). `add_common_args(..., log_format=True)` adds `--log-format {text,json}`; `run_web` passes
  uvicorn `log_config=None` for `json` so its logs use the same handler.
- PyInstaller hook: bundles `mcp` / `mcp_types` when the build environment has them.

## [1.2.1] - 2026-11-28

### Added
- README: "What belongs in common" (product first, promote later; hooks, not protocols).
- `make_base_app(..., max_import_bytes=MAX_IMPORT_BYTES)` (default 10 MiB): `POST /api/config/import` refuses a
  larger request body with 413 before parsing it (Content-Length checked first, the body stream is capped too).
- `XlsxSchema(..., max_rows=MAX_ROWS)` (default 50 000) and `Sheet(..., max_rows=None)` (per-sheet override):
  `read_sheet` stops at the cap and the import fails with `"<sheet>: more than N rows (row limit), import
  refused"`, so a crafted workbook cannot exhaust memory in read-only mode.

### Fixed
- `XlsxSchema.write` writes a text starting with `=`, `+`, `-`, `@`, `＠`, tab or CR (`FORMULA_PREFIXES`) as a
  literal string with a quote prefix. openpyxl stored `=...` as a formula, so such a value did not round-trip.
- `BaseEngine._run` waits with `asyncio.timeout` instead of `asyncio.wait_for`, which on Python 3.11 swallowed a
  cancel arriving together with a wake-up and kept the engine task running.

## [1.2.0] - 2026-11-26

### Added
- `config.replace_yaml_list_item(text, key, match_field, match_value, new_item)`: comment-preserving write-back
  of one item of a top-level YAML list. The item whose `match_field` equals `match_value` (compared as `str`)
  is replaced, appended when missing, or deleted with `new_item=None`; the other items keep their lines and
  comments. The result is read back and the whole block is rewritten when the layout is unusual (flow style,
  empty list, ...).
- README: SME OCPPSim registered in the port table (8082) and the accent table (amber).

## [1.1.0] - 2026-11-25

### Added
- `cli.add_validate_args` / `run_validate`: `validate` also accepts `-c/--config CONFIG` (the flag `run` uses).
  The positional `CONFIG` stays; giving neither, or both with different paths, is a usage error (exit 2).

### Fixed
- `behaviors.compile_expr` rejects a function used as a value (`pv > 3`, `max + 1`) and a value called as a
  function (`t(1)`, `pi(2)`) at compile time. These expressions passed `validate` before but raised on every tick.

## [1.0.0] - 2026-11-25

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
- `templates`: `TemplateRegistry(extra_keys=(...))` allows extra top-level keys in user templates (e.g. a scanned
  `identification`); `expand_extras` / `expand_device_extras` merge them with the device's own fields (non-empty
  device value wins, dicts merged shallowly) and `device_as_template` exports them.
