"""Config helpers shared by the simulators: strict pydantic base model, YAML / JSON loaders, atomic writes and
comment-preserving partial write-back of a top-level YAML block.

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
