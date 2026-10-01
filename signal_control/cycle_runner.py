"""
Timed cycle runner - turns an FSM DECISION into an actual GREEN -> YELLOW -> RED
sequence over real time, pushing each transition to the hardware adapter.

Why this exists: FSMController.run_cycle() / FailsafeFSMWrapper.run_cycle()
compute WHAT should happen (which lane, for how long) instantly - they don't
by themselves make a real light stay green for green_duration seconds and
then turn amber before red. Skipping that step is a serious bug for a REAL
signal (GREEN jumping straight to RED, or the next lane's GREEN starting
before this lane properly ambers off, is exactly the kind of thing that
causes real accidents). This module is what actually waits and transitions.

Two ways to use it:
  1. execute_timed_cycle() - blocking, synchronous. Good for scripts (like
     run_pipeline.py) and for the sandbox test below.
  2. execute_timed_cycle_async() - same logic, but non-blocking (asyncio),
     which is what backend/main.py's background loop uses so the API stays
     responsive while a light is mid-cycle.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Dict, Optional

from hardware.adapter import SignalHardwareAdapter
from signal_control.fsm_controller import FSMController, SignalState


def execute_timed_cycle(
    fsm: FSMController,
    hardware: SignalHardwareAdapter,
    cycle_result: Dict[str, object],
    sleep_fn: Callable[[float], None] = time.sleep,
    on_transition: Optional[Callable[[str, SignalState], None]] = None,
) -> None:
    """
    Blocking: actually walks the selected lane through GREEN -> YELLOW -> RED,
    holding each state for its real duration, pushing every transition to
    the hardware adapter (so a real light genuinely changes colour on time).

    `sleep_fn` is injectable so tests can run this in milliseconds instead
    of real seconds without changing the logic being tested.
    """
    lane = cycle_result["lane"]
    green_s = cycle_result["green_duration"]
    yellow_s = cycle_result["yellow_duration"]

    # GREEN - fsm.run_cycle() (called by the caller BEFORE this) already set
    # every other lane to RED and this lane to GREEN; push that state now.
    fsm.set_state(lane, SignalState.GREEN)
    hardware.apply(lane, SignalState.GREEN)
    if on_transition:
        on_transition(lane, SignalState.GREEN)
    sleep_fn(green_s)

    # YELLOW - the transition this project's FSM was missing.
    fsm.set_state(lane, SignalState.YELLOW)
    hardware.apply(lane, SignalState.YELLOW)
    if on_transition:
        on_transition(lane, SignalState.YELLOW)
    sleep_fn(yellow_s)

    # RED - safe to switch off; the NEXT run_cycle() call will pick (and turn
    # green) whichever lane should go next.
    fsm.set_state(lane, SignalState.RED)
    hardware.apply(lane, SignalState.RED)
    if on_transition:
        on_transition(lane, SignalState.RED)


async def execute_timed_cycle_async(
    fsm: FSMController,
    hardware: SignalHardwareAdapter,
    cycle_result: Dict[str, object],
    on_transition: Optional[Callable[[str, SignalState], None]] = None,
) -> None:
    """Same as execute_timed_cycle but non-blocking - used by the backend's
    background loop so /signal/cycle and other endpoints stay responsive
    while a light is mid-transition."""
    lane = cycle_result["lane"]
    green_s = cycle_result["green_duration"]
    yellow_s = cycle_result["yellow_duration"]

    fsm.set_state(lane, SignalState.GREEN)
    hardware.apply(lane, SignalState.GREEN)
    if on_transition:
        on_transition(lane, SignalState.GREEN)
    await asyncio.sleep(green_s)

    fsm.set_state(lane, SignalState.YELLOW)
    hardware.apply(lane, SignalState.YELLOW)
    if on_transition:
        on_transition(lane, SignalState.YELLOW)
    await asyncio.sleep(yellow_s)

    fsm.set_state(lane, SignalState.RED)
    hardware.apply(lane, SignalState.RED)
    if on_transition:
        on_transition(lane, SignalState.RED)
