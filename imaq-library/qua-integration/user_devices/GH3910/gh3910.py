"""G&H 3910 RF driver using PyVISA and NI-VISA.

Developed with G&H 3910 firmware 1.11, S/N 14523.

Frequency programming uses an experimentally validated
20 MHz reference configuration and a fixed /32 divider.

The frequency encoder remains provisional for 80–110 MHz.
"""

from __future__ import annotations

import re
import os
import configparser
import msvcrt
import tempfile
import time

from contextlib import contextmanager
from pathlib import Path
from fractions import Fraction

import pyvisa
from pyvisa.constants import Parity, StopBits, StatusCode
from pyvisa.errors import VisaIOError


# ==================================================
# Discovery lock
# ==================================================

@contextmanager
def gh3910_discovery_lock(timeout=60.0):
    """Serialize USB discovery across BLACS worker processes."""

    path = (
        Path(tempfile.gettempdir())
        / "gh3910_discovery.lock"
    )

    with open(path, "a+b") as file:

        if path.stat().st_size == 0:
            file.write(b"\0")
            file.flush()

        deadline = time.monotonic() + timeout

        while True:
            try:
                file.seek(0)

                msvcrt.locking(
                    file.fileno(),
                    msvcrt.LK_NBLCK,
                    1,
                )

                break

            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "Timed out waiting for GH3910 discovery lock"
                    )

                time.sleep(0.1)

        try:
            yield

        finally:
            file.seek(0)

            msvcrt.locking(
                file.fileno(),
                msvcrt.LK_UNLCK,
                1,
            )


# ==================================================
# USB / VISA discovery
# ==================================================

def find_gh3910_resources(rm):
    """Find NI-VISA resources belonging to G&H USB devices.

    Uses the observed G&H USB VID/PID and the NI-VISA
    serial resource mapping.

    Does not query unrelated instrument types.
    """

    if os.name != "nt":
        raise RuntimeError(
            "Automatic discovery currently requires Windows"
        )

    import winreg

    usb_key = (
        r"SYSTEM\CurrentControlSet\Enum\USB"
        r"\VID_1F46&PID_1102"
    )

    ports = set()

    # ------------------------------------------
    # Find G&H COM ports in Windows
    # ------------------------------------------

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            usb_key,
        ) as parent:

            count = winreg.QueryInfoKey(parent)[0]

            for index in range(count):
                instance = winreg.EnumKey(
                    parent,
                    index,
                )

                try:
                    with winreg.OpenKey(
                        parent,
                        instance + r"\Device Parameters",
                    ) as params:

                        name = winreg.QueryValueEx(
                            params,
                            "PortName",
                        )[0]

                        if re.fullmatch(
                            r"COM\d+",
                            name,
                            re.IGNORECASE,
                        ):
                            ports.add(name.upper())

                except OSError:
                    continue

    except FileNotFoundError:
        pass

    if not ports:
        raise RuntimeError(
            "No G&H USB serial ports found "
            "(VID_1F46 PID_1102)"
        )

    # ------------------------------------------
    # Read NI-VISA COM-to-ASRL mappings
    # ------------------------------------------

    path = (
        Path(
            os.environ.get(
                "PROGRAMDATA",
                r"C:\ProgramData",
            )
        )
        / "National Instruments"
        / "NIvisa"
        / "visaconf.ini"
    )

    if not path.is_file():
        raise RuntimeError(
            f"NI-VISA configuration file not found: {path}"
        )

    conf = configparser.ConfigParser(
        interpolation=None
    )

    conf.optionxform = str

    conf.read(
        path,
        encoding="utf-8-sig",
    )

    section_name = "ASRL-RSRC-ALIAS"

    if not conf.has_section(section_name):
        raise RuntimeError(
            f"NI-VISA serial alias section not found in {path}"
        )

    section = conf[section_name]
    resources = set()

    for key, port in section.items():

        match = re.fullmatch(
            r"SystemName(\d+)",
            key,
        )

        if not match:
            continue

        index = match.group(1)

        if port.strip('"').upper() not in ports:
            continue

        if section.get(
            "Enabled" + index,
            "1",
        ) != "1":
            continue

        resource = section.get(
            "Name" + index,
            "",
        ).strip('"').upper()

        if re.fullmatch(
            r"ASRL\d+::INSTR",
            resource,
        ):
            resources.add(resource)

    # ------------------------------------------
    # Restrict to VISA's available resources
    # ------------------------------------------

    available = {
        resource.upper()
        for resource in rm.list_resources("?*")
    }

    candidates = sorted(
        resources.intersection(available)
    )

    if not candidates:
        raise RuntimeError(
            f"G&H COM port(s) {sorted(ports)} "
            f"have no available NI-VISA mapping in {path}"
        )

    return candidates


# ==================================================
# Hardware driver
# ==================================================

class GH3910:

    MODES = {
        "combined": 1,
        "analog": 2,
        "digital": 3,
    }

    REVERSE_MODES = {
        value: key
        for key, value in MODES.items()
    }

    REFERENCE_MHZ = 20.0
    OUTPUT_DIVIDER = 32

    BASE_REGISTERS = {
        0: 0x00500000,
        1: 0x00008011,
        2: 0x18004F42,
        3: 0x004004B3,
        4: 0x00DA003C,
        5: 0x00580005,
    }

    def __init__(
        self,
        resource: str | None = None,
        serial_number: int | None = None,
    ):
        self.resource_name = resource

        if serial_number is None:
            raise ValueError(
                "serial_number is required"
            )

        self.expected_serial = int(serial_number)

        self.rm = None
        self.device = None

    # ==================================================
    # Connect
    # ==================================================

    def __enter__(self):
        self.rm = pyvisa.ResourceManager()

        try:
            with gh3910_discovery_lock():

                if self.resource_name is not None:
                    candidates = [
                        self.resource_name
                    ]
                else:
                    candidates = find_gh3910_resources(
                        self.rm
                    )

                failures = []

                for resource in candidates:
                    matched = False

                    try:
                        self.device = self.rm.open_resource(
                            resource
                        )

                        self.device.baud_rate = 9600
                        self.device.data_bits = 8
                        self.device.parity = Parity.none
                        self.device.stop_bits = StopBits.one

                        self.device.write_termination = "\n"
                        self.device.read_termination = "\n"
                        self.device.timeout = 500

                        actual_serial = self.get_serial_number()

                        if actual_serial == self.expected_serial:
                            matched = True

                            self.resource_name = resource

                            print(
                                f"GH3910 S/N {actual_serial} "
                                f"connected via {resource}",
                                flush=True,
                            )

                            return self

                        failures.append(
                            f"{resource}: S/N {actual_serial}"
                        )

                    except Exception as exc:
                        failures.append(
                            f"{resource}: {exc}"
                        )

                    finally:
                        if (
                            not matched
                            and self.device is not None
                        ):
                            self.device.close()
                            self.device = None

                raise RuntimeError(
                    f"GH3910 serial number "
                    f"{self.expected_serial} not found. "
                    f"Discovery results: {failures}"
                )

        except BaseException:
            self.close()
            raise

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        self.close()
        return False

    def close(self):
        try:
            if self.device is not None:
                self.device.close()

        finally:
            self.device = None

            if self.rm is not None:
                self.rm.close()
                self.rm = None

    # ==================================================
    # Serial communication
    # ==================================================

    def _query_lines(self, command: str) -> list[str]:

        if self.device is None:
            raise RuntimeError(
                "Open the GH3910 in a 'with' block first"
            )

        self.device.write(command)

        lines = []

        # The firmware echoes the command first.
        # Then it returns one or multiple response lines.

        while True:
            try:
                line = (
                    self.device.read()
                    .replace("\x00", "")
                    .strip()
                )

            except VisaIOError as exc:
                if exc.error_code == StatusCode.error_timeout:
                    break
                raise

            if line:
                lines.append(line)

        if not lines:
            raise RuntimeError(
                f"No response to {command!r}"
            )

        return lines

    def _response(self, command: str) -> str:

        lines = self._query_lines(command)

        # Remove the echoed command.
        lines = [
            line
            for line in lines
            if line.lower() != command.lower()
        ]

        if not lines:
            raise RuntimeError(
                f"Only command echo received for {command!r}"
            )

        if any(
            "error" in line.lower()
            for line in lines
        ):
            raise RuntimeError(
                f"Instrument error for {command!r}: {lines}"
            )

        return "\n".join(lines)

    @staticmethod
    def _extract(
        pattern: str,
        text: str,
        label: str,
    ) -> str:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match is None:
            raise RuntimeError(
                f"Unable to parse {label}: {text!r}"
            )

        return match.group(1)

    # ==================================================
    # Device identification
    # ==================================================

    def get_serial_number(self) -> int:

        response = self._response("get sn")

        return int(
            self._extract(
                r"Serial Number:\s*(\d+)",
                response,
                "serial",
            )
        )

    def get_firmware(self) -> str:

        response = self._response("get ver")

        return self._extract(
            r"FW Version\s*=\s*([\d.]+)",
            response,
            "firmware",
        )

    # ==================================================
    # Attenuation
    # ==================================================

    def get_attenuation(self) -> int:

        response = self._response("get atten")

        return int(
            self._extract(
                r"Attenuator Setting is\s*(\d+)",
                response,
                "attenuation",
            )
        )

    def set_attenuation(self, value: int) -> int:

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 650 <= value <= 1023
        ):
            raise ValueError(
                "Attenuation must be an integer from 650 to 1023"
            )

        acknowledgement = self._response(
            f"set atten {value}"
        )

        if not re.search(
            rf"Attenuator Setting Set to\s*{value}\b",
            acknowledgement,
            re.IGNORECASE,
        ):
            raise RuntimeError(
                "Unexpected attenuation acknowledgement: "
                f"{acknowledgement}"
            )

        actual = self.get_attenuation()

        if actual != value:
            raise RuntimeError(
                f"Attenuation readback mismatch: "
                f"{actual} != {value}"
            )

        return actual

    # ==================================================
    # Modulation mode
    # ==================================================

    def get_modulation_mode(self) -> str:

        response = self._response("get SW")

        state = int(
            self._extract(
                r"SW state is\s*(\d+)",
                response,
                "mode",
            )
        )

        if state not in self.REVERSE_MODES:
            raise RuntimeError(
                f"Unknown modulation state: {state}"
            )

        return self.REVERSE_MODES[state]

    def set_modulation_mode(self, mode: str) -> str:

        mode = mode.lower()

        if mode not in self.MODES:
            raise ValueError(
                "Mode must be one of: "
                f"{', '.join(self.MODES)}"
            )

        state = self.MODES[mode]

        acknowledgement = self._response(
            f"set SW {state}"
        )

        if not re.search(
            rf"SW set to\s*{state}\b",
            acknowledgement,
            re.IGNORECASE,
        ):
            raise RuntimeError(
                "Unexpected modulation acknowledgement: "
                f"{acknowledgement}"
            )

        actual = self.get_modulation_mode()

        if actual != mode:
            raise RuntimeError(
                f"Mode readback mismatch: {actual} != {mode}"
            )

        return actual

    # ==================================================
    # Synthesizer registers
    # ==================================================

    def get_registers(self) -> dict[int, int]:

        response = self._response("get R0")

        registers = {
            int(index): int(value, 16)
            for index, value in re.findall(
                r"R([0-5])\s*=\s*0x([0-9A-Fa-f]+)",
                response,
            )
        }

        if set(registers) != set(range(6)):
            raise RuntimeError(
                f"Incomplete register readback: {response}"
            )

        return registers

    # ==================================================
    # Decode frequency
    # ==================================================

    @classmethod
    def decode_frequency(
        cls,
        registers: dict[int, int],
    ) -> float:

        r0, r1, r2, r4 = (
            registers[i]
            for i in (0, 1, 2, 4)
        )

        integer = (r0 >> 15) & 0xFFFF
        fraction = (r0 >> 3) & 0xFFF
        modulus = (r1 >> 3) & 0xFFF

        divider = 2 ** ((r4 >> 20) & 0x7)

        ref_counter = (r2 >> 14) & 0x3FF
        doubler = (r2 >> 25) & 1
        div2 = (r2 >> 24) & 1

        if modulus == 0 or ref_counter == 0:
            raise RuntimeError(
                "Invalid synthesizer divider/modulus"
            )

        pfd = (
            cls.REFERENCE_MHZ
            * (1 + doubler)
            / (ref_counter * (1 + div2))
        )

        return (
            pfd
            * (integer + fraction / modulus)
            / divider
        )

    def get_frequency(self) -> float:
        """Read programmed RF frequency in MHz."""

        return self.decode_frequency(
            self.get_registers()
        )

    # ==================================================
    # Calculate registers
    # ==================================================

    @classmethod
    def calculate_registers(
        cls,
        frequency_mhz: float,
    ) -> dict[int, int]:

        if not 80 <= frequency_mhz <= 110:
            raise ValueError(
                "Frequency outside provisional 80–110 MHz range"
            )

        n = (
            Fraction(str(frequency_mhz))
            * Fraction(cls.OUTPUT_DIVIDER, 20)
        )

        integer = n.numerator // n.denominator

        fractional = (
            n - integer
        ).limit_denominator(4095)

        frac = fractional.numerator
        mod = fractional.denominator if frac else 2

        if (
            not 23 <= integer <= 65535
            or not 2 <= mod <= 4095
            or frac >= mod
        ):
            raise ValueError(
                "Invalid frequency divider values"
            )

        registers = cls.BASE_REGISTERS.copy()

        # R0: INT and FRAC
        registers[0] = (
            (
                registers[0]
                & ~((0xFFFF << 15) | (0xFFF << 3))
            )
            | (integer << 15)
            | (frac << 3)
        )

        # R1: MOD
        registers[1] = (
            (
                registers[1]
                & ~(0xFFF << 3)
            )
            | (mod << 3)
        )

        # R2 and R3: integer-N vs fractional-N
        if frac == 0:
            registers[2] |= 1 << 8
            registers[3] |= 1 << 22

        else:
            registers[2] &= ~(1 << 8)
            registers[3] &= ~(1 << 22)

        return registers

    # ==================================================
    # Program frequency
    # ==================================================

    def set_frequency(
        self,
        frequency_mhz: float,
        *,
        confirm: bool = False,
    ) -> float:

        if not confirm:
            raise ValueError(
                "Frequency writes require confirm=True"
            )

        registers = self.calculate_registers(
            frequency_mhz
        )

        predicted = self.decode_frequency(
            registers
        )

        if abs(predicted - frequency_mhz) > 0.005:
            raise ValueError(
                f"Requested {frequency_mhz} MHz "
                "not closely representable; "
                f"predicted {predicted}"
            )

        # Write R5 through R0.
        for index in range(5, -1, -1):

            cmd = (
                f"set R{index} "
                f"{registers[index]:X}"
            )

            reply = self._response(cmd)

            if not re.search(
                r"\bOK\b|\bset\b|\bR[0-5]\b",
                reply,
                re.IGNORECASE,
            ):
                raise RuntimeError(
                    f"Unexpected register-write response "
                    f"to {cmd}: {reply}"
                )

        actual_regs = self.get_registers()

        if actual_regs != registers:
            raise RuntimeError(
                "Frequency register mismatch: "
                f"expected {registers}, "
                f"got {actual_regs}"
            )

        return self.decode_frequency(
            actual_regs
        )


# ==================================================
# Standalone read-only test
# ==================================================

if __name__ == "__main__":

    with GH3910(serial_number=14523) as driver:

        print(
            "Serial number:",
            driver.get_serial_number(),
        )

        print(
            "Firmware:",
            driver.get_firmware(),
        )

        print(
            "Frequency (MHz):",
            driver.get_frequency(),
        )

        print(
            "Attenuation:",
            driver.get_attenuation(),
        )

        print(
            "Modulation mode:",
            driver.get_modulation_mode(),
        )