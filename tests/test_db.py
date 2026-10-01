import tempfile
from pathlib import Path

from database.db import count_logs, get_logs, init_db, log_cycle_result


def test_log_and_read_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "test.db"
        init_db(db_path)
        log_cycle_result(
            {"lane": "north", "vehicle_count": 7, "green_duration": 14, "was_emergency": False},
            db_path=db_path,
        )
        log_cycle_result(
            {"lane": "east", "vehicle_count": 2, "green_duration": 10, "was_emergency": True},
            db_path=db_path,
        )
        logs = get_logs(db_path=db_path)
        assert len(logs) == 2
        assert logs[0]["lane_id"] == "east"          # most recent first
        assert logs[0]["is_emergency"] == 1
        assert count_logs(db_path=db_path) == 2


def test_filter_by_lane():
    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "test.db"
        init_db(db_path)
        for lane in ["north", "east", "north"]:
            log_cycle_result(
                {"lane": lane, "vehicle_count": 1, "green_duration": 10, "was_emergency": False},
                db_path=db_path,
            )
        assert count_logs(lane_id="north", db_path=db_path) == 2
        assert count_logs(lane_id="east", db_path=db_path) == 1


def test_pagination():
    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "test.db"
        init_db(db_path)
        for i in range(5):
            log_cycle_result(
                {"lane": "north", "vehicle_count": i, "green_duration": 10, "was_emergency": False},
                db_path=db_path,
            )
        page1 = get_logs(limit=2, offset=0, db_path=db_path)
        page2 = get_logs(limit=2, offset=2, db_path=db_path)
        assert [r["id"] for r in page1] == [5, 4]
        assert [r["id"] for r in page2] == [3, 2]
