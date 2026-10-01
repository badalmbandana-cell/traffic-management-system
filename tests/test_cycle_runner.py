import time

from hardware.adapter import LoggingAdapter
from signal_control.cycle_runner import execute_timed_cycle
from signal_control.fsm_controller import FSMController, SignalState


def test_timed_cycle_goes_green_then_yellow_then_red():
    fsm = FSMController(["north", "south", "east", "west"])
    hw = LoggingAdapter()
    result = fsm.run_cycle({"north": 1, "south": 10, "east": 1, "west": 1})
    result["green_duration"] = 0.05  # keep the test fast
    result["yellow_duration"] = 0.05

    transitions = []
    execute_timed_cycle(fsm, hw, result, sleep_fn=time.sleep,
                         on_transition=lambda lane, state: transitions.append((lane, state)))

    assert [s for _, s in transitions] == [SignalState.GREEN, SignalState.YELLOW, SignalState.RED]
    assert all(lane == "south" for lane, _ in transitions)
    assert fsm.get_states()["south"] == SignalState.RED  # ends safely red
    assert hw.history == [("south", "GREEN"), ("south", "YELLOW"), ("south", "RED")]


def test_timed_cycle_respects_actual_durations():
    fsm = FSMController(["a", "b"])
    hw = LoggingAdapter()
    result = {"lane": "a", "green_duration": 0.1, "yellow_duration": 0.1,
              "was_emergency": False, "vehicle_count": 5}

    start = time.monotonic()
    execute_timed_cycle(fsm, hw, result)
    elapsed = time.monotonic() - start

    assert 0.18 <= elapsed <= 0.5  # ~0.2s expected, generous upper bound for CI jitter
