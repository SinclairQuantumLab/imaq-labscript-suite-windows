"""Common integration plumbing; the numbered scripts contain the actual lessons.

Reuse the real connection table, including its channel names and defaults.
No new Labscript devices are added and no connection-table properties are changed.
The QUA config and replay metadata are per-shot data, as allowed by the OPX driver.
"""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import labscript as lab
from qm import qua
from user_devices.opx.qua_tick_programs import qua_section
from user_devices.opx.tick_segment_compile import qua_wait_scaled_cycles

from opx_configuration import (
    CLOCK_ELEMENTS, SECTION_ELEMENTS, TICK_NS, make_config,
)

# The override is for offline validation or a copied folder, not normally needed.
CONNECTION_TABLE = Path(os.environ.get(
    "QUA_TESTING_CONNECTION_TABLE",
    str(Path(__file__).resolve().parent.parent / "connection_table.py"),
))


def setup():
    """Construct the supplied apparatus afresh for this compilation."""
    spec = importlib.util.spec_from_file_location("qua_learning_table", CONNECTION_TABLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ConnectionTable()
    devices = {device.name: device for device in lab.compiler.inventory}
    ct = SimpleNamespace(**devices)
    expected = {
        "c1_AO30": ("ni_pxie_6738_1", "ao30"),
        #"c2_AO0": ("ni_pxie_6738_2", "ao0"),
        "do0": ("ni_pxie_6535", "port0/line0"),
        "ni_pxie_6738_1_clock": ("opx_main_pseudoclock", "flag 0"),
        #"ni_pxie_6738_2_clock": ("opx_main_pseudoclock", "flag 6"),
        "ni_pxie_6535_clock": ("opx_main_pseudoclock", "flag 1"),
    }
    for name, (parent, connection) in expected.items():
        device = devices[name]
        if device.parent_device.name != parent or device.connection != connection:
            raise ValueError(f"Unexpected connection for {name}; check the learning guide")

    ct.opx_main.qm_config = make_config()
    ct.opx_main.set_execution_mode("execute")
    lines = {
        "analog": ct.ni_pxie_6738_1_clock,
        "analog2": ct.ni_pxie_6738_2_clock,
        "digital": ct.ni_pxie_6535_clock,
    }
    playbacks = {}
    for label, line in lines.items():
        stream = f"learning_{label}_tick_times"
        playbacks[label] = ct.opx_main.enable_inline_tick_playback(
            tick_element=CLOCK_ELEMENTS[label],
            tick_operation="tick",
            tick_pulse_cycles=TICK_NS // 4,
            timestamp_stream_name=stream,
            clock_line=line,
        )
        ct.opx_main.add_result_trace(
            handle=f"{stream}_values",
            trace_name=f"learning_{label}_ticks",
            sample_period=0.0,
            timestamp_handle=stream,
            timestamp_scale=4e-9,
            clock_line=line,
        )
        ct.opx_main.add_result_trace(
            handle=f"learning_{label}_completion_times",
            trace_name=f"learning_{label}_completion_cycles",
            sample_period=0.0,
            clock_line=line,
        )
    return ct, playbacks


def begin(ct, playbacks):
    """Prepare streams and give both NI cards at least four buffered samples."""
    for playback in playbacks.values():
        playback.qua_prepare_tick_playback()
    lab.start()
    ct.c1_AO30.constant(0.0, 0.0)
    ct.do0.go_low(0.0)
    # The full apparatus has nonzero AO and shutter defaults, so its NI tasks
    # stay buffered even when these test outputs never change. Generic finite
    # timing needs >=2 samples, but this PXIe-6535's initial transfer needs >=4
    # samples at StartTask(). The worker drops the final duplicate stop row.
    # Three identical holds plus t=0 provide four uploaded samples per card.
    # These binary-fraction times precede every lesson's first event. Voltages
    # and logic levels do not change at these additional sample-clock edges.


def section(ct, playbacks, name="lesson", t=0.0, duration=1.0, **kwargs):
    """Replay both independent NI clocks concurrently with scope elements."""
    return qua_section(
        ct.opx_main, name, t, duration,
        playback=list(playbacks.values()),
        pre_align=SECTION_ELEMENTS,
        post_align=SECTION_ELEMENTS,
        **kwargs,
    )


def wait_seconds(seconds, element):
    """Convert seconds to 4 ns cycles and split long waits using the driver."""
    from user_devices.opx.qua_tick_programs import qua_wait_chunked
    cycles = round(seconds / 4e-9)
    if abs(cycles * 4e-9 - seconds) > 1e-12:
        raise ValueError("Wait must lie on the 4 ns QUA grid")
    qua_wait_chunked(cycles, element)


def wait_runtime_seconds(seconds, scale, element="clock"):
    """Give a QUA-selected section its full duration, including its final hold."""
    wait_cycles = qua.declare(int)
    qua_wait_scaled_cycles(round(seconds / 4e-9), scale, element, wait_cycles)


def finish(playbacks):
    """Join timelines and supply NI's extra finite-task completion edge.

    The installed segment compiler leaves out the stop(t) tick. NI_DAQmx omits
    the final duplicate data row and some NI devices require one extra edge to
    complete their finite task. Keep this pulse separate from sample replay.
    The 1 ms guard guarantees low time even after a runtime-scaled final tick.
    """
    qua.align("clock", *SECTION_ELEMENTS)
    completions = {}
    for label, element in CLOCK_ELEMENTS.items():
        completions[label] = qua.declare_output_stream()
        qua.wait(250_000, element)
        qua.play("tick", element, timestamp_stream=completions[label])
    with qua.stream_processing():
        for playback in playbacks.values():
            playback.save_tick_trace()
        for label, stream in completions.items():
            stream.save_all(f"learning_{label}_completion_times")
