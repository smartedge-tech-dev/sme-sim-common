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

# MCP support (sme-sim-common[mcp]) is optional: bundle the SDK only when the product's build env has it.
try:
    import mcp  # noqa: F401
except ImportError:
    pass
else:
    from PyInstaller.utils.hooks import copy_metadata

    # mcp.cli needs the optional typer; products never run it.
    hiddenimports += collect_submodules("mcp", filter=lambda n: not n.startswith("mcp.cli")) + collect_submodules(
        "mcp_types")
    datas += copy_metadata("mcp") + copy_metadata("mcp-types")
