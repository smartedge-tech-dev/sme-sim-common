# sme-sim-common

**English** | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

Shared runtime for the smart-edge simulator series (SME BACnetSim, SME ModbusSim, the OCPP simulator,
SME SerialHub): the web shell (header, menus, theme, languages, About), vendor texts, the `common.*`
UI strings, and the protocol-independent Python layer (web helpers, config I/O, behaviors, device
templates, test helpers, PyInstaller hook). The `templates/` directory holds the build-time skeleton
(CI, release, packaging, docs, page) that products copy by hand; it is not part of the wheel.

MIT-licensed, developed by [smart-edge (智届科技)](https://smartedge-tech.com).

## Install

```bash
pip install "sme-sim-common>=1.0,<2"          # in a product's pyproject.toml dependencies
pip install "sme-sim-common[xlsx]>=1.0,<2"    # with the .xlsx import / export helpers (openpyxl)
pip install -e ../sme-sim-common              # local development against a checkout
```

Python 3.11 or newer.

## Using it in a product

### Mount the common static files

```python
from fastapi import FastAPI
from sme_sim_common.web import mount_common, mount_product_static

app = FastAPI()
mount_common(app)                          # serves /sme-sim-common/{shell,vendor,i18n,brand}/...
mount_product_static(app, STATIC_DIR)      # the product's own /static (skipped if the directory is missing)
```

The common files live under their own prefix `/sme-sim-common`, never under `/static`: Starlette matches
mounts in registration order, so a nested path would be swallowed by the product's `/static` mount.

### Minimal app

```python
import argparse
from pathlib import Path

from sme_sim_common.cli import add_common_args, run_web
from sme_sim_common.web import make_base_app

ap = add_common_args(argparse.ArgumentParser(), default_http_port=8080, app_name="sme-my-sim")
args = ap.parse_args()
engine = MyEngine(...)                     # follows sme_sim_common.engine.EngineProtocol (or subclass BaseEngine)
app = make_base_app(engine, config_path=args.config, static_dir=Path(__file__).parent / "static")
run_web(app, args)                         # uvicorn on args.host / args.http_port, opens the browser
```

### Page skeleton

Start from `templates/static/index.html`. The load order is fixed:

1. `/sme-sim-common/shell/shell.css` then the product `/static/style.css`
2. `/sme-sim-common/shell/shell.js` in `<head>` with `data-storage="<dist name>"` (localStorage prefix;
   the stored theme is applied before first paint)
3. `/sme-sim-common/vendor/vendor.js`, then `/sme-sim-common/i18n/common.js`
4. the product dictionaries `/static/i18n/en.js`, `ja.js`, `zh.js`, then `/static/app.js`

The common assets carry a `?v=` version query so browsers do not keep stale shell files after an upgrade;
`Shell.version` reports the sme-sim-common version and the About dialog shows it.

### Vendor

`vendor/vendor.js` registers the company preset `Shell.vendors.smartEdge` and the `vendor.*` strings.
Products pass it explicitly:

```js
Shell.init({ ...PRODUCT, vendor: Shell.vendors.smartEdge });
```

Company texts are maintained only here, so a change reaches every product with the next common release.

### i18n prefixes

| Prefix | Owner |
|---|---|
| `shell.*` | sme-sim-common: UI framework (menus, theme, language, help, About) — `shell.js` |
| `vendor.*` | sme-sim-common: company texts — `vendor/vendor.js` |
| `common.*` | sme-sim-common: features provided by the common layer — `i18n/common.js` |
| anything else | the product — `static/i18n/{en,ja,zh}.js` |

Products must not define the three reserved prefixes. Guard it in the product tests:

```python
from sme_sim_common.testing import check_i18n_keys

def test_no_reserved_i18n_keys():
    check_i18n_keys(STATIC_DIR)
```

`common.*` keys are named after the feature, not the menu position, and must be unambiguous in every
product of the series (e.g. `common.backend.connected`, not `ws.on`).

### Accent color

Each product has its own accent color. `shell.css` defaults to the brand blue `#087def`; a product
overrides `--accent`, `--accent-ink` and `--accent-weak` in three blocks of its `style.css`
(`:root`, `:root[data-theme="dark"]` and the `prefers-color-scheme: dark` block) — see
`templates/static/style.css`. The vendor area uses `--vendor-accent` (always brand blue) and must not be
overridden.

### Tests and packaging

- The pytest plugin (asyncio timeout + hang dump) is activated automatically through the `pytest11`
  entry point.
- The PyInstaller hook (`pyinstaller40` entry point) collects the common static files and the uvicorn
  hidden imports, so product spec files list only their own files.

## Series port table

Default web UI ports, so that sibling products can run side by side. New products register here first.

| Product | Default HTTP port |
|---|---|
| SME BACnetSim | 8080 |
| SME ModbusSim | 8081 |
| OCPP simulator | TBD |
| SME SerialHub | TBD |

## Series accent table

| Product | `--accent` | `--accent-ink` | `--accent-weak` | Dark theme |
|---|---|---|---|---|
| SME BACnetSim | `#087def` (brand blue, shell default) | `#fff` | `#e7f2fe` | shell default (`#3d9bff` / `#fff` / `#11304f`) |
| SME ModbusSim | `#0f766e` (teal) | `#ffffff` | `#ccfbf1` | TBD |
| OCPP simulator | TBD | TBD | TBD | TBD |
| SME SerialHub | TBD | TBD | TBD | TBD |

## Versioning

- Semantic Versioning, first release `1.0.0`. Within 1.x only backward-compatible additions (new keys,
  new optional parameters, new modules) and fixes; a breaking change would be 2.0 and is avoided.
- Products depend on `sme-sim-common>=1.0,<2`.
- The single version source is `sme_sim_common.__version__`; `Shell.version` carries the same value.

## Templates

See [`templates/CHECKLIST.md`](templates/CHECKLIST.md) for adopting the templates in a new or migrated
product (placeholders, port / accent registration, i18n rules, PyInstaller, PyPI trusted publishing).

## Releasing sme-sim-common

1. Update `__version__` and the `CHANGELOG.md` section `## [x.y.z] - YYYY-MM-DD`.
2. Push the tag `vx.y.z`. `.github/workflows/release.yml` builds the sdist and wheel, checks them with
   `twine`, publishes to PyPI with trusted publishing (environment `pypi`) and creates the GitHub Release
   with the CHANGELOG section as notes. The workflow file name `release.yml` and the environment name
   `pypi` are registered on PyPI; do not rename them.

## License

MIT — see [LICENSE](LICENSE).
