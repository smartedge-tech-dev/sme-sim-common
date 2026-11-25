"""PyInstaller integration (``pyinstaller40`` entry point): products bundling sme-sim-common get its static
assets and the uvicorn / multipart hidden imports without listing them in their spec."""

import os


def get_hook_dirs():
    return [os.path.dirname(__file__)]
