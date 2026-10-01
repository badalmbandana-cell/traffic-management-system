"""
Live camera feed (RTSP/USB/file) with automatic reconnect.

Real CCTV/traffic cameras drop frames aur connections lose karte hain
(network blip, camera reboot, etc). Plain `cv2.VideoCapture` isse handle
nahi karta - ek baar read fail hone pe woh forever fail deta rehta hai.
Yeh class stream ko background mein monitor karti hai aur automatically
reconnect karti hai, exponential backoff ke saath (taaki dead camera ko
har 10ms pe hammer na kare).

Usage:
    stream = LiveStream("rtsp://192.168.1.50:554/stream1")
    for frame in stream.frames():
        ...

Works identically for:
    - RTSP camera:  "rtsp://user:pass@ip:554/stream"
    - USB webcam:    0  (integer device index)
    - video file:    "data/sample_videos/traffic.mp4"   (useful for testing
                      the reconnect logic without a real camera)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterator, Optional, Union

import cv2

logger = logging.getLogger(__name__)

Source = Union[str, int]


@dataclass
class StreamStats:
    frames_read: int = 0
    reconnects: int = 0
    consecutive_failures: int = 0
    last_frame_ts: Optional[float] = None


class LiveStream:
    def __init__(
        self,
        source: Source,
        read_timeout_seconds: float = 5.0,
        max_backoff_seconds: float = 30.0,
        initial_backoff_seconds: float = 1.0,
        max_consecutive_failures_before_failsafe: int = 10,
    ) -> None:
        self.source = source
        self.read_timeout_seconds = read_timeout_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.initial_backoff_seconds = initial_backoff_seconds
        self.max_consecutive_failures_before_failsafe = max_consecutive_failures_before_failsafe

        self.stats = StreamStats()
        self._cap: Optional[cv2.VideoCapture] = None
        self._backoff = initial_backoff_seconds

    # ------------------------------------------------------------- lifecycle
    def _open(self) -> bool:
        if self._cap is not None:
            self._cap.release()
        cap = cv2.VideoCapture(self.source)
        if isinstance(self.source, str) and self.source.startswith("rtsp"):
            # Buffer size 1: purana stale frame nahi, hamesha latest frame chahiye
            # for real-time signal decisions (RTSP-specific backend flag).
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok = cap.isOpened()
        self._cap = cap if ok else None
        return ok

    def _try_reconnect_once(self) -> bool:
        """One (re)connect attempt. Waits `backoff` first, UNLESS this is the very
        first attempt ever (nothing to back off from yet)."""
        is_first_attempt = self.stats.reconnects == 0
        if not is_first_attempt:
            logger.warning("Stream '%s' disconnected, retrying in %.1fs...", self.source, self._backoff)
            time.sleep(self._backoff)
        self.stats.reconnects += 1
        if self._open():
            logger.info("Stream '%s' connected.", self.source)
            self._backoff = self.initial_backoff_seconds  # reset on success
            self.stats.consecutive_failures = 0
            return True
        self._backoff = min(self._backoff * 2, self.max_backoff_seconds)  # exponential backoff
        self.stats.consecutive_failures += 1
        return False

    @property
    def is_failsafe_worthy(self) -> bool:
        """True when the caller should treat detection as unavailable (tell FailsafeFSMWrapper)."""
        return self.stats.consecutive_failures >= self.max_consecutive_failures_before_failsafe

    # ------------------------------------------------------------------ read
    def frames(self) -> Iterator[Optional["cv2.typing.MatLike"]]:
        """
        Infinite generator. On a good read it yields a frame; on a failed read
        (or while reconnecting) it yields None instead of blocking silently -
        this is IMPORTANT: it hands control back to the caller every attempt,
        so the caller can check `is_failsafe_worthy`, log, update a health
        endpoint, or `break` out cleanly instead of the generator looping
        forever on its own with the caller stuck waiting.
        """
        while True:
            if self._cap is None:
                self._try_reconnect_once()
                yield None
                continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                self.stats.consecutive_failures += 1
                logger.debug("Frame read failed (%d consecutive).", self.stats.consecutive_failures)
                self._cap.release()
                self._cap = None
                yield None
                continue

            self.stats.consecutive_failures = 0
            self.stats.frames_read += 1
            self.stats.last_frame_ts = time.monotonic()
            yield frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
