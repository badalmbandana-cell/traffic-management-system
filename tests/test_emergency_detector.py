from detection.emergency_detector import EmergencyTracker


def make_tracker(**kw):
    return EmergencyTracker(["north", "south", "east", "west"], **kw)


def test_single_frame_does_not_trigger():
    t = make_tracker(trigger_frames=5)
    assert t.update("east", True) is False
    assert t.get_emergency_lane() is None


def test_sustained_detection_triggers():
    t = make_tracker(trigger_frames=5)
    for _ in range(4):
        t.update("east", True)
    assert t.get_emergency_lane() is None          # 4 hits: not yet
    t.update("east", True)                          # 5th hit
    assert t.get_emergency_lane() == "east"


def test_flicker_resets_the_streak():
    t = make_tracker(trigger_frames=5)
    for _ in range(4):
        t.update("east", True)
    t.update("east", False)                         # breaks the streak
    for _ in range(4):
        t.update("east", True)                       # only 4 again
    assert t.get_emergency_lane() is None


def test_release_requires_sustained_absence():
    t = make_tracker(trigger_frames=3, release_frames=4)
    for _ in range(3):
        t.update("east", True)
    assert t.get_emergency_lane() == "east"
    for _ in range(3):
        t.update("east", False)
    assert t.get_emergency_lane() == "east"          # still active, only 3 misses
    t.update("east", False)                          # 4th miss
    assert t.get_emergency_lane() is None


def test_oldest_emergency_wins_when_two_active():
    t = make_tracker(trigger_frames=2)
    for _ in range(2):
        t.update("east", True)                        # active first
    for _ in range(2):
        t.update("west", True)                         # active second
    assert t.get_emergency_lane() == "east"


def test_unknown_lane_raises():
    t = make_tracker()
    try:
        t.update("nowhere", True)
        assert False, "expected ValueError"
    except ValueError:
        pass
