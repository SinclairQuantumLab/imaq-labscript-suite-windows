# FakeVoltageGenerator

Compile-only test harness for OPX pseudoclock tick playback. **Not a real
instrument driver** — it does not control hardware or expose a BLACS worker.

## Purpose

`FakeVoltageGenerator` lets reference experiments schedule dense pseudoclock tick
trains without wiring a physical voltage source. Calling
`start_voltage_ramp()` compiles one tick per ramp sample on the parent clock
line; the OPX pseudoclock replays those ticks as TTL pulses so you can verify
timing against the expected ramp timeline.

The apparatus examples use it for multi-clock-line and tick-only smoke tests.
Replace it with your own devices when building a production apparatus.

## What it does not do

- No hardware I/O (voltages are not applied anywhere).
- No BLACS worker — registration uses `DummyIntermediateDeviceTab` only.
- `blacs_connection="fake_voltage_generator"` is a placeholder string, not a
  serial port or instrument address.

## Usage

Attach to an OPX `clock_line` (or any pseudoclock parent) in your connection
table:

```python
from user_devices.fake_voltage_generator.labscript_devices import FakeVoltageGenerator

fake_voltage_gen = FakeVoltageGenerator(
    "fake_voltage_gen",
    parent_device=opx_main.clock_line,
    clock_limit=100,
    voltage_limits=(-5.0, 5.0),
    default_voltage=0.0,
)
```

In an experiment script:

```python
fake_voltage_gen.start_voltage_ramp(
    t,
    duration=2.0,
    initial=0.0,
    final=1.0,
    samplerate=100,
)
```

See `labscriptlib.opx_apparatus.connection_table`, `config_opx.py`, and the
multi-clock-line experiments for full examples.
