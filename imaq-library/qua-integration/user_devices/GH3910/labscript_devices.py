from labscript import Device, LabscriptError, set_passed_properties


class GH3910(Device):
    description = "G&H 3910 RF Driver (USB serial)"
    allowed_children = []

    @set_passed_properties(
        property_names={
            "connection_table_properties": ["serial_number"]
        }
    )
    def __init__(self, name, serial_number, **kwargs):
        super().__init__(
            name,
            parent_device=None,
            connection=None,
            **kwargs,
        )

        self.BLACS_connection = "auto"
        self.serial_number = int(serial_number)
        self._shot_settings = None

    def configure(
        self,
        frequency_mhz,
        attenuation,
        modulation_mode,
    ):
        """Set the configuration loaded by BLACS before each shot."""

        frequency_mhz = float(frequency_mhz)
        attenuation = int(attenuation)
        modulation_mode = str(modulation_mode).lower()

        if not 80 <= frequency_mhz <= 110:
            raise LabscriptError(
                "GH3910: provisional frequency range is 80–110 MHz"
            )

        if not 650 <= attenuation <= 1023:
            raise LabscriptError(
                "GH3910: attenuation must be 650–1023"
            )

        if modulation_mode not in {
            "analog",
            "digital",
            "combined",
        }:
            raise LabscriptError(
                "GH3910: mode must be analog, digital, or combined"
            )

        self._shot_settings = (
            frequency_mhz,
            attenuation,
            modulation_mode,
        )

    def generate_code(self, hdf5_file):
        super().generate_code(hdf5_file)

        group = self.init_device_group(hdf5_file)

        if self._shot_settings is None:
            group.attrs["has_settings"] = False

        else:
            frequency, attenuation, mode = self._shot_settings

            group.attrs["has_settings"] = True
            group.attrs["frequency_mhz"] = frequency
            group.attrs["attenuation"] = attenuation
            group.attrs["modulation_mode"] = mode