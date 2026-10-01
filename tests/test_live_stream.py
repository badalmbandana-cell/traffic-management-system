import itertools
import time

import cv2
import numpy as np
import pytest

from detection.live_stream import LiveStream


@pytest.fixture()
def synthetic_video(tmp_path):
    path = str(tmp_path / "synthetic.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (32, 32))
    for i in range(10):
        writer.write(np.full((32, 32, 3), i * 20 % 255, dtype=np.uint8))
    writer.release()
    return path


def test_reads_all_frames_from_valid_source(synthetic_video):
    stream = LiveStream(synthetic_video)
    attempts = list(itertools.islice(stream.frames(), 11))
    real_frames = [f for f in attempts if f is not None]
    assert len(real_frames) == 10
    stream.release()


def test_first_connect_does_not_wait_for_backoff(synthetic_video):
    stream = LiveStream(synthetic_video, initial_backoff_seconds=5.0)
    start = time.monotonic()
    next(stream.frames())
    assert time.monotonic() - start < 1.0
    stream.release()


def test_invalid_source_becomes_failsafe_worthy_without_hanging():
    stream = LiveStream(
        "/nonexistent/path.mp4",
        initial_backoff_seconds=0.01,
        max_backoff_seconds=0.02,
        max_consecutive_failures_before_failsafe=3,
    )
    count = 0
    for frame in stream.frames():
        count += 1
        assert frame is None
        if stream.is_failsafe_worthy:
            break
        assert count <= 10, "should reach failsafe threshold quickly"
    assert stream.is_failsafe_worthy is True
    assert count == 3
