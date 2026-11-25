"""Behavior kinds and the restricted expression evaluator (ported from sme-modbus-sim tests @ 085fe59)."""

import pytest

from sme_sim_common.behaviors import (BEHAVIORS, ENGINE_NAMES, FUNCTIONS, ExpressionError, check_point_names,
                                      compile_expr, ident, make_behavior, reserved_names)


def test_eight_kinds_registered():
    assert set(BEHAVIORS) == {"sine", "random", "random_walk", "expr", "follow", "ramp", "counter", "pulse", "replay"}


def test_static_and_unknown():
    assert make_behavior(None) is None and make_behavior({"type": "static"}) is None
    with pytest.raises(ValueError, match="unknown behavior type"):
        make_behavior({"type": "nope"})
    with pytest.raises(ValueError, match="missing parameter 'expr'"):
        make_behavior({"type": "expr"})


@pytest.mark.parametrize("src", ["__import__('os')", "a.b", "(lambda: 1)()", "[x for x in y]", "open('f')()"])
def test_safe_eval_rejects(src):
    with pytest.raises(ExpressionError):
        compile_expr(src)


def test_expr_and_pv_name():
    fn = compile_expr("clamp(a * 2, 0, 5) + pv('Dev', 'p')")
    assert fn({"a": 10, "pv": lambda d, p: 1}) == 6
    assert ident("p-1 x") == "p_1_x" and ident("1st") == "_1st"


def test_follow_counter_pulse_sine_walk():
    f = make_behavior({"type": "follow", "target": "100", "tau": 1})
    v = f.step({}, 0.0, 1.0)
    assert 60 < v < 65  # 1 - e^-1
    c = make_behavior({"type": "counter", "rate": "p / 3600"})
    assert c.step({"p": 3600}, 1.0, 2.0) == pytest.approx(3.0)
    pl = make_behavior({"type": "pulse", "rate": "0.5"})
    assert pl.step({}, 0, 1.0) == 0 and pl.step({}, 0, 1.0) == 1
    s = make_behavior({"type": "sine", "min": 0, "max": 10, "period": 4})
    assert s.step({"t": 1.0}, None, 1.0) == pytest.approx(10.0)
    w = make_behavior({"type": "random_walk", "min": 0, "max": 1, "step": 5})
    assert 0 <= w.step({}, 0.5, 1.0) <= 1


def test_ramp_slew_limit():
    r = make_behavior({"type": "ramp", "target": "sp", "rate": 10})
    assert r.step({"sp": 50}, 0.0, 1.0) == pytest.approx(10.0)
    assert r.step({"sp": 50}, 45.0, 1.0) == pytest.approx(50.0)  # within one step: snaps to target
    assert r.step({"sp": -50}, 0.0, 0.5) == pytest.approx(-5.0)
    assert r.step({"sp": 7}, None, 1.0) == 7  # no current value yet: start at the target
    r2 = make_behavior({"type": "ramp", "target": "sp * 2", "rate": "k"})
    assert r2.step({"sp": 10, "k": 4}, 0.0, 2.0) == pytest.approx(8.0)
    with pytest.raises(ValueError, match="missing parameter"):
        make_behavior({"type": "ramp", "rate": 1})


def test_reserved_names():
    r = reserved_names()
    assert {"t", "dt", "hour", "pv", "sin", "clamp", "noise"} <= r and set(ENGINE_NAMES) | set(FUNCTIONS) == r
    assert "foo" in reserved_names(["foo"])


def test_check_point_names():
    check_point_names("D", ["power", "soc", "t1"])  # fine
    check_point_names("D", iter(["power"]))  # any iterable of names
    with pytest.raises(ValueError, match=r"device 'D': point name 'hour', 'dt' is reserved"):
        check_point_names("D", ["hour", "ok", "dt"])
    with pytest.raises(ValueError, match=r"object name 'p-v' \(as 'p_v'\)"):
        check_point_names("D", ["p-v"], reserved={"p_v"}, kind="object")
    with pytest.raises(ValueError, match="rename the point"):
        check_point_names("D", ["sin"])


@pytest.mark.parametrize("src, word", [
    ("pv > 3", "'pv' is a function; call it as pv(device, point)"),
    ("max + 1", "'max' is a function"),
    ("clamp", "'clamp' is a function"),
    ("t(1)", "'t' is a value, not a function"),
    ("pi(2)", "'pi' is a value, not a function"),
])
def test_function_value_misuse_rejected(src, word):
    with pytest.raises(ExpressionError, match=word.replace("(", r"\(").replace(")", r"\)")):
        compile_expr(src)


def test_function_value_proper_use_ok():
    fn = compile_expr("max(t, 1) + pi * 0 + clamp(dt, 0, 1)")
    assert fn({"t": 5, "dt": 2}) == 6
    assert compile_expr("pv('d', 'p') + 1")({"pv": lambda d, p: 2}) == 3
