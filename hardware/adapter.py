"""
Hardware integration layer.

FSM decides "east should be GREEN for 24s" - but turning that into an ACTUAL
traffic light involves talking to physical signal controller hardware, and
every vendor/municipality uses a different protocol:

  - NTCIP 1202 (common in US/some Indian smart-city installs) - usually over
    serial (RS-232/485) or Ethernet, SNMP-based
  - Vendor-proprietary serial/Modbus protocols (very common in India -
    each traffic-signal manufacturer has their own)
  - Simple relay/GPIO boards (small intersections, DIY setups - a Raspberry
    Pi or Arduino driving relays that switch the actual lights)

There is NO way to write one "correct" implementation without knowing which
controller your city/campus actually has - this file gives you the interface
and one that we can genuinely test in a sandbox (LoggingAdapter + a
GPIO-style adapter that works with an actual Raspberry Pi), plus documented
stubs for the other two so you know exactly what to fill in once you have
the hardware manual.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict

from signal_control.fsm_controller import SignalState

logger = logging.getLogger(__name__)


class SignalHardwareAdapter(ABC):
    """Every adapter turns 'this lane is now this SignalState' into a physical action."""

    @abstractmethod
    def apply(self, lane_id: str, state: SignalState) -> bool:
        """Return True if the hardware confirmed the change, False otherwise.
        MUST NOT raise for a routine comms failure - return False so the
        caller can fall back safely; only raise for programmer errors."""

    def apply_all(self, states: Dict[str, SignalState]) -> Dict[str, bool]:
        return {lane: self.apply(lane, state) for lane, state in states.items()}

    def health_check(self) -> bool:
        """Cheap connectivity check. Default: assume healthy (override if the
        real hardware exposes a ping/status call)."""
        return True


class LoggingAdapter(SignalHardwareAdapter):
    """No real hardware - just logs what WOULD happen. Used for local dev/demo
    and is exactly what this project's tests run against."""

    def __init__(self) -> None:
        self.history: list[tuple[str, str]] = []

    def apply(self, lane_id: str, state: SignalState) -> bool:
        self.history.append((lane_id, state.value))
        logger.info("[LoggingAdapter] %s -> %s", lane_id, state.value)
        return True


class GPIOAdapter(SignalHardwareAdapter):
    """
    For a small/DIY intersection: Raspberry Pi GPIO pins driving relays,
    one relay per (lane, colour) - i.e. 4 lanes x 3 colours = 12 pins.

    Needs `RPi.GPIO` installed AND actual Raspberry Pi hardware - this class
    will raise ImportError in any other environment (including this sandbox),
    which is correct: it should never silently pretend to control real relays
    it can't reach.

    pin_map example:
        {
          "north": {"RED": 17, "YELLOW": 27, "GREEN": 22},
          "south": {"RED": 5,  "YELLOW": 6,  "GREEN": 13},
          ...
        }
    """

    def __init__(self, pin_map: Dict[str, Dict[str, int]]) -> None:
        try:
            import RPi.GPIO as GPIO  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "RPi.GPIO not available. GPIOAdapter only runs on an actual "
                "Raspberry Pi wired to relays - use LoggingAdapter for dev/demo."
            ) from exc
        self._gpio = GPIO
        self.pin_map = pin_map
        self._gpio.setmode(GPIO.BCM)
        for lane_pins in pin_map.values():
            for pin in lane_pins.values():
                self._gpio.setup(pin, GPIO.OUT, initial=GPIO.LOW)

    def apply(self, lane_id: str, state: SignalState) -> bool:
        pins = self.pin_map.get(lane_id)
        if pins is None:
            logger.error("No GPIO pins configured for lane '%s'", lane_id)
            return False
        try:
            for colour, pin in pins.items():
                self._gpio.output(pin, self._gpio.HIGH if colour == state.value else self._gpio.LOW)
            return True
        except Exception:  # noqa: BLE001 - any GPIO error is a hardware comms failure, not a crash
            logger.exception("GPIO write failed for lane '%s'", lane_id)
            return False


class NTCIPAdapterStub(SignalHardwareAdapter):
    """
    STUB - documents the shape of an NTCIP 1202 integration; does not
    actually talk to a controller. Fill in `_send()` using your controller's
    manual (SNMP OIDs / serial framing vary by vendor even within NTCIP).

    Typical real implementation uses `pysnmp` (SNMP SET on the controller's
    phase-control OID) or a vendor SDK the controller manufacturer supplies.
    """

    def __init__(self, controller_ip: str, community: str = "public") -> None:
        self.controller_ip = controller_ip
        self.community = community

    def apply(self, lane_id: str, state: SignalState) -> bool:
        logger.warning(
            "NTCIPAdapterStub.apply(%s, %s) called - this is a STUB, no packet was sent. "
            "Wire this method to your controller's actual NTCIP/vendor protocol.",
            lane_id, state.value,
        )
        return False

    def health_check(self) -> bool:
        return False  # stub is never "healthy" - forces failsafe if someone wires it in by mistake
