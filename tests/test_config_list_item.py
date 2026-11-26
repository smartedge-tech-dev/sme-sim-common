import pytest
import yaml

from sme_sim_common.config import replace_yaml_list_item

CHARGERS = """\
# site config
title: demo
# the chargers
chargers:
  # first one, near the gate
  - id: "0123"
    power: 7   # kW
  # second one
  - id: "0124"
    power: 11  # was 22
    # note inside the second one
    vendor: acme
  # third one
  - id: "0125"
    power: 22  # fast
# after
network:
  port: 1
"""


def _ids(text):
    return [c["id"] for c in yaml.safe_load(text)["chargers"]]


def test_replace_middle_keeps_other_comments():
    new = replace_yaml_list_item(CHARGERS, "chargers", "id", "0124", {"id": "0124", "power": 50})
    for kept in ("# site config", "# the chargers", "# first one, near the gate", "# kW", "# second one",
                 "# third one", "# fast", "# after"):
        assert kept in new, kept
    assert "# was 22" not in new and "# note inside the second one" not in new
    doc = yaml.safe_load(new)
    assert doc["chargers"][1] == {"id": "0124", "power": 50}
    assert _ids(new) == ["0123", "0124", "0125"]  # ids stay strings
    assert doc["network"] == {"port": 1} and doc["title"] == "demo"


def test_match_is_by_str():
    text = "items:\n  - id: 1\n    v: a  # keep\n  - id: 2\n    v: b\n"
    new = replace_yaml_list_item(text, "items", "id", "2", {"id": 2, "v": "c"})
    assert "# keep" in new
    assert yaml.safe_load(new) == {"items": [{"id": 1, "v": "a"}, {"id": 2, "v": "c"}]}


def test_append():
    new = replace_yaml_list_item(CHARGERS, "chargers", "id", "0200", {"id": "0200", "power": 3})
    assert "# fast" in new and "# after" in new and "# second one" in new and "# was 22" in new
    assert _ids(new) == ["0123", "0124", "0125", "0200"]
    assert new.index("0200") < new.index("# after")


def test_delete():
    new = replace_yaml_list_item(CHARGERS, "chargers", "id", "0124", None)
    assert _ids(new) == ["0123", "0125"]
    assert "# second one" not in new and "# was 22" not in new
    assert "# first one, near the gate" in new and "# third one" in new and "# kW" in new
    first = replace_yaml_list_item(CHARGERS, "chargers", "id", "0123", None)
    assert _ids(first) == ["0124", "0125"]
    assert "# the chargers" in first and "near the gate" not in first
    assert replace_yaml_list_item(CHARGERS, "chargers", "id", "nope", None) == CHARGERS


def test_column0_dashes():
    text = "items:\n- id: a  # keep a\n- id: b\n  v: 1\nother: x\n"
    new = replace_yaml_list_item(text, "items", "id", "b", {"id": "b", "v": 2})
    assert "# keep a" in new
    assert yaml.safe_load(new) == {"items": [{"id": "a"}, {"id": "b", "v": 2}], "other": "x"}


def test_falls_back_to_block_rewrite():
    flow = "# top\nitems: [{id: a, v: 1}, {id: b, v: 2}]  # flow\nother: x\n"
    new = replace_yaml_list_item(flow, "items", "id", "b", {"id": "b", "v": 3})
    assert new.startswith("# top\n")
    assert yaml.safe_load(new) == {"items": [{"id": "a", "v": 1}, {"id": "b", "v": 3}], "other": "x"}
    # missing key, empty list, deleting the last item
    assert yaml.safe_load(replace_yaml_list_item("t: 1\n", "items", "id", "a", {"id": "a"})) == {
        "t": 1, "items": [{"id": "a"}]}
    assert yaml.safe_load(replace_yaml_list_item("items: []\n", "items", "id", "a", {"id": "a"})) == {
        "items": [{"id": "a"}]}
    assert yaml.safe_load(replace_yaml_list_item("items:\n  - id: a\n", "items", "id", "a", None)) == {"items": []}


def test_rejects_non_list():
    with pytest.raises(ValueError):
        replace_yaml_list_item("items:\n  a: 1\n", "items", "id", "a", {"id": "a"})
    with pytest.raises(ValueError):
        replace_yaml_list_item("- a\n", "items", "id", "a", {"id": "a"})
