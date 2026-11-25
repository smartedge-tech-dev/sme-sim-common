# New product / migration checklist

Templates in this directory are copied **by hand** into a product repository (they are not part of the
`sme-sim-common` wheel). Work through every item; tick them in the product's task file.

## 1. Copy and replace placeholders

| Template path | Product path |
|---|---|
| `.github/workflows/{ci,docs,release}.yml` | same |
| `packaging/{{dist_name}}.spec`, `packaging/entry.py` | `packaging/<dist_name>.spec`, `packaging/entry.py` |
| `mkdocs.yml`, `requirements-docs.txt`, `docs/{en,ja,zh}/` | same |
| `pyproject.toml`, `LICENSE`, `CHANGELOG.md`, `README*.md` | same |
| `static/index.html`, `static/style.css`, `static/i18n/*.js` | `<import_name>/static/...` |

Placeholders (replace all of them, then `grep -rn "{{" .` must find nothing except the
`{{version}}` of docker/metadata-action in the optional, commented-out docker block of `release.yml`):

| Placeholder | Example |
|---|---|
| `{{dist_name}}` | `sme-modbus-sim` (PyPI name, exe name, localStorage prefix, repo name) |
| `{{import_name}}` | `sme_modbus_sim` |
| `{{display_name}}` | `SME ModbusSim` |
| `{{description}}` / `{{description_ja}}` / `{{description_zh}}` | one-line description per language |
| `{{default_http_port}}` | `8081` (from the port table) |
| `{{accent}}` / `{{accent_ink}}` / `{{accent_weak}}` | light accent tokens |
| `{{accent_dark}}` / `{{accent_ink_dark}}` / `{{accent_weak_dark}}` | dark accent tokens |

- [ ] Placeholders replaced; file `packaging/{{dist_name}}.spec` renamed.
- [ ] `__version__` defined in `<import_name>/__init__.py` (pyproject reads it).
- [ ] `<import_name>/__main__.py` exposes `main()` (used by `entry.py` and `[project.scripts]`).
- [ ] `static/app.js` written; it calls
      `Shell.init({...PRODUCT, vendor: Shell.vendors.smartEdge})` (vendor preset from `vendor/vendor.js`).

## 2. Register the product in the sme-sim-common README

- [ ] **Port table**: pick a default web port not used by a sibling product, add the row (all three READMEs).
- [ ] **Accent table**: add light (and, once decided, dark) `--accent` / `--accent-ink` / `--accent-weak`.
      Check contrast of `--accent-ink` on `--accent` (buttons) in both themes.
- [ ] Never override `--vendor-accent`: the vendor area keeps the brand blue in every product.

## 3. Web page and i18n

- [ ] `index.html` keeps the load order: `shell.css` → product `style.css` → `shell.js` (in `<head>`,
      `data-storage="<dist_name>"`) → `vendor/vendor.js` → `i18n/common.js` → product `i18n/en|ja|zh.js` → `app.js`.
- [ ] The common assets carry `?v=__SME_SIM_COMMON_VERSION__` (replaced with the sme-sim-common version when
      `GET /` is served) so browsers do not keep stale shell files after an upgrade.
- [ ] The app mounts the common files with `mount_common(app)` **before** its own `/static` mount
      (prefix `/sme-sim-common`, never nested under `/static`).
- [ ] Product strings live in `static/i18n/{en,ja,zh}.js` (not inline in `app.js`).
- [ ] The prefixes `shell.*`, `vendor.*` and `common.*` are reserved for sme-sim-common. Products must not
      define them. Add a test:

      ```python
      from pathlib import Path
      from sme_sim_common.testing import check_i18n_keys

      def test_no_reserved_i18n_keys():
          check_i18n_keys(Path(__file__).parents[1] / "<import_name>" / "static")
      ```
- [ ] Features provided by sme-sim-common use the `common.*` keys (e.g. `common.config.save`); do not
      copy them into product dictionaries.

## 4. Packaging

- [ ] The spec lists only product files: product `static/`, demo configs, protocol library data / hidden
      imports. Shell static files and uvicorn / multipart / yaml / websockets hidden imports come from the
      sme-sim-common PyInstaller hook automatically.
- [ ] `pyinstaller packaging/<dist_name>.spec --noconfirm` → run `dist/<dist_name>.exe`, open the UI, check
      the header, About dialog (shows the common library version), theme and the three languages.

## 5. Release / PyPI trusted publishing

- [ ] `CHANGELOG.md` has a `## [x.y.z] - YYYY-MM-DD` section for every tag `vx.y.z` (release.yml copies it
      into the GitHub Release notes; without it GitHub-generated notes are used).
- [ ] sme-sim-common itself must already be on PyPI in a matching version before the product is
      published to PyPI (a PyPI package cannot depend on a git URL or a local path).
- [ ] Trusted publishing only works when **all four** match exactly what is registered on PyPI:
      owner `smartedge-tech-dev`, repository `<dist_name>`, workflow file name `release.yml`,
      environment `pypi`. Do not rename the workflow file or the environment.
- [ ] For a project that does not exist on PyPI yet, add a **pending publisher**:
      PyPI → Your account → Publishing → "Add a new pending publisher" → GitHub, with PyPI project name
      `<dist_name>`, owner, repository, workflow `release.yml`, environment `pypi`. The first successful
      upload creates the project.
- [ ] GitHub → repository Settings → Environments → create `pypi` (optionally restrict it to `v*` tags
      and require a reviewer).
- [ ] If the product is not published to PyPI (yet), delete the `pypi` job from `release.yml` rather than
      letting the tag build fail.
- [ ] Docker: uncomment the optional `docker` block only for products that ship an image (needs a
      `Dockerfile`). SME SerialHub does not ship a Docker image.

## 6. Docs

- [ ] `docs/en|ja|zh/` contain the same file names; `mkdocs build --strict` passes.
- [ ] GitHub → Settings → Pages → Source: GitHub Actions.
