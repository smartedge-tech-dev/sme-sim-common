# PyInstaller spec (onefile) for the sme-sim-common smoke app. Build from the repo root:
#   pyinstaller tests/pyinstaller_smoke/smoke.spec --noconfirm
# Deliberately no hiddenimports / datas: the hook shipped with sme-sim-common must supply them.
import os

a = Analysis(
    [os.path.join(SPECPATH, "smoke_app.py")],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="sme-sim-common-smoke",
    console=True,
    upx=False,
)
