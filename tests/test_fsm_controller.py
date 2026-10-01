import pytest

from signal_control.fsm_controller import FSMController, SignalState


def make_fsm(**kw):
    return FSMController(["north", "south", "east", "west"], **kw)


def test_green_time_scales_and_clamps():
    fsm = make_fsm(min_green=10, max_green=60)
    assert fsm.calculate_green_time(0) == 10        # clamp low
    assert fsm.calculate_green_time(5) == 10         # 5*2=10, at the floor
    assert fsm.calculate_green_time(20) == 40        # 20*2=40, mid-range
    assert fsm.calculate_green_time(100) == 60       # clamp high


def test_selects_highest_density_lane():
    fsm = make_fsm()
    counts = {"north": 4, "south": 15, "east": 8, "west": 3}
    assert fsm.select_next_lane(counts) == "south"


def test_emergency_always_overrides_density():
    fsm = make_fsm()
    counts = {"north": 4, "south": 15, "east": 8, "west": 3}
    result = fsm.run_cycle(counts, emergency_lane="west")
    assert result["lane"] == "west"
    assert result["was_emergency"] is True


def test_run_cycle_resets_other_lanes_to_red():
    fsm = make_fsm()
    result = fsm.run_cycle({"north": 1, "south": 1, "east": 10, "west": 1})
    states = fsm.get_states()
    assert states[result["lane"]] == SignalState.GREEN
    for lane, state in states.items():
        if lane != result["lane"]:
            assert state == SignalState.RED


def test_unknown_lane_rejected():
    fsm = make_fsm()
    with pytest.raises(ValueError):
        fsm.select_next_lane({"unknown": 5})


def test_negative_count_rejected():
    fsm = make_fsm()
    with pytest.raises(ValueError):
        fsm.calculate_green_time(-1)


def test_duplicate_lane_ids_rejected():
    with pytest.raises(ValueError):
        FSMController(["north", "north"])


def test_starvation_forces_a_quiet_lane_eventually():
    fsm = make_fsm(starvation_limit=3)
    counts = {"north": 1, "south": 20, "east": 1, "west": 1}
    picks = [fsm.run_cycle(counts)["lane"] for _ in range(4)]
    # south wins repeatedly, but by the 4th cycle someone else must have starved in
    assert set(picks[:3]) == {"south"}
    assert picks[3] != "south" or len(set(picks)) > 1
