import io

import pytest
from openpyxl import load_workbook

from sme_sim_common import xlsx as X
from sme_sim_common.config import parse_text

from _sim_fixture import YAML, Config


def export_rows(cfg):
    devs, pts = [], []
    for d in cfg.devices:
        dd = d.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        dd.pop("points", None)
        devs.append(dd)
        for p in d.points:
            pts.append({"device": d.name, **p.model_dump(mode="json", exclude_unset=True, exclude_none=True)})
    return {"Devices": devs, "Points": pts}


def build(tables, base, errors, warnings):
    devices = {}
    for r in tables["Devices"]:
        if r.ok and r.values["name"] in devices:
            errors.append(f"Devices row {r.row_no}, column 'name': duplicate device {r.values['name']!r}")
        elif r.ok:
            devices[r.values["name"]] = {**r.merged(), "points": []}
    for r in tables["Points"]:
        if not r.ok:
            continue
        p = r.merged()
        dev = devices.get(p.pop("device"))
        if dev is None:
            errors.append(f"Points row {r.row_no}, column 'device': unknown device")
            continue
        dev["points"].append(p)
    top = {"devices": list(devices.values())}
    if base is not None and "simulation" in base.model_fields_set:
        top["simulation"] = base.simulation.model_dump(mode="json", exclude_unset=True)
    return top


SCHEMA = X.XlsxSchema(
    [X.Sheet("Devices", [("name", "名前 / 名称"), ("unit", "ユニット"), ("params", "YAML"), ("extra", "YAML")],
             kinds={"unit": "int", "params": "yaml"}, required=("name",)),
     X.Sheet("Points", [("device", "デバイス"), ("name", "名前"), ("value", "値"), ("extra", "YAML")],
             kinds={"value": "float"}, required=("device", "name"))],
    export_rows=export_rows, build=build, model=Config, template_file="t.xlsx", export_file="e.xlsx")


def test_roundtrip_and_extra_column():
    cfg = parse_text(YAML, Config)
    cfg.devices[0].description = "PCS"  # no column -> extra
    cfg.devices[0].points[0].units = "kW"
    data, warnings = X.export_xlsx(cfg, schema=SCHEMA)
    assert warnings == []
    ws = load_workbook(io.BytesIO(data))["Devices"]
    assert [c.value for c in ws[1]] == ["name", "unit", "params", "extra"]
    assert str(ws["A2"].value).startswith("# ")
    assert ws["D3"].value == "{description: PCS}"
    back, warns = X.import_xlsx(data, cfg, schema=SCHEMA)
    assert warns == [] and isinstance(back, Config)
    assert back.devices[0].description == "PCS" and back.devices[0].points[0].units == "kW"
    assert back.simulation.tick_seconds == 0.05
    assert "description: PCS" in X.to_yaml(back) and "time_scale" not in X.to_yaml(back)  # exclude_unset


def test_blank_template_has_all_sheets():
    wb = load_workbook(io.BytesIO(SCHEMA.blank_template()))
    assert wb.sheetnames == ["Devices", "Points"] and wb["Points"]["A2"].value.startswith("#")


def _book(rows_by_sheet):
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in rows_by_sheet.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_errors_are_collected_not_raised():
    data = _book({
        "Devices": [["name", "unit", "bogus"], ["# help"], ["d1", "x"], [None, 2], ["d2", 3, "ignored"]],
        "Points": [["device", "name", "value"], ["d2", "p", "nan?"], ["zz", "q", 1]],
    })
    cfg, errors = X.import_xlsx(data, schema=SCHEMA)
    assert cfg is None
    text = "\n".join(errors)
    assert "Devices row 3, column 'unit': not an integer" in text
    assert "Devices row 4, column 'name': required" in text
    assert "Points row 2, column 'value': not a number" in text
    assert "Points row 3, column 'device': unknown device" in text


def test_missing_sheet_unreadable_and_validation():
    assert X.import_xlsx(b"not a zip", schema=SCHEMA)[0] is None
    cfg, errors = X.import_xlsx(_book({"Devices": [["name"]]}), schema=SCHEMA)
    assert cfg is None and errors == ["sheet 'Points' is missing"]
    dup = _book({"Devices": [["name"], ["a"], ["a"]], "Points": [["device", "name"]]})
    cfg, errors = X.import_xlsx(dup, schema=SCHEMA)
    assert cfg is None and "duplicate device" in errors[0]
    cfg, errors = X.import_xlsx(_book({"Devices": [["unit"], [1]], "Points": [["device", "name"]]}), schema=SCHEMA)
    assert errors == ["Devices row 1: missing column(s) name"]


def test_unknown_column_warning_and_cell_limit():
    data = _book({"Devices": [["name", "colour"], ["a", "red"]], "Points": [["device", "name"]]})
    cfg, warnings = X.import_xlsx(data, schema=SCHEMA)
    assert cfg.devices[0].name == "a" and warnings == ["Devices: unknown column 'colour' ignored"]
    _, warnings = SCHEMA.write({"Devices": [{"name": "x" * (X.CELL_LIMIT + 1)}]})
    assert "Excel cell limit" in warnings[0]


def test_converters():
    assert X.convert("int", 3.0) == 3 and X.convert("number", "2.0") == 2 and X.convert("bool", "yes") is True
    assert X.convert("list", "a, b,") == ["a", "b"] and X.convert("port", "COM5") == "COM5"
    assert X.convert("lower", " TCP ") == "tcp" and X.convert("str", 5.0) == "5"
    for kind, v in (("int", True), ("float", "x"), ("bool", "maybe"), ("yaml", "[1]"), ("yaml", "{a: ")):
        with pytest.raises(ValueError):
            X.convert(kind, v)
    s = X.Sheet("S", [("a", "")], kinds={"a": lambda v: int(v) * 2})
    assert s.convert("a", "4") == 8


def test_missing_openpyxl_message(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("openpyxl"):
            raise ImportError("No module named 'openpyxl'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(X.XlsxUnavailable, match=r"sme-sim-common\[xlsx\]"):
        SCHEMA.blank_template()
    cfg, errors = X.import_xlsx(b"", schema=SCHEMA)
    assert cfg is None and "[xlsx]" in errors[0]
