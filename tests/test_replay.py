"""CSV time-series replay behavior (ported from sme-modbus-sim tests/test_replay.py @ 085fe59).

The behavior itself is tested, including the datatype-agnostic ``discrete`` / ``coerce`` hooks that the
products derive from their point models (Modbus bool / bit / enum, BACnet binary / multi-state).
Fixture CSV files are written into ``tmp_path``.
"""

import pytest

from sme_sim_common import behaviors
from sme_sim_common.behaviors import make_behavior

CSV = """time,oat,fan,mode
00:00:00,10,OFF,1
00:10:00,20,ON,2
00:20:00,30,OFF,3
"""


def _beh(tmp_path, column="oat", discrete=False, coerce=None, **kw):
    (tmp_path / "day.csv").write_text(CSV, encoding="utf-8")
    spec = {"type": "replay", "file": "day.csv", "column": column, **kw}
    return make_behavior(spec, tmp_path, discrete, coerce)


def test_linear_interpolation(tmp_path):
    b = _beh(tmp_path)
    assert b.step({"t": 1.0}, None, 1.0) == pytest.approx(10 + 1 / 60)  # replay time 0 = before the first tick
    assert b.step({"t": 300.0}, None, 1.0) == pytest.approx(15.0)
    assert b.step({"t": 900.0}, None, 1.0) == pytest.approx(25.0)
    assert b.step({"t": 5000.0}, None, 1.0) == 30.0  # no loop: holds the last value


def test_step_hold(tmp_path):
    b = _beh(tmp_path, interpolate="step")
    b.step({"t": 0.0}, None, 0.0)
    assert b.step({"t": 599.0}, None, 1.0) == 10.0
    assert b.step({"t": 600.0}, None, 1.0) == 20.0


def test_discrete_always_step_holds(tmp_path):
    b = _beh(tmp_path, column="mode", discrete=True)  # interpolate defaults to linear
    b.step({"t": 0.0}, None, 0.0)
    assert b.step({"t": 900.0}, None, 1.0) == 2.0


def test_coerce_converts_values(tmp_path):
    to_bool = lambda v: str(v).strip().upper() in ("ON", "1", "TRUE")  # noqa: E731
    b = _beh(tmp_path, column="fan", discrete=True, coerce=to_bool)
    b.step({"t": 0.0}, None, 0.0)
    assert b.step({"t": 300.0}, None, 1.0) is False
    assert b.step({"t": 700.0}, None, 1.0) is True
    b2 = _beh(tmp_path, column="mode", discrete=True, coerce=int)
    assert b2.step({"t": 0.0}, None, 0.0) == 1 and isinstance(b2.step({"t": 1.0}, None, 1.0), int)


def test_loop_and_offset(tmp_path):
    b = _beh(tmp_path, loop=True, offset="00:05:00")
    assert b.step({"t": 0.0}, None, 0.0) == pytest.approx(15.0)
    assert b.progress() == {"t": "00:05:00", "pct": 25}
    assert b.step({"t": 1200.0}, None, 1.0) == pytest.approx(15.0)
    b2 = _beh(tmp_path, offset=300)
    assert b2.step({"t": 0.0}, None, 0.0) == pytest.approx(15.0)


def test_iso_timestamps_and_offset(tmp_path):
    (tmp_path / "iso.csv").write_text(
        "timestamp,kw\n2026-01-01T00:00:00,0\n2026-01-01T01:00:00,100\n", encoding="utf-8")
    b = make_behavior({"type": "replay", "file": "iso.csv", "column": "kw",
                       "offset": "2026-01-01T00:30:00"}, tmp_path)
    assert b.step({"t": 0.0}, None, 0.0) == pytest.approx(50.0)
    assert b.step({"t": 900.0}, None, 1.0) == pytest.approx(75.0)


@pytest.mark.parametrize("csv_text, msg", [
    ("time,oat\n", "needs a header row and at least one data row"),
    ("time\n00:00:00\n", "needs a timestamp column and at least one value column"),
    ("time,oat\n00:00:00,1\nnoon,2\n", r"line 3: bad timestamp 'noon' \(expected HH:MM:SS or seconds\)"),
    ("time,oat\n00:10:00,1\n00:05:00,2\n", "line 3: timestamp '00:05:00' goes backwards"),
    ("time,oat\n2026-01-01T00:00:00,1\n12:00,2\n", r"line 3: bad timestamp '12:00' \(expected an ISO datetime\)"),
])
def test_bad_csv_errors(tmp_path, csv_text, msg):
    (tmp_path / "bad.csv").write_text(csv_text, encoding="utf-8")
    with pytest.raises(ValueError, match=msg):
        make_behavior({"type": "replay", "file": "bad.csv", "column": "oat"}, tmp_path)


def test_missing_column_file_and_bad_params(tmp_path):
    with pytest.raises(ValueError, match=r"no column 'rh' \(columns: oat, fan, mode\)"):
        _beh(tmp_path, column="rh")
    with pytest.raises(ValueError, match="replay: cannot read"):
        make_behavior({"type": "replay", "file": "nope.csv", "column": "x"}, tmp_path)
    with pytest.raises(ValueError, match="interpolate must be"):
        _beh(tmp_path, interpolate="cubic")
    with pytest.raises(ValueError, match="bad offset"):
        _beh(tmp_path, offset="soon")
    with pytest.raises(ValueError, match="missing parameter 'column'"):
        make_behavior({"type": "replay", "file": "day.csv"}, tmp_path)


def test_cache_reparses_changed_file(tmp_path):
    b1 = _beh(tmp_path)
    again = make_behavior({"type": "replay", "file": "day.csv", "column": "fan"}, tmp_path, True)
    assert again.table is b1.table  # parsed once per path
    (tmp_path / "day.csv").write_text("time,oat\n0,99\n10,99\n", encoding="utf-8")
    b2 = make_behavior({"type": "replay", "file": "day.csv", "column": "oat"}, tmp_path)
    assert b2.table is not b1.table and b2.step({"t": 0.0}, None, 0.0) == 99.0
    assert behaviors.load_table(tmp_path / "day.csv") is b2.table


def test_bacnet_style_hooks(tmp_path):
    """BACnet: discrete for binary-* / multi-state-*, coerce active/inactive -> 1/0 (as sme-bac-sim would)."""
    obj_type = "binary-input"
    discrete = obj_type.startswith(("binary", "multi-state"))
    coerce = lambda v: {"ON": 1, "OFF": 0}.get(str(v).upper(), v)  # noqa: E731
    b = _beh(tmp_path, column="fan", discrete=discrete, coerce=coerce)
    assert b.linear is False
    assert b.step({"t": 0.0}, None, 0.0) == 0 and b.step({"t": 650.0}, None, 1.0) == 1
