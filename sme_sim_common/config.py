"""Config helpers shared by the simulators: strict pydantic base model, YAML / JSON loaders, atomic writes and
comment-preserving partial write-back of a top-level YAML block or of one item of a top-level YAML list.

Ported from sme-bac-sim v0.4.0 (config.py ``_Model`` / ``parse_text`` / ``load_file`` / ``dump_yaml``,
netsettings.py ``replace_yaml_block`` / ``write_network_section``) and sme-modbus-sim 085fe59 (config.py),
made generic over the product's config model.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, TypeVar, Union

import yaml
from pydantic import BaseModel, ConfigDict

__all__ = [
    "StrictModel",
    "parse_text",
    "load_file",
    "dump_yaml",
    "atomic_write_text",
    "splice_yaml_block",
    "replace_yaml_block",
    "replace_yaml_list_item",
]

M = TypeVar("M", bound=BaseModel)


class StrictModel(BaseModel):
    """Base for config models: unknown keys are errors, fields can be filled by name or alias."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def parse_text(text: str, model_cls: type[M], *, fmt: Literal["yaml", "json"] | None = "yaml") -> M:
    """Parse YAML or JSON text into ``model_cls`` (YAML is a superset of JSON; ``None`` means YAML)."""
    data = json.loads(text) if fmt == "json" else yaml.safe_load(text)
    return model_cls.model_validate(data or {})


def load_file(path: Union[str, Path], model_cls: type[M]) -> M:
    """Load a ``.json`` file as JSON and anything else as YAML."""
    p = Path(path)
    return parse_text(p.read_text(encoding="utf-8"), model_cls, fmt="json" if p.suffix.lower() == ".json" else "yaml")


def dump_yaml(obj: Union[BaseModel, dict]) -> str:
    """Dump a model (``exclude_none``) or a plain dict as block-style YAML, keeping key order and unicode."""
    data = obj.model_dump(exclude_none=True, exclude_defaults=False) if isinstance(obj, BaseModel) else obj
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def atomic_write_text(path: Union[str, Path], text: str, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically: temp file in the same directory, fsync, then ``os.replace``.

    Readers see either the old or the new content, never a truncated file. On Windows ``os.replace`` can fail
    transiently while another process (virus scanner, indexer, editor) holds the target open; it is retried briefly.
    """
    p = Path(path)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(10):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.05)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def splice_yaml_block(text: str, key: str, block: str) -> str:
    """Textually replace the top-level ``key:`` block of a YAML document (or insert it after the leading comments).

    Indented lines and comments inside the block are replaced; column-0 comments / blank lines right before the
    next top-level key are left to that key. No validation: see :func:`replace_yaml_block`."""
    if not block.endswith("\n"):
        block += "\n"
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(rf"{re.escape(key)}\s*:", ln)), None)
    if start is None:
        i = 0
        while i < len(lines) and (not lines[i].strip() or lines[i].startswith("#")):
            i += 1
        return "".join(lines[:i]) + block + ("\n" if i < len(lines) else "") + "".join(lines[i:])
    end = start + 1
    while end < len(lines) and not re.match(r"[^\s#]", lines[end]):
        end += 1
    if end < len(lines):  # keep the comment header of the next section
        while end - 1 > start and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
            end -= 1
    return "".join(lines[:start]) + block + "".join(lines[end:])


def replace_yaml_block(text: str, key: str, new_value: Any) -> str:
    """Return ``text`` with the top-level ``key`` set to ``new_value``, keeping comments elsewhere.

    The spliced document is read back and compared with the expected mapping; if the layout is unusual
    (anchors, flow style at top level, ...) the whole document is re-dumped instead (comments are then lost).
    Raises ``ValueError`` if ``text`` is not a YAML mapping. Write the result with :func:`atomic_write_text`.
    """
    old = yaml.safe_load(text) if text.strip() else {}
    if old is None:
        old = {}
    if not isinstance(old, dict):
        raise ValueError(f"not a YAML mapping (top level is {type(old).__name__})")
    block = yaml.safe_dump({key: new_value}, allow_unicode=True, sort_keys=False)
    want = {**old, key: yaml.safe_load(block)[key]}
    new = splice_yaml_block(text, key, block)
    try:
        ok = yaml.safe_load(new) == want
    except yaml.YAMLError:
        ok = False
    if not ok:
        new = yaml.safe_dump(want, allow_unicode=True, sort_keys=False)
    return new


_MISSING = object()


def replace_yaml_list_item(text: str, key: str, match_field: str, match_value: Any, new_item: Any) -> str:
    """Return ``text`` with one item of the top-level list ``key`` replaced, appended or deleted.

    The item is the first mapping whose ``match_field`` equals ``match_value`` compared as ``str`` (so the
    id ``"0123"`` matches ``"0123"`` and ``123`` matches ``"123"``). ``new_item`` replaces it, or is appended at
    the end of the list when no item matches; ``new_item=None`` deletes it (no match: ``text`` is returned
    unchanged). Only the lines of that item change: the other items, their comments and the comment lines
    right above the replaced item stay as written (a deleted item takes the comment lines right above it along).

    As in :func:`replace_yaml_block` the result is read back and compared with the expected document; if the
    layout is unusual (flow style, anchors, an empty list, ...) the whole ``key`` block is rewritten instead.
    Raises ``ValueError`` if ``text`` is not a YAML mapping or ``key`` is not a list.
    """
    old = yaml.safe_load(text) if text.strip() else {}
    if old is None:
        old = {}
    if not isinstance(old, dict):
        raise ValueError(f"not a YAML mapping (top level is {type(old).__name__})")
    items = old.get(key)
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError(f"{key!r} is not a YAML list (it is {type(items).__name__})")
    idx = next(
        (i for i, it in enumerate(items) if isinstance(it, dict) and str(it.get(match_field, _MISSING)) == str(match_value)),
        None,
    )
    if new_item is None and idx is None:
        return text
    item_text = "" if new_item is None else yaml.safe_dump([new_item], allow_unicode=True, sort_keys=False)
    want_items = list(items)
    if new_item is None:
        del want_items[idx]
    elif idx is None:
        want_items.append(yaml.safe_load(item_text)[0])
    else:
        want_items[idx] = yaml.safe_load(item_text)[0]

    new = _splice_list_item(text, key, idx, len(items), item_text)
    if new is not None:
        try:
            ok = yaml.safe_load(new) == {**old, key: want_items}
        except yaml.YAMLError:
            ok = False
        if ok:
            return new
    return replace_yaml_block(text, key, want_items)


def _splice_list_item(text: str, key: str, idx: int | None, count: int, item_text: str) -> str | None:
    """Textual part of :func:`replace_yaml_list_item`; ``None`` when the block-style item lines are not found."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(rf"{re.escape(key)}\s*:", ln)), None)
    if start is None or count == 0:
        return None
    end = start + 1  # a column-0 "- " item still belongs to the block
    while end < len(lines) and not (re.match(r"[^\s#-]", lines[end]) or re.match(r"-\S", lines[end])):
        end += 1
    first = next((m for m in (re.match(r"( *)-(\s|$)", ln) for ln in lines[start + 1 : end]) if m), None)
    if first is None:
        return None
    indent = first.group(1)
    dashes = [i for i in range(start + 1, end) if re.match(rf"{indent}-(\s|$)", lines[i])]
    if len(dashes) != count:
        return None

    def is_gap(ln: str) -> bool:
        return not ln.strip() or ln.lstrip().startswith("#")

    def item_end(k: int) -> int:  # trailing blank / comment lines go with the next item (or stay in place)
        e = dashes[k + 1] if k + 1 < len(dashes) else end
        while e - 1 > dashes[k] and is_gap(lines[e - 1]):
            e -= 1
        return e

    block = "".join(indent + ln if ln.strip() else ln for ln in item_text.splitlines(keepends=True))
    if idx is None:  # append after the last item
        at = item_end(len(dashes) - 1)
        return "".join(lines[:at]) + block + "".join(lines[at:])
    lo, hi = dashes[idx], item_end(idx)
    if not item_text:  # delete, together with the comment lines right above the item
        while lo - 1 > start and lines[lo - 1].startswith(indent + "#"):
            lo -= 1
    return "".join(lines[:lo]) + block + "".join(lines[hi:])
