"""Human-readable QUA program dumps for compile-time and BLACS debugging."""

from __future__ import annotations

from qm import Program
from qm.serialization.qua_serializing_visitor import QuaSerializingVisitor


def format_qua_program(program: Program) -> str:
    """Return a serialized QUA program suitable for console inspection."""
    visitor = QuaSerializingVisitor()
    visitor.visit(program.qua_program)
    return visitor.out()


def print_qua_program(
    program: Program | None,
    *,
    device_name: str,
    stage: str = "before OPX execution",
) -> None:
    """Print the final QUA program to stdout."""
    if program is None:
        return
    print(f"\n=== QUA program for {device_name} ({stage}) ===\n")
    print(format_qua_program(program))
    print(f"\n=== end QUA program for {device_name} ===\n")
