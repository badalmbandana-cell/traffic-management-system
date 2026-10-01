from detection.lane_mapper import build_vertical_zones, assign_lane, count_per_lane


def test_build_vertical_zones_splits_evenly():
    zones = build_vertical_zones(["a", "b"], frame_width=100, frame_height=50)
    assert zones["a"] == (0, 0, 50, 50)
    assert zones["b"] == (50, 0, 100, 50)


def test_assign_lane_by_center_point():
    zones = build_vertical_zones(["left", "right"], frame_width=100, frame_height=50)
    assert assign_lane((0, 0, 20, 20), zones) == "left"     # center x=10
    assert assign_lane((60, 0, 90, 20), zones) == "right"   # center x=75


def test_count_per_lane():
    zones = build_vertical_zones(["left", "right"], frame_width=100, frame_height=50)
    detections = [
        {"bbox": (0, 0, 20, 20)},
        {"bbox": (5, 5, 25, 25)},
        {"bbox": (60, 0, 90, 20)},
    ]
    counts = count_per_lane(detections, zones)
    assert counts == {"left": 2, "right": 1}
