"""Engine contract shared by the simulators.

``EngineProtocol`` is what :func:`sme_sim_common.web.make_base_app` depends on (structural typing, no inheritance
needed: BACnetSim keeps its own engine and only aligns the signatures, design §2.1 / §7.1). ``BaseEngine`` is an
optional base class for new engines (Modbus / OCPP / SerialHub): subscribe / publish fan-out, event log, the
"validate -> build -> swap -> roll back on failure -> broadcast reload" flow with an ``_apply_diff`` hook for
incremental reloads, and the tick loop with run / pause and time scale.

Generalised from sme-modbus-sim 085fe59 ``engine.py`` (``Engine.reload`` / ``subscribe`` / ``publish`` /
``log_event`` / ``set_running`` / ``_run``) and sme-bac-sim v0.4.0 ``engine.py`` (``subscribe`` / ``publish`` :813,
``reload`` :1068 restore-on-failure).
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Protocol, Union, runtime_checkable

from .config import dump_yaml

__all__ = ["EngineProtocol", "BaseEngine"]

log = logging.getLogger("sme_sim_common.engine")


@runtime_checkable
class EngineProtocol(Protocol):
    """What the common web layer needs from an engine.

    ``publish`` messages are dicts with a ``type``: ``reload`` (the web layer answers with a fresh snapshot),
    ``log`` (``{"event": ev}``), ``simulation``, ``stats``; products add their own (``values``, ``faults`` ...).
    """

    config: Any
    config_text: str
    config_path: Union[str, Path, None]

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def reload(self, config: Any, text: Optional[str] = None) -> None:
        """Replace the configuration; on failure raise and keep the old one running."""

    def subscribe(self) -> asyncio.Queue: ...

    def unsubscribe(self, q: asyncio.Queue) -> None: ...

    def publish(self, msg: Dict[str, Any]) -> None: ...

    def log_event(self, level: str, message: str, **fields: Any) -> Dict[str, Any]: ...

    def snapshot(self) -> Dict[str, Any]: ...


class BaseEngine(abc.ABC):
    """Optional base class implementing :class:`EngineProtocol`.

    Subclass hooks:

    * ``_build(config) -> state`` (required): build the runtime objects for a config **without** touching the
      running ones; raise to reject the config. The default :meth:`_install` stores the result in ``self.state``.
    * ``validate_config(config)``: extra checks before building (default: none).
    * ``async _apply_diff(old_config, new_config, new_state)``: make ``new_state`` live. Default: whole
      replacement through :meth:`_install`. Override for incremental reloads (OCPP per charger) or to rebind
      servers; raise to fail the reload.
    * ``async _rollback(old_config, old_state, error)``: undo a failed ``_apply_diff`` (default: reinstall the
      old state).
    * ``_step(dt)``: advance the simulation by ``dt`` simulated seconds (default: nothing).
    * ``_on_tick()``: called every tick, running or paused (e.g. scan for value changes), and once more on
      :meth:`wake`.
    * ``stats_snapshot() -> dict | None``: per-interface counters pushed as ``{"type": "stats"}`` every
      ``stats_interval`` seconds while someone is subscribed (``None`` = no stats).
    * ``snapshot() -> dict`` (required): the full state for ``GET /api/state`` and ``/ws``.

    Run / pause, time scale and tick length are read from ``config.simulation`` (``running`` / ``time_scale`` /
    ``tick_seconds``) when the config has them, else from the class defaults.
    """

    queue_size = 1000
    event_size = 500
    stats_interval = 2.0  # seconds between {"type": "stats"} pushes
    max_time_scale = 3600.0
    default_tick_seconds = 1.0
    #: Name of the logger behind ``self.logger`` (products set their own, e.g. ``"sme_modbus_sim.engine"``).
    logger_name = "sme_sim_common.engine"

    def __init__(self, config: Any, *, config_text: Optional[str] = None,
                 config_path: Optional[Union[str, Path]] = None, base_dir: Optional[Union[str, Path]] = None):
        self.logger = logging.getLogger(self.logger_name)
        self.config_path = Path(config_path) if config_path else None
        self.base_dir = Path(base_dir) if base_dir else (self.config_path.resolve().parent if self.config_path
                                                         else None)
        self.events: Deque[Dict[str, Any]] = deque(maxlen=self.event_size)
        self._seq = 0
        self._subs: List[asyncio.Queue] = []
        self._task: Optional[asyncio.Task] = None
        self._lock: Optional[asyncio.Lock] = None
        self._stopping = False
        self._stats_at = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._wake: Optional[asyncio.Event] = None
        self.sim_time = 0.0
        self.state: Any = None
        sim = getattr(config, "simulation", None)
        self.running: bool = bool(getattr(sim, "running", True))
        self.time_scale: float = float(getattr(sim, "time_scale", 1.0))
        self.tick_seconds: float = float(getattr(sim, "tick_seconds", self.default_tick_seconds))
        self.validate_config(config)
        self._install(self._build(config))
        self.config = config
        self.config_text = config_text if config_text is not None else self.dump_config(config)

    # ------------------------------------------------------------ hooks

    @abc.abstractmethod
    def _build(self, config: Any) -> Any:
        """Build the runtime state for ``config`` (raise to reject it)."""

    @abc.abstractmethod
    def snapshot(self) -> Dict[str, Any]:
        """Full state for ``GET /api/state`` and the first ``/ws`` message."""

    def validate_config(self, config: Any) -> None:
        """Extra validation before building (raise ``ValueError`` to reject)."""

    def dump_config(self, config: Any) -> str:
        """Text stored as ``config_text`` when a reload passes none."""
        return dump_yaml(config)

    def _install(self, state: Any) -> None:
        self.state = state

    async def _apply_diff(self, old_config: Any, new_config: Any, new_state: Any) -> None:
        self._install(new_state)

    async def _rollback(self, old_config: Any, old_state: Any, error: BaseException) -> None:
        self._install(old_state)

    def _step(self, dt: float) -> None:
        pass

    def _on_tick(self) -> None:
        pass

    def stats_snapshot(self) -> Optional[Dict[str, Any]]:
        return None

    # ------------------------------------------------------------ reload

    async def reload(self, config: Any, text: Optional[str] = None) -> None:
        """Validate -> build -> swap (``_apply_diff``) -> broadcast ``{"type": "reload"}``.

        If validation or building fails nothing is touched; if ``_apply_diff`` fails ``_rollback`` restores the
        old state. Either way the exception is re-raised and the old configuration keeps running."""
        lock = self._lock or asyncio.Lock()
        async with lock:
            self.validate_config(config)
            new_state = self._build(config)
            old_config, old_state = self.config, self.state
            try:
                await self._apply_diff(old_config, config, new_state)
            except Exception as e:
                with contextlib.suppress(Exception):
                    await self._rollback(old_config, old_state, e)
                self.config = old_config
                self.log_event("error", f"reload failed, previous configuration kept: {e}")
                raise
            self.config = config
            self.config_text = text if text is not None else self.dump_config(config)
            self._sync_simulation()
        self.log_event("config", "configuration reloaded")
        self.publish({"type": "reload"})

    def _sync_simulation(self) -> None:
        sim = getattr(self.config, "simulation", None)
        if sim is not None:
            self.running = bool(getattr(sim, "running", self.running))
            self.time_scale = float(getattr(sim, "time_scale", self.time_scale))
            self.tick_seconds = float(getattr(sim, "tick_seconds", self.tick_seconds))

    # ------------------------------------------------------------ pub / sub

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with contextlib.suppress(ValueError):
            self._subs.remove(q)

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def publish(self, msg: Dict[str, Any]) -> None:
        """Fan ``msg`` out to every subscriber; a slow consumer loses its oldest message, never blocks us."""
        for q in list(self._subs):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(msg)

    def log_event(self, level: str, message: str, **fields: Any) -> Dict[str, Any]:
        """Append an event (``seq`` / ``t`` / ``level`` / ``message`` + ``fields``), log it, publish
        ``{"type": "log", "event": ev}`` and return it."""
        self._seq += 1
        ev = {"seq": self._seq, "t": time.time(), "level": level, "message": message, **fields}
        self.events.append(ev)
        lg = self.logger
        (lg.error if level == "error" else lg.warning if level == "warning" else lg.info)(message)
        self.publish({"type": "log", "event": ev})
        return ev

    def event_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """The most recent events (oldest first)."""
        ev = list(self.events)
        return ev[-limit:] if limit else ev

    # ------------------------------------------------------------ simulation clock

    def set_running(self, running: Optional[bool] = None, time_scale: Optional[float] = None) -> None:
        """Run / pause and change the time scale; mirrored into ``config.simulation`` when it exists."""
        if time_scale is not None:
            ts = float(time_scale)
            if not 0 < ts <= self.max_time_scale:
                raise ValueError(f"time_scale must be in (0, {self.max_time_scale:g}]")
            self.time_scale = ts
        if running is not None:
            self.running = bool(running)
        sim = getattr(self.config, "simulation", None)
        if sim is not None:
            for k in ("running", "time_scale"):
                with contextlib.suppress(AttributeError, TypeError, ValueError):
                    setattr(sim, k, getattr(self, k))
        self.log_event("info", f"simulation {'running' if self.running else 'paused'} (x{self.time_scale:g})")
        self.publish({"type": "simulation", "running": self.running, "time_scale": self.time_scale})

    def step(self, dt: float) -> None:
        """Advance simulated time by ``dt`` seconds (tests call this directly)."""
        self.sim_time += dt
        self._step(dt)

    def tick(self) -> None:
        """One scheduler tick: step when running, then ``_on_tick`` and the stats push."""
        if self.running:
            self.step(self.tick_seconds * self.time_scale)
        self._on_tick()
        now = time.monotonic()
        if self._subs and now >= self._stats_at:
            stats = self.stats_snapshot()
            if stats is not None:
                self._stats_at = now + self.stats_interval
                self.publish({"type": "stats", "t": time.time(), "stats": stats})

    async def start(self) -> None:
        self._lock = asyncio.Lock()
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = False
        self._task = asyncio.create_task(self._run())

    def wake(self) -> None:
        """Run one extra ``_on_tick`` (scan for changes, push) as soon as possible, without advancing simulated
        time or shifting the tick schedule. Several wakes before it runs coalesce into one. Thread-safe: may be
        called from any thread (e.g. a protocol stack's callback); a no-op before :meth:`start` / after the loop
        closed."""
        loop, ev = self._loop, self._wake
        if loop is None or ev is None or loop.is_closed():
            return
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            ev.set()
        else:
            with contextlib.suppress(RuntimeError):  # loop closed in the meantime
                loop.call_soon_threadsafe(ev.set)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _guarded(self, fn, what: str) -> None:
        async with self._lock:
            try:
                fn()
            except Exception as e:  # keep the loop alive; surface the error
                self.log_event("error", f"{what} failed: {type(e).__name__}: {e}")

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        if self._wake is None:
            self._wake = asyncio.Event()
        wake = self._wake
        nxt = loop.time()
        while not self._stopping:
            if loop.time() >= nxt:
                wake.clear()  # the due tick covers a pending wake-up
                await self._guarded(self.tick, "tick")
                nxt = max(nxt + self.tick_seconds, loop.time())
            # asyncio.timeout, not wait_for: on Python 3.11 wait_for returns the inner result when a cancel
            # arrives just as wake.wait() completes, swallowing the cancellation and keeping the task alive.
            try:
                async with asyncio.timeout(max(0.0, nxt - loop.time())):
                    await wake.wait()
            except TimeoutError:
                continue
            wake.clear()
            if loop.time() < nxt:  # woken between ticks: scan / push only, the schedule is unchanged
                await self._guarded(self._on_tick, "wake")
