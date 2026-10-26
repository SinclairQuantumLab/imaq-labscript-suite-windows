"""Context manager for one triggered segment inside a single QUA program."""

from collections.abc import Iterator
from contextlib import contextmanager

from labscript import LabscriptError
from qm import qua
from user_devices.opx.labscript_devices import OPX


@contextmanager
def triggered_segment(opx: OPX, name: str, trigger_element: str) -> Iterator[None]:
    """Wrap one wait-for-trigger/act unit inside a single QUA program.

    Emits ``qua.wait_for_trigger(trigger_element)`` followed by ``qua.align()``
    on entry, then ``qua.align()`` again on exit so the segment body is fully
    gated on the trigger and finishes before QUA execution reaches the next
    segment's ``wait_for_trigger``. This is required in a single continuous
    program so each segment is fully synchronized on the external trigger.

    Args:
        opx: The triggered OPX device this program is being built for.
        name: Segment name, for readability at the call site only (e.g. in
            tracebacks); not recorded or validated.
        trigger_element: QUA element wired to the external trigger input that
            the master pulses once per segment.
    """
    if opx._tick_playbacks:
        raise LabscriptError(
            f"OPX device {opx.name} cannot combine triggered_segment(...) with "
            "inline tick playback. triggered_segment() is for the plain "
            "triggered-role QUA program builder (execute / "
            "precompiled_program_id modes with trigger_device set)."
        )
    qua.wait_for_trigger(trigger_element)
    qua.align()
    try:
        yield
    finally:
        qua.align()
