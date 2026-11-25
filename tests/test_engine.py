import asyncio

import pytest

from sme_sim_common.config import parse_text
from sme_sim_common.engine import BaseEngine, EngineProtocol

from _sim_fixture import YAML, Config, Engine


def make():
    return Engine(parse_text(YAML, Config), config_text=YAML)


def test_protocol_and_abstract():
    assert isinstance(make(), EngineProtocol)
    with pytest.raises(TypeError):
        BaseEngine(Config())  # _build / snapshot are abstract


def test_initial_state_and_text():
    e = make()
    assert e.state == {"pcs1": {"p": 1.5}}
    assert e.config_text == YAML and e.tick_seconds == 0.05
    assert "devices" in Engine(Config()).config_text  # dumped when no text given


def test_reload_success_broadcasts():
    async def main():
        e = make()
        q = e.subscribe()
        cfg = Config.model_validate({"devices": [{"name": "a"}, {"name": "b"}]})
        await e.reload(cfg, "text: 1\n")
        assert e.config is cfg and e.config_text == "text: 1\n" and sorted(e.state) == ["a", "b"]
        assert e.diffs == [(["pcs1"], ["a", "b"])]
        msgs = [q.get_nowait() for _ in range(q.qsize())]
        assert msgs[-1] == {"type": "reload"}
        assert any(m["type"] == "log" and m["event"]["level"] == "config" for m in msgs)
        await e.reload(Config())  # text omitted -> dumped
        assert "devices: []" in e.config_text

    asyncio.run(main())


def test_reload_build_failure_keeps_old():
    async def main():
        e = make()
        q = e.subscribe()
        with pytest.raises(ValueError, match="boom"):
            await e.reload(Config.model_validate({"devices": [{"name": "boom"}]}))
        assert e.state == {"pcs1": {"p": 1.5}} and e.config_text == YAML and e.diffs == []
        assert q.empty()

    asyncio.run(main())


def test_reload_apply_failure_rolls_back():
    async def main():
        e = make()
        old = e.config
        q = e.subscribe()
        e.apply_fail = True
        with pytest.raises(RuntimeError, match="port in use"):
            await e.reload(Config.model_validate({"devices": [{"name": "x"}]}), "x")
        assert e.config is old and e.state == {"pcs1": {"p": 1.5}} and e.config_text == YAML
        msgs = [q.get_nowait() for _ in range(q.qsize())]
        assert [m["type"] for m in msgs] == ["log"] and msgs[0]["event"]["level"] == "error"

    asyncio.run(main())


def test_log_event_history_and_fanout():
    e = make()
    q1, q2 = e.subscribe(), e.subscribe()
    ev = e.log_event("info", "hello", kind="config", device="pcs1")
    assert ev["message"] == "hello" and ev["kind"] == "config" and ev["seq"] == 1
    assert e.event_history() == [ev] and e.event_history(1) == [ev]
    assert q1.get_nowait()["event"] is ev and q2.get_nowait()["event"] is ev
    e.unsubscribe(q2)
    e.unsubscribe(q2)  # idempotent
    e.publish({"type": "x"})
    assert q2.empty() and q1.get_nowait() == {"type": "x"}


def test_slow_subscriber_drops_oldest():
    e = make()
    e.queue_size = 2
    q = e.subscribe()
    for i in range(5):
        e.publish({"type": "n", "i": i})
    assert [q.get_nowait()["i"] for _ in range(q.qsize())] == [3, 4]


def test_pause_scale_and_step():
    e = make()
    q = e.subscribe()
    e.set_running(time_scale=10)
    assert e.config.simulation.time_scale == 10
    e.tick()
    assert e.steps == [pytest.approx(0.5)] and e.sim_time == pytest.approx(0.5)
    e.set_running(False)
    e.tick()
    assert e.steps == [pytest.approx(0.5)] and e.config.simulation.running is False
    sims = [m for m in (q.get_nowait() for _ in range(q.qsize())) if m["type"] == "simulation"]
    assert sims[-1] == {"type": "simulation", "running": False, "time_scale": 10.0}
    with pytest.raises(ValueError):
        e.set_running(time_scale=0)
    e.step(2)
    assert e.sim_time == pytest.approx(2.5)


def test_stats_only_with_subscribers():
    class S(Engine):
        def stats_snapshot(self):
            return {"rx": 1}

    e = S(Config())
    e.tick()  # nobody listening: nothing to compute
    q = e.subscribe()
    e.tick()
    e.tick()  # within stats_interval: no second push
    stats = [m for m in (q.get_nowait() for _ in range(q.qsize())) if m["type"] == "stats"]
    assert len(stats) == 1 and stats[0]["stats"] == {"rx": 1}


def test_tick_loop_runs():
    async def main():
        e = make()
        await e.start()
        await asyncio.sleep(0.2)
        await e.stop()
        assert len(e.steps) >= 2

    asyncio.run(main())
