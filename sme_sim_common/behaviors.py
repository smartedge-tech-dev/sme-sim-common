# Shared by the SME simulators. Taken from sme-modbus-sim sme_modbus_sim/behaviors.py @ 085fe59
# (itself generalised from sme-bac-sim @ ebd27ec: Replay takes ``discrete`` / ``coerce`` hooks instead of
# BACnet object types). ``reserved_names`` / ``check_point_names`` come from sme-modbus-sim config.py @ 085fe59.
"""Value simulation behaviors and a restricted expression evaluator.

Expressions are plain Python expressions restricted to arithmetic, comparisons,
boolean logic, conditional expressions and a whitelist of functions.  Names
refer to points of the same device (point name with non-identifier chars
replaced by ``_``); other devices are reachable with ``pv("Device", "point")``.
The engine supplies ``t`` (sim seconds), ``dt``, ``hour`` and ``pv`` in the name map
(``ENGINE_NAMES``); together with ``FUNCTIONS`` they are reserved (``reserved_names``).
"""

from __future__ import annotations

import ast
import bisect
import csv
import math
import random as _random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.IfExp,
    ast.Call, ast.Name, ast.Load, ast.Constant, ast.Tuple, ast.List,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
)


def ident(name: str) -> str:
    """Point name -> expression identifier."""
    s = re.sub(r"\W", "_", name)
    return "_" + s if s[:1].isdigit() else s


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


FUNCTIONS: Dict[str, Any] = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "exp": math.exp, "log": math.log,
    "sqrt": math.sqrt, "pi": math.pi, "abs": abs, "min": min, "max": max, "round": round,
    "int": int, "float": float, "bool": bool, "sum": sum, "clamp": _clamp,
    "random": _random.random, "uniform": _random.uniform,
    "noise": lambda a=1.0: _random.uniform(-a, a),
    "gauss": lambda sigma=1.0: _random.gauss(0, sigma),
}


class ExpressionError(ValueError):
    pass


ENGINE_NAMES: Tuple[str, ...] = ("t", "dt", "hour", "pv")
"""Names the engine puts into every expression's name map."""


def reserved_names(extra: Iterable[str] = ()) -> set:
    """Identifiers a point may not take: ``ENGINE_NAMES`` + ``FUNCTIONS`` (+ product-specific ``extra``)."""
    return set(ENGINE_NAMES) | set(FUNCTIONS) | set(extra)


def check_point_names(owner: str, names: Iterable[str], reserved: Optional[Iterable[str]] = None,
                      *, kind: str = "point") -> None:
    """Reject names whose expression identifier (``ident(name)``) collides with a reserved name.

    ``owner`` is used in the message (typically the device name); ``names`` is any iterable of
    point / object names; ``kind`` is the noun used in the message (``"point"``, ``"object"`` ...).
    """
    reserved = reserved_names() if reserved is None else set(reserved)
    bad = [f"{n!r}" + (f" (as {ident(n)!r})" if ident(n) != n else "")
           for n in names if ident(n) in reserved]
    if bad:
        raise ValueError(f"device {owner!r}: {kind} name {', '.join(bad)} is reserved in behavior expressions "
                         f"(reserved: {', '.join(sorted(reserved))}); rename the {kind}")


def compile_expr(src: str) -> Callable[[Dict[str, Any]], Any]:
    """Compile a restricted expression; returns fn(names) -> value."""
    try:
        tree = ast.parse(str(src), mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"syntax error in {src!r}: {e.msg}") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"not allowed in expression {src!r}: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ExpressionError(f"dunder names not allowed in {src!r}")
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise ExpressionError(f"only plain function calls allowed in {src!r}")
    code = compile(tree, "<expr>", "eval")
    env = {"__builtins__": {}, **FUNCTIONS}

    def run(names: Dict[str, Any]) -> Any:
        return eval(code, env, names)  # noqa: S307 - AST-whitelisted

    return run


class Behavior:
    """Base class: step() returns the new value, or None to leave it unchanged."""

    def __init__(self, spec: Dict[str, Any]):
        self.spec = spec

    def step(self, names: Dict[str, Any], current: float, dt: float) -> Optional[float]:
        raise NotImplementedError


class Sine(Behavior):
    def __init__(self, spec):
        super().__init__(spec)
        self.lo, self.hi = float(spec.get("min", 0)), float(spec.get("max", 100))
        self.period = float(spec.get("period", 60))
        self.phase = float(spec.get("phase", 0))
        self.noise = float(spec.get("noise", 0))

    def step(self, names, current, dt):
        mid, amp = (self.hi + self.lo) / 2, (self.hi - self.lo) / 2
        v = mid + amp * math.sin(2 * math.pi * (names["t"] / self.period) + self.phase)
        return v + (_random.uniform(-self.noise, self.noise) if self.noise else 0)


class Random(Behavior):
    def step(self, names, current, dt):
        return _random.uniform(float(self.spec.get("min", 0)), float(self.spec.get("max", 100)))


class RandomWalk(Behavior):
    def step(self, names, current, dt):
        lo, hi = float(self.spec.get("min", 0)), float(self.spec.get("max", 100))
        step = float(self.spec.get("step", (hi - lo) / 50))
        v = (current if current is not None else (lo + hi) / 2) + _random.uniform(-step, step)
        return _clamp(v, lo, hi)


class Expr(Behavior):
    def __init__(self, spec):
        super().__init__(spec)
        self.fn = compile_expr(spec["expr"])

    def step(self, names, current, dt):
        return self.fn(names)


class Follow(Behavior):
    """First-order lag toward a target expression (e.g. room temperature)."""

    def __init__(self, spec):
        super().__init__(spec)
        self.target = compile_expr(spec["target"])
        self.tau = max(float(spec.get("tau", 60)), 1e-3)
        self.noise = float(spec.get("noise", 0))

    def step(self, names, current, dt):
        target = float(self.target(names))
        cur = target if current is None else float(current)
        v = cur + (target - cur) * (1 - math.exp(-dt / self.tau))
        return v + (_random.uniform(-self.noise, self.noise) if self.noise else 0)


class Ramp(Behavior):
    """Slew-rate limited tracking: moves toward ``target`` by at most ``rate`` units per (sim) second.

    ``target`` is an expression (a plain point name works too); ``rate`` is a number or an expression.
    Typical use: a PCS active power output following its setpoint (kW/s).
    """

    def __init__(self, spec):
        super().__init__(spec)
        self.target = compile_expr(spec["target"])
        self.rate = compile_expr(spec.get("rate", 1))

    def step(self, names, current, dt):
        target = float(self.target(names))
        if current is None:
            return target
        cur = float(current)
        limit = abs(float(self.rate(names))) * dt
        diff = target - cur
        if abs(diff) <= limit:
            return target
        return cur + math.copysign(limit, diff)


class Counter(Behavior):
    """Integrates a rate expression (units per second), e.g. energy from power."""

    def __init__(self, spec):
        super().__init__(spec)
        self.rate = compile_expr(spec.get("rate", 1))

    def step(self, names, current, dt):
        return float(current or 0) + float(self.rate(names)) * dt


class Pulse(Behavior):
    """Pulse counter for accumulators: adds ``rate`` pulses per second (fractions carried over).

    Wrapping (if any) is up to the product (e.g. a BACnet accumulator's max-pres-value).
    """

    def __init__(self, spec):
        super().__init__(spec)
        self.rate = compile_expr(spec.get("rate", 1))
        self.frac = 0.0

    def step(self, names, current, dt):
        x = max(0.0, float(self.rate(names))) * dt + self.frac
        n = math.floor(x)
        self.frac = x - n
        return int(current or 0) + n


# --------------------------------------------------------------------------- CSV replay

_HMS = re.compile(r"^(\d+):([0-5]?\d)(?::([0-5]?\d(?:\.\d*)?))?$")


def parse_elapsed(value: Any) -> Optional[float]:
    """``HH:MM:SS`` / ``HH:MM`` / plain seconds -> seconds; None if it is neither."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    s = str(value).strip()
    m = _HMS.match(s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3) or 0)
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_iso(value: Any) -> Optional[float]:
    """ISO 8601 datetime -> epoch seconds; None if it is not one."""
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fmt_elapsed(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


class ReplayTable:
    """A parsed replay CSV: times relative to the first row (seconds) and one value list per column."""

    def __init__(self, path: Path):
        self.path = path
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]
        except OSError as e:
            raise ValueError(f"replay: cannot read {path}: {e.strerror or e}") from None
        if len(rows) < 2:
            raise ValueError(f"replay: {path}: needs a header row and at least one data row")
        header = [h.strip() for h in rows[0]]
        if len(header) < 2:
            raise ValueError(f"replay: {path}: needs a timestamp column and at least one value column")
        self.columns: Dict[str, List[Any]] = {h: [] for h in header[1:] if h}
        times: List[float] = []
        self.iso = parse_elapsed(rows[1][0]) is None  # format decided by the first data row
        for n, row in enumerate(rows[1:], start=2):
            cell = row[0].strip() if row else ""
            t = parse_iso(cell) if self.iso else parse_elapsed(cell)
            if t is None:
                kind = "an ISO datetime" if self.iso else "HH:MM:SS or seconds"
                raise ValueError(f"replay: {path} line {n}: bad timestamp {cell!r} (expected {kind})")
            if times and t < times[-1]:
                raise ValueError(f"replay: {path} line {n}: timestamp {cell!r} goes backwards")
            times.append(t)
            for i, h in enumerate(header[1:], start=1):
                if not h:
                    continue
                raw = row[i].strip() if i < len(row) else ""
                col = self.columns[h]
                if raw == "":
                    if not col:
                        raise ValueError(f"replay: {path} line {n}: column {h!r} has no value")
                    col.append(col[-1])  # an empty cell holds the previous value
                    continue
                try:
                    col.append(float(raw))
                except ValueError:
                    col.append(raw)  # non-numeric text (e.g. enum labels); converted by ``coerce``
        self.t0 = times[0]
        self.times = [t - self.t0 for t in times]
        self.duration = self.times[-1]

    def column(self, name: str) -> List[Any]:
        if name not in self.columns:
            raise ValueError(f"replay: {self.path}: no column {name!r} (columns: {', '.join(self.columns)})")
        return self.columns[name]


_TABLES: Dict[Path, Tuple[Tuple[float, int], ReplayTable]] = {}


def load_table(path: Path) -> ReplayTable:
    """Parse a replay CSV once per path (shared by all points); re-parsed when the file changes."""
    path = path.resolve()
    try:
        st = path.stat()
    except OSError as e:
        raise ValueError(f"replay: cannot read {path}: {e.strerror or e}") from None
    sig = (st.st_mtime, st.st_size)
    hit = _TABLES.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    table = ReplayTable(path)
    _TABLES[path] = (sig, table)
    return table


class Replay(Behavior):
    """Plays one column of a CSV time series on the simulation clock.

    Replay time 0 is the first row. It advances with the simulated time (so it follows
    ``simulation.time_scale``), starts at ``offset`` and optionally loops; past the end without
    ``loop`` the last value is held. ``discrete`` points (e.g. bool / bit / enum / binary /
    multi-state) always step-hold; ``coerce`` (optional) converts each produced value to the point's
    datatype (e.g. label -> enum int, ``active`` -> 1). Both are decided by the product from its point model.
    """

    def __init__(self, spec, base_dir: Optional[Path] = None, discrete: bool = False,
                 coerce: Optional[Callable[[Any], Any]] = None):
        super().__init__(spec)
        p = Path(str(spec["file"]))
        if not p.is_absolute():
            p = (base_dir or Path.cwd()) / p
        self.table = load_table(p)
        self.values = self.table.column(str(spec["column"]))
        mode = str(spec.get("interpolate", "linear")).lower()
        if mode not in ("linear", "step"):
            raise ValueError(f"replay: interpolate must be 'linear' or 'step', got {mode!r}")
        self.coerce = coerce
        self.linear = mode == "linear" and not discrete
        self.loop = bool(spec.get("loop", False))
        off = spec.get("offset", 0)
        o = parse_elapsed(off)
        if o is None:
            iso = parse_iso(off)
            if iso is None:
                raise ValueError(f"replay: bad offset {off!r} (HH:MM:SS, seconds or an ISO datetime)")
            if not self.table.iso:
                raise ValueError("replay: an ISO datetime offset needs a CSV with ISO timestamps")
            o = iso - self.table.t0
        self.offset = max(0.0, o)
        self.start: Optional[float] = None
        self.pos = min(self.offset, self.table.duration)

    def position(self, t: float) -> float:
        """Simulated time -> replay time (seconds from the first row)."""
        pos = self.offset + (t - self.start)
        dur = self.table.duration
        if self.loop and dur > 0:
            return pos % dur
        return min(pos, dur)

    def value_at(self, pos: float) -> Any:
        times, vals = self.table.times, self.values
        i = max(0, bisect.bisect_right(times, pos) - 1)
        if i >= len(times) - 1 or not self.linear:
            return vals[i]
        a, b = vals[i], vals[i + 1]
        t0, t1 = times[i], times[i + 1]
        if not isinstance(a, float) or not isinstance(b, float) or t1 <= t0:
            return a
        return a + (b - a) * (pos - t0) / (t1 - t0)

    def step(self, names, current, dt):
        if self.start is None:
            self.start = names["t"] - dt  # replay time `offset` = when the behavior started
        self.pos = self.position(names["t"])
        v = self.value_at(self.pos)
        return self.coerce(v) if self.coerce else v

    def progress(self) -> Dict[str, Any]:
        dur = self.table.duration
        return {"t": fmt_elapsed(self.pos), "pct": int(100 * self.pos / dur) if dur > 0 else 100}


BEHAVIORS = {
    "sine": Sine,
    "random": Random,
    "random_walk": RandomWalk,
    "expr": Expr,
    "follow": Follow,
    "ramp": Ramp,
    "counter": Counter,
    "pulse": Pulse,
    "replay": Replay,
}


def make_behavior(spec: Optional[Dict[str, Any]], base_dir: Optional[Path] = None,
                  discrete: bool = False, coerce: Optional[Callable[[Any], Any]] = None) -> Optional[Behavior]:
    """Build a behavior; ``base_dir`` resolves relative replay files (the config file's directory).

    ``discrete`` / ``coerce`` only affect ``replay`` (step-hold and value conversion for the point's datatype;
    the product derives both from its own point model).
    """
    if not spec:
        return None
    kind = spec.get("type")
    if kind in (None, "none", "static"):
        return None
    cls = BEHAVIORS.get(kind)
    if cls is None:
        raise ValueError(f"unknown behavior type: {kind!r} (known: {', '.join(BEHAVIORS)})")
    try:
        if cls is Replay:
            return Replay(spec, base_dir, discrete, coerce)
        return cls(spec)
    except KeyError as e:
        raise ValueError(f"behavior {kind!r} missing parameter {e}") from None
