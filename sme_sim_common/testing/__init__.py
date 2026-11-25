"""Test helpers for products built on sme-sim-common.

The asyncio timeout fixture lives in :mod:`sme_sim_common.testing.plugin` and is activated automatically through
the ``pytest11`` entry point. :func:`check_i18n_keys` guards the reserved i18n namespaces.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, NamedTuple, Union

__all__ = ["RESERVED_PREFIXES", "I18nKey", "iter_i18n_keys", "check_i18n_keys"]

#: Key prefixes owned by sme-sim-common (shell.js / vendor.js / common.js); products must not define them.
RESERVED_PREFIXES = ("shell.", "vendor.", "common.")

_CALL = re.compile(r"""Shell\.addStrings\(\s*(["'])(\w+)\1\s*,\s*\{""")


class I18nKey(NamedTuple):
    lang: str
    key: str
    line: int


def _read_string(src: str, i: int) -> int:
    """``src[i]`` is a quote; return the index just past the closing quote."""
    q = src[i]
    i += 1
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == q:
            return i + 1
        i += 1
    return i


def iter_i18n_keys(path: Union[str, Path]) -> Iterator[I18nKey]:
    """Yield the keys defined by ``Shell.addStrings(lang, {...})`` calls in a JS file (top-level quoted keys
    of the object literal; string-aware, so ``{path}`` placeholders and braces in texts are ignored)."""
    src = Path(path).read_text(encoding="utf-8")
    for m in _CALL.finditer(src):
        lang, i, depth = m.group(2), m.end(), 1
        while i < len(src) and depth:
            c = src[i]
            if c in "\"'`":
                j = _read_string(src, i)
                if depth == 1 and c != "`":
                    k = j
                    while k < len(src) and src[k] in " \t\r\n":
                        k += 1
                    if k < len(src) and src[k] == ":":
                        yield I18nKey(lang, src[i + 1:j - 1], src.count("\n", 0, i) + 1)
                i = j
                continue
            if c == "/" and src.startswith("//", i):
                i = src.find("\n", i)
                i = len(src) if i < 0 else i
                continue
            if c == "/" and src.startswith("/*", i):
                i = src.find("*/", i)
                i = len(src) if i < 0 else i + 2
                continue
            if c in "{[(":
                depth += 1
            elif c in "}])":
                depth -= 1
            i += 1


def check_i18n_keys(static_dir: Union[str, Path]) -> list[str]:
    """Scan a product's ``i18n/*.js`` and ``app.js`` for strings in the reserved namespaces.

    Returns violations as ``"<file>:<line>: <lang> <key>"`` (empty list = OK). Typical product test::

        def test_i18n_namespaces():
            assert check_i18n_keys(STATIC) == []
    """
    d = Path(static_dir)
    files = sorted((d / "i18n").glob("*.js")) + ([d / "app.js"] if (d / "app.js").is_file() else [])
    out = []
    for f in files:
        rel = f.relative_to(d).as_posix()
        for k in iter_i18n_keys(f):
            if k.key.startswith(RESERVED_PREFIXES):
                out.append(f"{rel}:{k.line}: {k.lang} {k.key}")
    return out
