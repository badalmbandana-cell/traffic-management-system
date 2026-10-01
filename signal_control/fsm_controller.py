"""
Module 2 - Finite-State-Machine signal controller.

The FSM answers three questions each cycle:
  1. WHO gets the green?      -> select_next_lane()
  2. For HOW LONG?            -> calculate_green_time()
  3. What are the light states afterwards? -> run_cycle()

Rules (as per the project brief)
  * green time   = vehicle_count * 2 seconds, clamped to [min_green, max_green]
  * normal pick  = lane with the highest vehicle count
  * emergency    = an emergency lane ALWAYS wins, regardless of density

Two small, optional extras (both keep the original behaviour by default):
  * starvation_limit - a lane that was skipped this many cycles in a row is
    forced next, so a quiet lane cannot wait forever behind busy ones.
    Default None = OFF = pure "highest count wins".
  * ties are broken in favour of the lane that has waited longest.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable, List, Optional


class SignalState(Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"


class FSMController:
    def __init__(
        self,
        lane_ids: Iterable[str],
        min_green: int = 10,
        max_green: int = 60,
        yellow_duration: int = 3,
        starvation_limit: Optional[int] = None,
    ) -> None:
        lanes: List[str] = list(lane_ids)
        if not lanes:
            raise ValueError("lane_ids must contain at least one lane")
        if len(set(lanes)) != len(lanes):
            raise ValueError("lane_ids must be unique")
        if min_green <= 0 or yellow_duration <= 0:
            raise ValueError("min_green and yellow_duration must be positive")
        if min_green > max_green:
            raise ValueError("min_green cannot be greater than max_green")
        if starvation_limit is not None and starvation_limit < 1:
            raise ValueError("starvation_limit must be >= 1 (or None to disable)")

        self.lane_ids = lanes
        self.min_green = min_green
        self.max_green = max_green
        self.yellow_duration = yellow_duration
        self.starvation_limit = starvation_limit

        # Every lane starts RED; nobody has been skipped yet.
        self.states: Dict[str, SignalState] = {lane: SignalState.RED for lane in lanes}
        self._skipped: Dict[str, int] = {lane: 0 for lane in lanes}

    # ------------------------------------------------------------------ helpers
    def _require_known_lane(self, lane: str) -> None:
        if lane not in self.states:
            raise ValueError(f"Unknown lane '{lane}'. Known lanes: {self.lane_ids}")

    def _validate_counts(self, lane_counts: Dict[str, int]) -> None:
        for lane, count in lane_counts.items():
            self._require_known_lane(lane)
            if count < 0:
                raise ValueError(f"Vehicle count for lane '{lane}' cannot be negative")

    # ------------------------------------------------------------- public API
    def calculate_green_time(self, vehicle_count: int) -> int:
        """vehicle_count * 2, bounded to [min_green, max_green]."""
        if vehicle_count < 0:
            raise ValueError("vehicle_count cannot be negative")
        return max(self.min_green, min(self.max_green, vehicle_count * 2))

    def select_next_lane(
        self, lane_counts: Dict[str, int], emergency_lane: Optional[str] = None
    ) -> str:
        """Pick the next lane to turn green (does NOT change any state)."""
        if emergency_lane is not None:
            self._require_known_lane(emergency_lane)
            return emergency_lane

        self._validate_counts(lane_counts)

        if self.starvation_limit is not None:
            starved = [l for l in self.lane_ids if self._skipped[l] >= self.starvation_limit]
            if starved:
                return max(starved, key=lambda l: (self._skipped[l], lane_counts.get(l, 0)))

        # Highest count wins; on a tie the lane that waited longest wins.
        return max(self.lane_ids, key=lambda l: (lane_counts.get(l, 0), self._skipped[l]))

    def run_cycle(
        self, lane_counts: Dict[str, int], emergency_lane: Optional[str] = None
    ) -> Dict[str, object]:
        """Reset all lanes to RED, turn the selected lane GREEN, return the plan."""
        lane = self.select_next_lane(lane_counts, emergency_lane)
        vehicle_count = lane_counts.get(lane, 0)
        green_duration = self.calculate_green_time(vehicle_count)

        for l in self.lane_ids:
            self.states[l] = SignalState.RED
            self._skipped[l] += 1
        self.states[lane] = SignalState.GREEN
        self._skipped[lane] = 0

        return {
            "lane": lane,
            "green_duration": green_duration,
            "yellow_duration": self.yellow_duration,
            "was_emergency": emergency_lane is not None,
            "vehicle_count": vehicle_count,  # extra key, handy for logging
        }

    # ------------------------------------------------------- state accessors
    def set_state(self, lane: str, state: SignalState) -> None:
        self._require_known_lane(lane)
        self.states[lane] = state

    def get_states(self) -> Dict[str, SignalState]:
        return dict(self.states)

    @property
    def active_lane(self) -> Optional[str]:
        """The lane currently GREEN or YELLOW (None when everything is RED)."""
        for lane, state in self.states.items():
            if state in (SignalState.GREEN, SignalState.YELLOW):
                return lane
        return None
