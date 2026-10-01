import pytest

from hardware.adapter import GPIOAdapter, LoggingAdapter, NTCIPAdapterStub
from signal_control.fsm_controller import SignalState


def test_logging_adapter_records_and_confirms():
    adapter = LoggingAdapter()
    assert adapter.apply("east", SignalState.GREEN) is True
    assert adapter.history == [("east", "GREEN")]


def test_logging_adapter_apply_all():
    adapter = LoggingAdapter()
    result = adapter.apply_all({"north": SignalState.RED, "east": SignalState.GREEN})
    assert result == {"north": True, "east": True}
    assert ("north", "RED") in adapter.history
    assert ("east", "GREEN") in adapter.history


def test_gpio_adapter_raises_without_real_hardware():
    # We are NOT on a Raspberry Pi in this sandbox/CI - this must raise
    # ImportError rather than silently pretending to drive relays.
    with pytest.raises(ImportError):
        GPIOAdapter(pin_map={"north": {"RED": 17, "YELLOW": 27, "GREEN": 22}})


def test_ntcip_stub_never_reports_healthy_and_never_confirms():
    stub = NTCIPAdapterStub("10.0.0.5")
    assert stub.health_check() is False
    assert stub.apply("north", SignalState.GREEN) is False
