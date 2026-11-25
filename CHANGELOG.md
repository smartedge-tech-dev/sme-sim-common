# Changelog

All notable changes to sme-sim-common are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - YYYY-MM-DD

First release. The API below is the 1.x compatibility promise.

### Added
- Web shell (`shell.js` / `shell.css`, from SME BACnetSim 0.4.0): header, menu bar, status area, footer,
  About dialog with the common library version, toasts, system / light / dark theme, i18n helper.
  Served under `/sme-sim-common` by `mount_common()`.
- Vendor preset `Shell.vendors.smartEdge` and `vendor.*` strings; `--vendor-accent` token so the vendor
  area keeps the brand blue while each product overrides `--accent` / `--accent-ink` / `--accent-weak`.
- `common.*` strings (en / ja / zh) for the features provided by the common layer.
- Python helpers: web (`mount_common`, `mount_product_static`, `bad`), config I/O, behaviors, device
  templates, xlsx helpers (`[xlsx]` extra), CLI helpers, engine protocol.
- Test helpers: pytest plugin (asyncio timeout + hang dump) and `check_i18n_keys` for the reserved
  `shell.*` / `vendor.*` / `common.*` prefixes.
- PyInstaller hook that collects the common static files and the uvicorn hidden imports.
- `templates/`: CI, docs, release (Windows exe, PyPI trusted publishing, optional Docker), PyInstaller spec,
  mkdocs, pyproject, page / style / i18n skeletons, LICENSE, CHANGELOG, README and the adoption checklist.
