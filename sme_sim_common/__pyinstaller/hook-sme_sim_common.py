# PyInstaller hook for sme_sim_common (found through the pyinstaller40 "hook-dirs" entry point).
# Mirrors what sme-bac-sim v0.4.0 packaging/sme-bacnet-sim.spec listed by hand for the web stack.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("sme_sim_common", includes=["static/**/*"])

hiddenimports = collect_submodules("uvicorn") + [
    "multipart",
    "python_multipart",
    "yaml",
    "h11",
    "websockets",
    "httptools",
]
