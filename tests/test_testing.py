import asyncio

from sme_sim_common.testing import check_i18n_keys, iter_i18n_keys

PRODUCT_EN = """\
"use strict";
const PRODUCT = { vendor: Shell.vendors.smartEdge };
Shell.addStrings("en", {
  "menu.proto": "Protocol {x}",   // comment with "common.fake": 1
  "status.text": "a: {b} } { ' \\" ",
  /* "shell.block": "in a comment" */
  "vendor.blurb": "product must not redefine this",
  nested: { "common.inner": "not top-level" },
});
"""

PRODUCT_JA = """\
Shell.addStrings('ja', {
  'menu.proto': 'プロトコル',
  "common.config.save": "保存",
});
"""


def test_iter_keys_is_string_aware(tmp_path):
    p = tmp_path / "app.js"
    p.write_text(PRODUCT_EN, encoding="utf-8")
    keys = [(k.lang, k.key, k.line) for k in iter_i18n_keys(p)]
    assert keys == [("en", "menu.proto", 4), ("en", "status.text", 5), ("en", "vendor.blurb", 7)]


def test_check_i18n_keys(tmp_path):
    (tmp_path / "i18n").mkdir()
    (tmp_path / "app.js").write_text(PRODUCT_EN, encoding="utf-8")
    (tmp_path / "i18n" / "ja.js").write_text(PRODUCT_JA, encoding="utf-8")
    assert check_i18n_keys(tmp_path) == ["i18n/ja.js:3: ja common.config.save", "app.js:7: en vendor.blurb"]


def test_check_i18n_keys_clean(tmp_path):
    (tmp_path / "i18n").mkdir()
    (tmp_path / "i18n" / "en.js").write_text('Shell.addStrings("en", { "menu.x": "X" });\n', encoding="utf-8")
    assert check_i18n_keys(tmp_path) == []
    assert check_i18n_keys(tmp_path / "missing") == []


def test_plugin_wraps_asyncio_run():
    assert asyncio.run.__name__ == "_run_with_timeout"

    async def main():
        await asyncio.sleep(0)
        return 42

    assert asyncio.run(main()) == 42
