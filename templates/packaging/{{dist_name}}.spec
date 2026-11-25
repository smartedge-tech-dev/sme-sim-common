# PyInstaller spec (onefile). Build from the repo root:
#   pyinstaller packaging/{{dist_name}}.spec --noconfirm
# SPECPATH is the directory of this spec file (packaging/).
#
# sme-sim-common ships a PyInstaller hook (pyinstaller40 entry point) that collects its own static
# files (shell / vendor / common i18n) and the uvicorn / multipart / yaml / websockets hidden imports.
# Do NOT list those here. Only add what belongs to this product.
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files  # noqa: F401

root = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    # Product static files (index.html, app.js, style.css, i18n/, favicon) are still collected here.
    (os.path.join(root, "{{import_name}}", "static"), "{{import_name}}/static"),
    # Optional demo config, if __main__ resolves configs/ relative to the package's parent directory:
    # (os.path.join(root, "configs", "demo.yaml"), "configs"),
]
# Protocol library data files, if any, e.g.:
# datas += collect_data_files("bacpypes3")

hiddenimports = [
    # Protocol library submodules imported dynamically, if any, e.g.:
    # *collect_submodules("bacpypes3"),
]

a = Analysis(
    [os.path.join(root, "packaging", "entry.py")],
    pathex=[root],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="{{dist_name}}",
    console=True,
    upx=False,
)
