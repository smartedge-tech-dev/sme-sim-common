"""Template mechanism (ported from sme-modbus-sim tests/test_templates.py @ 085fe59, protocol-free).

The item / device models here are tiny stand-ins; the Modbus-like hooks (address allocation per table,
overlap check, "needs a table") and the BACnet-like hook (instance numbers per object type) show that
the protocol-specific parts plug in through ``finalize_hook`` / ``validate_hook`` / ``export_hook``.
"""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sme_sim_common.templates import NAME_RE, TemplateRegistry, env_var_for, escape_braces, substitute


class Pt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    description: Optional[str] = None
    table: Optional[Literal["holding", "input", "coil"]] = None
    address: Optional[int] = Field(default=None, ge=0)
    size: int = 1
    access: Literal["r", "rw"] = "r"
    value: Any = None
    max: Optional[float] = None
    order: str = "big"
    behavior: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _ro_coil(self):
        if self.table == "input" and self.access == "rw":
            raise ValueError("input points are read-only")
        return self


class Dev(BaseModel):
    name: str
    template: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    points: List[Pt] = Field(default_factory=list)
    removed: Optional[List[str]] = None
    order: str = "big"


def allocate(owner: str, pts: List[Pt]) -> List[Pt]:
    nxt: Dict[str, int] = {}
    for p in pts:
        if p.address is not None:
            nxt[p.table] = max(nxt.get(p.table, 0), p.address + p.size)
    out = []
    for p in pts:
        if p.address is None:
            a = nxt.get(p.table, 0)
            p = p.model_copy(update={"address": a})
            nxt[p.table] = a + p.size
        out.append(p)
    return out


def check(owner: str, pts: List[Pt]) -> None:
    missing = [p.name for p in pts if p.table is None]
    if missing:
        raise ValueError(f"{owner}: points {missing} need a table")
    used: Dict[tuple, str] = {}
    for p in pts:
        for a in range(p.address, p.address + p.size):
            if (p.table, a) in used:
                raise ValueError(f"{owner}/{p.name}: {p.table} {a} overlaps {used[(p.table, a)]}")
            used[(p.table, a)] = p.name


def export(dev: Dev, d: Dict[str, Any]) -> Dict[str, Any]:
    if dev.order != "big" and "order" not in d:
        d["order"] = dev.order
    return d


def make_registry() -> TemplateRegistry:
    reg = TemplateRegistry(Pt, check, app_name="sme-test-sim", finalize_hook=allocate, export_hook=export)

    @reg.template("meter", "Power meter", {"rated_kw": 10})
    def _meter(p):
        return [{"name": "power", "table": "input", "max": p["rated_kw"],
                 "behavior": {"type": "sine", "max": p["rated_kw"]}},
                {"name": "frequency", "table": "input", "value": 50},
                {"name": "energy", "table": "input", "size": 2,
                 "behavior": {"type": "counter", "rate": "power / 3600"}},
                {"name": "serial", "table": "holding", "size": 4, "value": "{literal}"}]

    @reg.template("custom", "Empty device", {}, description="define points yourself")
    def _custom(p):
        return []

    return reg


@pytest.fixture()
def reg():
    return make_registry()


def _dev(**kw) -> Dev:
    return Dev.model_validate({"name": "D", **kw})


def test_catalog_and_get(reg):
    cat = reg.catalog()
    assert [t["name"] for t in cat] == ["meter", "custom"]
    assert cat[0] == {"name": "meter", "title": "Power meter", "params": {"rated_kw": 10}, "source": "builtin"}
    assert cat[1]["description"] == "define points yourself" and "path" not in cat[1]
    assert reg.get("meter")["title"] == "Power meter" and reg.get("nope") is None


def test_params_merge_and_allocation(reg):
    pts = {p.name: p for p in reg.expand_device(_dev(template="meter", params={"rated_kw": 100}))}
    assert pts["power"].max == 100 and pts["power"].behavior["max"] == 100
    assert [pts[n].address for n in ("power", "frequency", "energy")] == [0, 1, 2]
    assert (pts["serial"].table, pts["serial"].address, pts["serial"].value) == ("holding", 0, "{literal}")


def test_override_add_and_remove(reg):
    pts = {p.name: p for p in reg.expand_device(_dev(
        template="meter",
        points=[{"name": "frequency", "value": 60, "behavior": {"type": "static"}},
                {"name": "extra", "table": "holding"}],
        removed=["energy"]))}
    assert pts["frequency"].value == 60 and pts["frequency"].table == "input" and pts["frequency"].address == 1
    assert pts["frequency"].behavior == {"type": "static"}
    assert "energy" not in pts
    assert (pts["extra"].table, pts["extra"].address) == ("holding", 4)  # after serial (0..3)


def test_override_errors_and_hooks(reg):
    with pytest.raises(ValueError, match=r"(?s)D/power: .*read-only"):
        reg.expand_device(_dev(template="meter", points=[{"name": "power", "access": "rw"}]))
    with pytest.raises(ValueError, match=r"points \['nope'\] need a table"):
        reg.expand_device(_dev(template="meter", points=[{"name": "nope", "value": 1}]))
    with pytest.raises(ValueError, match="overlaps"):
        reg.expand_device(_dev(template="meter", points=[{"name": "x", "table": "input", "address": 0, "size": 2},
                                                                {"name": "y", "table": "input", "address": 1}]))
    with pytest.raises(ValueError, match=r"D: unknown template 'zzz' \(known: meter, custom\)"):
        reg.expand_device(_dev(template="zzz"))


def test_no_hooks_and_explicit_expand():
    reg = TemplateRegistry(Pt, app_name="sme-x")
    reg.register("t", "T", {}, lambda p: [{"name": "a"}])
    pts = reg.expand("Dev", "t", items=[Pt(name="b")])
    assert [(p.name, p.table, p.address) for p in pts] == [("a", None, None), ("b", None, None)]


def test_bacnet_style_items_attr_and_instances():
    class Obj(BaseModel):
        type: str
        name: str
        instance: Optional[int] = None

    class BDev(BaseModel):
        name: str
        template: Optional[str] = None
        params: Dict[str, Any] = Field(default_factory=dict)
        objects: List[Obj] = Field(default_factory=list)
        removed: Optional[List[str]] = None

    def assign_instances(owner, objs):
        used: Dict[str, set] = {}
        for o in objs:
            if o.instance is not None:
                used.setdefault(o.type, set()).add(o.instance)
        out = []
        for o in objs:
            if o.instance is None:
                s = used.setdefault(o.type, set())
                n = 1
                while n in s:
                    n += 1
                s.add(n)
                o = o.model_copy(update={"instance": n})
            out.append(o)
        return out

    reg = TemplateRegistry(Obj, app_name="sme-bacnet-sim", items_attr="objects", finalize_hook=assign_instances)
    reg.register("ahu", "AHU", {}, lambda p: [{"type": "ai", "name": "Temp"}, {"type": "ai", "name": "RH"},
                                              {"type": "bo", "name": "Fan"}])
    objs = reg.expand_device(BDev(name="B", template="ahu", objects=[Obj(type="ai", name="X", instance=1)]))
    assert [(o.name, o.instance) for o in objs] == [("Temp", 2), ("RH", 3), ("Fan", 1), ("X", 1)]
    assert reg.env_var == "SME_BACNET_SIM_TEMPLATES"


def test_substitute_and_escape():
    p = {"kw": 10, "dev": "M1"}
    assert substitute("{kw}", p) == 10 and substitute("{kw}", p) is p["kw"]  # one placeholder keeps the type
    assert substitute({"a": ["x {kw} {{y}}", 3]}, p) == {"a": ["x 10 {y}", 3]}
    assert substitute(escape_braces({"e": "{a}"}), {}) == {"e": "{a}"}
    with pytest.raises(ValueError, match="unknown parameter 'nope'"):
        substitute("{nope}", p)
    with pytest.raises(ValueError, match="unknown parameter 'nope'"):
        substitute("a {nope}", p)
    with pytest.raises(ValueError, match="bad placeholder"):
        substitute("a { b", p)
    assert NAME_RE.match("my_pcs.v2") and not NAME_RE.match("a b")


# ---------------------------------------------------------------- user-local templates


def test_user_templates_load_override_and_errors(reg, tmp_path):
    (tmp_path / "inv.yaml").write_text("""
title: My inverter
description: test inverter
params: {rated_kw: 10}
points:
  - {name: p, table: holding, address: 0, max: "{rated_kw}", description: "limit {rated_kw} kW {{raw}}"}
  - {name: q, table: input, behavior: {type: expr, expr: "p * {rated_kw}"}}
""", encoding="utf-8")
    (tmp_path / "custom.yml").write_text("name: custom\ntitle: Overridden\npoints: [{name: x, table: coil}]\n",
                                         encoding="utf-8")
    (tmp_path / "bad.yaml").write_text("points: [{name: y, table: nowhere}]\n", encoding="utf-8")
    (tmp_path / "bad2.yaml").write_text("foo: 1\n", encoding="utf-8")
    (tmp_path / "bad3.yaml").write_text("points: [{name: z, table: input, max: '{nope}'}]\n", encoding="utf-8")
    (tmp_path / "bad4.yaml").write_text("points: [{name: z}]\n", encoding="utf-8")  # validate_hook: no table
    (tmp_path / "bad5.yaml").write_text("points: [{name: z, table: input}, {name: z, table: coil}]\n",
                                        encoding="utf-8")
    (tmp_path / "broken.yaml").write_text("points: [\n", encoding="utf-8")
    (tmp_path / "zdup.yaml").write_text("name: inv\npoints: []\n", encoding="utf-8")
    errs = reg.load_user_templates(tmp_path)
    by = {Path(e["path"]).name: e["error"] for e in errs}
    assert set(by) == {"bad.yaml", "bad2.yaml", "bad3.yaml", "bad4.yaml", "bad5.yaml", "broken.yaml", "zdup.yaml"}
    assert by["bad.yaml"].startswith("points.table:")
    assert "unknown key(s) ['foo']" in by["bad2.yaml"]
    assert "unknown parameter 'nope'" in by["bad3.yaml"]
    assert "need a table" in by["bad4.yaml"] and "duplicate point names ['z']" in by["bad5.yaml"]
    assert "already defined in" in by["zdup.yaml"]
    assert reg.user_errors == errs
    cat = {t["name"]: t for t in reg.catalog()}
    assert cat["inv"]["source"] == "user" and cat["inv"]["description"] == "test inverter"
    assert cat["inv"]["path"].endswith("inv.yaml") and cat["inv"]["overrides_builtin"] is False
    assert cat["custom"]["source"] == "user" and cat["custom"]["overrides_builtin"] and cat["custom"]["title"] == "Overridden"
    assert cat["meter"]["source"] == "builtin" and "path" not in cat["meter"]
    assert [t["name"] for t in reg.catalog()] == ["meter", "custom", "inv"]
    pts = {p.name: p for p in reg.expand_device(_dev(template="inv", params={"rated_kw": 20}))}
    assert pts["p"].max == 20 and pts["p"].description == "limit 20 kW {raw}"
    assert pts["q"].behavior["expr"] == "p * 20" and (pts["q"].table, pts["q"].address) == ("input", 0)
    assert [p.name for p in reg.expand_device(_dev(template="custom"))] == ["x"]
    reg.clear_user_templates()
    assert [t["name"] for t in reg.catalog()] == ["meter", "custom"] and reg.user_errors == []
    with pytest.raises(ValueError, match="unknown template"):
        reg.expand_device(_dev(template="inv"))


def test_templates_dir_resolution(reg, monkeypatch, tmp_path):
    assert env_var_for("sme-modbus-sim") == "SME_MODBUS_SIM_TEMPLATES"
    assert reg.env_var == "SME_TEST_SIM_TEMPLATES"
    monkeypatch.delenv(reg.env_var, raising=False)
    assert reg.default_templates_dir() == Path.home() / ".sme-test-sim" / "templates"
    assert reg.resolve_templates_dir() == reg.default_templates_dir()
    monkeypatch.setenv(reg.env_var, str(tmp_path / "t"))
    assert reg.default_templates_dir() == tmp_path / "t" and reg.templates_dir() == tmp_path / "t"
    assert reg.resolve_templates_dir(tmp_path / "x") == tmp_path / "x"  # explicit wins over env
    assert reg.load_user_templates(tmp_path / "missing") == []
    assert reg.templates_dir() == tmp_path / "missing"  # the directory last loaded
    custom = TemplateRegistry(Pt, app_name="sme-test-sim", env_var="MY_TPL")
    monkeypatch.setenv("MY_TPL", str(tmp_path / "y"))
    assert custom.default_templates_dir() == tmp_path / "y"


def test_device_as_template_round_trip(reg, tmp_path):
    dev = _dev(template="meter", params={"rated_kw": 20}, order="little",
               points=[{"name": "power", "description": "set {x}"}])
    text = reg.device_as_template(dev, "my_meter")
    doc = yaml.safe_load(text)
    assert doc["name"] == "my_meter" and doc["description"] == "Saved from device D" and doc["params"] == {}
    assert all(p["order"] == "little" for p in doc["points"])  # export_hook applied
    assert doc["points"][0]["description"] == "set {{x}}"  # literal braces escaped
    (tmp_path / "my_meter.yaml").write_text(text, encoding="utf-8")
    assert reg.load_user_templates(tmp_path) == []
    strip = lambda pts: [{k: v for k, v in p.model_dump().items() if k != "order"} for p in pts]  # noqa: E731
    saved = reg.expand_device(_dev(template="my_meter"))
    assert strip(saved) == strip(reg.expand_device(dev))
    assert all(p.order == "little" for p in saved)
    with pytest.raises(ValueError, match="invalid template name"):
        reg.device_as_template(dev, "a b")
