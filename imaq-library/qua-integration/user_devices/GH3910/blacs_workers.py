"""BLACS worker controlling G&H 3910 via NI-VISA/PyVISA."""

import labscript_utils.h5_lock
import h5py

from blacs.tab_base_classes import Worker
from .gh3910 import GH3910


class GH3910Worker(Worker):

    def init(self):
        self.driver_context = GH3910(
            serial_number=self.serial_number
        )

        self.driver = self.driver_context.__enter__()

        self.saved_manual_settings = None

    def read_settings(self):
        return {
            "frequency_mhz": self.driver.get_frequency(),
            "attenuation": self.driver.get_attenuation(),
            "modulation_mode": self.driver.get_modulation_mode(),
        }

    def apply_settings(self, requested):
        current = self.read_settings()

        # --------------------
        # Frequency
        # --------------------

        if (
            "frequency_mhz" in requested
            and abs(
                current["frequency_mhz"]
                - float(requested["frequency_mhz"])
            ) > 1e-6
        ):
            self.driver.set_frequency(
                float(requested["frequency_mhz"]),
                confirm=True,
            )

        # --------------------
        # Attenuation
        # --------------------

        if (
            "attenuation" in requested
            and current["attenuation"]
            != int(requested["attenuation"])
        ):
            self.driver.set_attenuation(
                int(requested["attenuation"])
            )

        # --------------------
        # Modulation mode
        # --------------------

        if (
            "modulation_mode" in requested
            and current["modulation_mode"]
            != requested["modulation_mode"]
        ):
            self.driver.set_modulation_mode(
                requested["modulation_mode"]
            )

        return self.read_settings()

    def program_manual(self, front_panel_values):
        # Manual controls use custom BLACS buttons.
        return {}

    def check_remote_values(self):
        return {}

    def transition_to_buffered(
        self,
        device_name,
        h5_file,
        initial_values,
        fresh,
    ):
        # Save existing manual settings before applying shot settings.
        self.saved_manual_settings = self.read_settings()

        with h5py.File(h5_file, "r") as f:
            attrs = f[f"devices/{device_name}"].attrs

            if not bool(attrs["has_settings"]):
                return {}

            mode = attrs["modulation_mode"]

            if isinstance(mode, bytes):
                mode = mode.decode()

            settings = {
                "frequency_mhz": float(attrs["frequency_mhz"]),
                "attenuation": int(attrs["attenuation"]),
                "modulation_mode": str(mode),
            }

        # Applied before the shot starts.
        self.apply_settings(settings)

        return {}

    def transition_to_manual(self, abort=False):
        if self.saved_manual_settings is not None:
            self.apply_settings(
                self.saved_manual_settings
            )

            self.saved_manual_settings = None

        return True

    def abort_transition_to_buffered(self):
        return self.transition_to_manual(abort=True)

    def abort_buffered(self):
        return self.transition_to_manual(abort=True)

    def shutdown(self):
        if getattr(self, "driver_context", None) is not None:
            self.driver_context.__exit__(
                None,
                None,
                None,
            )

            self.driver_context = None