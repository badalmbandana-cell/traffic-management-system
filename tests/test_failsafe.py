import time

from signal_control.failsafe import FailsafeFSMWrapper
from signal_control.fsm_controller import FSMController


def make_wrapper(**kw):
    fsm = FSMController(["north", "south", "east", "west"])
    return FailsafeFSMWrapper(fsm, **kw)


def test_no_data_yet_means_failsafe():
    fs = make_wrapper(stale_after_seconds=5)
    result = fs.run_cycle({"north": 5, "south": 20, "east": 2, "west": 1})
    assert result["failsafe"] is True


def test_fresh_data_means_normal_density_mode():
    fs = make_wrapper(stale_after_seconds=5)
    fs.mark_data_received()
    result = fs.run_cycle({"north": 5, "south": 20, "east": 2, "west": 1})
    assert result["failsafe"] is False
    assert result["lane"] == "south"


def test_stale_data_falls_back_to_failsafe():
    fs = make_wrapper(stale_after_seconds=0.2)
    fs.mark_data_received()
    time.sleep(0.3)
    result = fs.run_cycle({"north": 5, "south": 20, "east": 2, "west": 1})
    assert result["failsafe"] is True
    assert "stale" in result["failsafe_reason"]


def test_forced_failsafe_overrides_fresh_data():
    fs = make_wrapper()
    fs.mark_data_received()
    fs.force_failsafe(True)
    result = fs.run_cycle({"north": 5, "south": 20, "east": 2, "west": 1})
    assert result["failsafe"] is True


def test_failsafe_round_robin_covers_every_lane():
    fs = make_wrapper()
    lanes = [fs.run_cycle({})["lane"] for _ in range(4)]
    assert set(lanes) == {"north", "south", "east", "west"}


def test_failsafe_ignores_vehicle_counts_and_emergency():
    fs = make_wrapper()
    # even with a huge count and an emergency lane, failsafe mode must NOT use them
    result = fs.run_cycle({"east": 999}, emergency_lane="east")
    assert result["was_emergency"] is False
    assert result["vehicle_count"] == 0
