"""Compile-only fake voltage generator for pseudoclock tick testing."""

from labscript import AnalogOut
from labscript_devices.DummyIntermediateDevice import DummyIntermediateDevice


class FakeVoltageGenerator(DummyIntermediateDevice):
    """Fake voltage source with a ramp API for pseudoclock tick tests.

    The device does not talk to hardware. Labscript compiles
    :meth:`start_voltage_ramp` into pseudoclock ticks on the parent clock line,
    which the OPX can replay as TTL pulses.
    """

    description = "Fake voltage generator"
    clock_limit = 100e3

    def __init__(
        self,
        name,
        parent_device,
        clock_limit=100e3,
        voltage_limits=(-10.0, 10.0),
        default_voltage=0.0,
        blacs_connection="fake_voltage_generator",
        **kwargs,
    ):
        self.clock_limit = clock_limit
        self.BLACS_connection = blacs_connection
        DummyIntermediateDevice.__init__(self, name, parent_device, **kwargs)
        self.voltage_out = AnalogOut(
            f"{name}_out",
            parent_device=self,
            connection="voltage_out",
            default_value=default_voltage,
            limits=voltage_limits,
        )

    def start_voltage_ramp(
        self,
        t,
        duration,
        initial,
        final,
        samplerate=None,
        units=None,
    ):
        """Start a linear voltage ramp and return its duration in seconds."""
        if samplerate is None:
            samplerate = self.clock_limit
        return self.voltage_out.ramp(
            t,
            duration,
            initial,
            final,
            samplerate,
            units=units,
        )
