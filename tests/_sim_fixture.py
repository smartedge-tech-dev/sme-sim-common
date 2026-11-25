"""A tiny product (config model + BaseEngine subclass) used by the engine / web / xlsx tests."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import model_validator

from sme_sim_common.config import StrictModel
from sme_sim_common.engine import BaseEngine


class Simulation(StrictModel):
    running: bool = True
    time_scale: float = 1.0
    tick_seconds: float = 0.05


class Point(StrictModel):
    name: str
    value: float = 0.0
    units: Optional[str] = None


class Device(StrictModel):
    name: str
    unit: int = 1
    description: Optional[str] = None
    template: Optional[str] = None
    params: Dict[str, Any] = {}
    points: List[Point] = []


class Config(StrictModel):
    simulation: Simulation = Simulation()
    devices: List[Device] = []

    @model_validator(mode="after")
    def _unique(self):
        names = [d.name for d in self.devices]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"duplicate device name(s) {sorted(dup)}")
        return self


class Engine(BaseEngine):
    """``boom`` device fails to build; ``apply_fail`` makes the swap fail (rollback path)."""

    def __init__(self, config, **kw):
        self.apply_fail = False
        self.diffs: List[tuple] = []
        self.steps: List[float] = []
        super().__init__(config, **kw)

    def _build(self, config):
        if any(d.name == "boom" for d in config.devices):
            raise ValueError("device boom cannot be built")
        return {d.name: {p.name: p.value for p in d.points} for d in config.devices}

    async def _apply_diff(self, old_config, new_config, new_state):
        self.diffs.append(([d.name for d in old_config.devices], [d.name for d in new_config.devices]))
        self._install(new_state)
        if self.apply_fail:
            raise RuntimeError("port in use")

    def _step(self, dt):
        self.steps.append(dt)

    def snapshot(self):
        return {"devices": sorted(self.state), "running": self.running, "time_scale": self.time_scale,
                "sim_time": self.sim_time, "events": self.event_history()}


YAML = """# site comment
simulation:
  tick_seconds: 0.05
devices:
  - name: pcs1   # inline comment
    unit: 1
    points:
      - name: p
        value: 1.5
"""
