import re
from collections import defaultdict

from sme_sim_common import __version__
from sme_sim_common.testing import iter_i18n_keys
from sme_sim_common.web import STATIC_DIR

SHELL_JS = (STATIC_DIR / "shell" / "shell.js").read_text(encoding="utf-8")


def _keys_by_lang(path):
    out = defaultdict(set)
    for k in iter_i18n_keys(path):
        out[k.lang].add(k.key)
    return out


def test_shell_is_vendor_neutral():
    assert "shell.vendor." not in SHELL_JS
    assert '"shell.help.custom":' not in SHELL_JS
    shell = _keys_by_lang(STATIC_DIR / "shell" / "shell.js")
    assert shell == {}  # shell.js uses I18N.xx = Object.assign(...), not Shell.addStrings


def test_vendor_strings_complete():
    keys = _keys_by_lang(STATIC_DIR / "vendor" / "vendor.js")
    assert set(keys) == {"en", "ja", "zh"}
    assert keys["en"] == keys["ja"] == keys["zh"]
    assert all(k.startswith("vendor.") for k in keys["en"])
    used = set(re.findall(r'\bt\("(vendor\.[\w.]+)"', SHELL_JS)) | {"vendor.help.custom"}
    assert used <= keys["en"]
    vendor_js = (STATIC_DIR / "vendor" / "vendor.js").read_text(encoding="utf-8")
    assert 'logoUrl: "/sme-sim-common/brand/company-logo.svg"' in vendor_js
    for svc in re.findall(r'"(vendor\.svc\.\w+)"', vendor_js):
        assert svc in keys["en"]


def test_common_strings_complete():
    keys = _keys_by_lang(STATIC_DIR / "i18n" / "common.js")
    assert set(keys) == {"en", "ja", "zh"}
    assert keys["en"] == keys["ja"] == keys["zh"]
    assert all(k.startswith("common.") for k in keys["en"])


def _tokens(block):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))


def test_dark_token_blocks_in_sync():
    css = (STATIC_DIR / "shell" / "shell.css").read_text(encoding="utf-8")
    explicit = re.search(r':root\[data-theme="dark"\]\s*\{(.*?)\}', css, re.S).group(1)
    media = re.search(r':root:not\(\[data-theme="light"\]\)\s*\{(.*?)\}', css, re.S).group(1)
    assert _tokens(explicit) == _tokens(media)
    light = re.search(r"^:root\s*\{(.*?)\}", css, re.S | re.M).group(1)
    assert _tokens(light)["--vendor-accent"] == "#087def"
    assert "--vendor-accent" in _tokens(explicit)


def test_version_and_provenance():
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+|rc\d+)?", __version__)
    for rel in ("shell/shell.js", "shell/shell.css", "brand/company-logo.svg"):
        head = (STATIC_DIR / rel).read_text(encoding="utf-8").splitlines()[0]
        assert "sme-bac-sim v0.4.0" in head and "d8382883" in head, rel
    assert "version: COMMON_VERSION" in SHELL_JS
    assert 'cfg.copyright || "shell.footer.copyright"' in SHELL_JS
