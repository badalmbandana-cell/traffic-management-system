"""
Fail-safe wrapper around FSMController.

Real traffic-light control is a life-safety system: agar camera down ho jaaye,
detection pipeline crash kare, ya network se fresh data na aaye, signal ko
BAND nahi karna chahiye - usse ek safe, predictable, fixed-duration round-robin
pattern pe girna chahiye (jaisa purana fixed-timer signal karta tha), jab tak
fresh data wapas na aaye.

Yeh class khud koi detection/FSM logic repeat nahi karti - woh FSMController
ka kaam hai. Yeh sirf EK decision leti hai: "abhi FSM (density-based) trust
karoon, ya fixed round-robin pe fallback karoon?"
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from signal_control.fsm_controller import FSMController


@dataclass
class FailsafeStatus:
    healthy: bool
    reason: str
    seconds_since_last_update: Optional[float]
    mode: str  # "normal" or "failsafe"


class FailsafeFSMWrapper:
    """
    FSMController ke around ek safety layer.

    stale_after_seconds - itni der tak /detection/update na aaye toh data
                           'stale' maana jaata hai aur failsafe mode chalu.
    fixed_green_seconds  - failsafe mode mein har lane ko itna green milta hai.
    """

    def __init__(
        self,
        fsm: FSMController,
        stale_after_seconds: float = 30.0,
        fixed_green_seconds: int = 20,
    ) -> None:
        self.fsm = fsm
        self.stale_after_seconds = stale_after_seconds
        self.fixed_green_seconds = fixed_green_seconds
        self._last_update_ts: Optional[float] = None
        self._round_robin_index = 0
        self._forced_failsafe = False  # e.g. detection process itself crashed

    # ---------------------------------------------------------- data freshness
    def mark_data_received(self) -> None:
        """Backend har successful /detection/update pe isse call kare."""
        self._last_update_ts = time.monotonic()

    def force_failsafe(self, on: bool = True) -> None:
        """Detection pipeline crash/health-check-fail hone par backend isse call kare."""
        self._forced_failsafe = on

    def status(self) -> FailsafeStatus:
        if self._forced_failsafe:
            return FailsafeStatus(False, "detection pipeline reported unhealthy", None, "failsafe")
        if self._last_update_ts is None:
            return FailsafeStatus(False, "no detection data received yet", None, "failsafe")
        age = time.monotonic() - self._last_update_ts
        if age > self.stale_after_seconds:
            return FailsafeStatus(False, f"detection data stale ({age:.1f}s old)", age, "failsafe")
        return FailsafeStatus(True, "ok", age, "normal")

    # -------------------------------------------------------------- cycling
    def run_cycle(
        self, lane_counts: Dict[str, int], emergency_lane: Optional[str] = None
    ) -> Dict[str, object]:
        """
        Normal mode  -> FSMController.run_cycle() (density + emergency logic)
        Failsafe mode -> fixed-duration round-robin, IGNORES vehicle_count/emergency
                         (koi bharosemand data hi nahi hai unpar decision lene ke liye)
        """
        st = self.status()
        if st.healthy:
            result = self.fsm.run_cycle(lane_counts, emergency_lane=emergency_lane)
            result["failsafe"] = False
            result["failsafe_reason"] = None
            return result
        return self._fixed_round_robin_cycle(st.reason)

    def _fixed_round_robin_cycle(self, reason: str) -> Dict[str, object]:
        lane = self.fsm.lane_ids[self._round_robin_index % len(self.fsm.lane_ids)]
        self._round_robin_index += 1
        for l in self.fsm.lane_ids:
            self.fsm.set_state(l, self.fsm.states[l].__class__.RED)
        self.fsm.set_state(lane, self.fsm.states[lane].__class__.GREEN)
        return {
            "lane": lane,
            "green_duration": self.fixed_green_seconds,
            "yellow_duration": self.fsm.yellow_duration,
            "was_emergency": False,
            "vehicle_count": 0,
            "failsafe": True,
            "failsafe_reason": reason,
        }
