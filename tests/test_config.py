import json
import os

import pytest
import yaml
from pydantic import ValidationError

from sme_sim_common.config import (
    StrictModel,
    atomic_write_text,
    dump_yaml,
    load_file,
    parse_text,
    replace_yaml_block,
    splice_yaml_block,
)


class Net(StrictModel):
    port: int = 47808
    name: str = "eth0"


class Cfg(StrictModel):
    title: str = "demo"
    network: Net = Net()
    devices: list[str] = []


def test_yaml_round_trip():
    cfg = parse_text("title: 日本語\nnetwork: {port: 1}\ndevices: [a, b]\n", Cfg)
    assert cfg.network.port == 1
    again = parse_text(dump_yaml(cfg), Cfg)
    assert again == cfg
    assert "日本語" in dump_yaml(cfg)  # allow_unicode
    assert dump_yaml(cfg).index("title") < dump_yaml(cfg).index("network")  # sort_keys=False


def test_json_and_empty():
    assert parse_text('{"title": "x"}', Cfg, fmt="json").title == "x"
    assert parse_text("", Cfg) == Cfg()
    assert dump_yaml({"b": 1, "a": 2}) == "b: 1\na: 2\n"


def test_extra_forbidden():
    with pytest.raises(ValidationError):
        parse_text("title: x\nbogus: 1\n", Cfg)


def test_load_file_by_suffix(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps({"title": "j"}), encoding="utf-8")
    (tmp_path / "c.yaml").write_text("title: y\n", encoding="utf-8")
    assert load_file(tmp_path / "c.json", Cfg).title == "j"
    assert load_file(tmp_path / "c.yaml", Cfg).title == "y"


def test_atomic_write(tmp_path):
    p = tmp_path / "out.yaml"
    atomic_write_text(p, "a: 1\n")
    atomic_write_text(p, "a: 2\r\n日本\n")
    assert p.read_bytes().decode("utf-8") == "a: 2\r\n日本\n"  # no newline translation
    assert [f.name for f in tmp_path.iterdir()] == ["out.yaml"]  # temp file gone


def test_atomic_write_failure_keeps_old(tmp_path, monkeypatch):
    p = tmp_path / "out.yaml"
    p.write_text("old\n", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(p, "new\n")
    assert p.read_text(encoding="utf-8") == "old\n"
    assert [f.name for f in tmp_path.iterdir()] == ["out.yaml"]


DOC = """\
# header comment
title: demo   # inline
# network section
network:
  port: 1    # old port
  name: eth0

# devices follow
devices:
  - a
"""


def test_replace_keeps_comments():
    new = replace_yaml_block(DOC, "network", {"port": 2, "name": "eth1"})
    assert "# header comment" in new and "# inline" in new and "# devices follow" in new
    assert "# network section" in new
    assert "# old port" not in new
    assert yaml.safe_load(new) == {"title": "demo", "network": {"port": 2, "name": "eth1"}, "devices": ["a"]}


def test_replace_inserts_missing_key():
    new = replace_yaml_block("# top\ntitle: x\n", "network", {"port": 3})
    assert new.startswith("# top\nnetwork:\n")
    assert yaml.safe_load(new) == {"title": "x", "network": {"port": 3}}
    assert yaml.safe_load(replace_yaml_block("", "network", {"port": 3})) == {"network": {"port": 3}}


def test_replace_falls_back_to_full_rewrite():
    # flow-style top level: the textual splice cannot work, the self-check catches it
    text = "{title: x, network: {port: 1}}  # flow\n"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(splice_yaml_block(text, "network", "network:\n  port: 2\n"))
    new = replace_yaml_block(text, "network", {"port": 2})
    assert yaml.safe_load(new) == {"title": "x", "network": {"port": 2}}


def test_replace_rejects_non_mapping():
    with pytest.raises(ValueError):
        replace_yaml_block("- a\n- b\n", "network", {})
