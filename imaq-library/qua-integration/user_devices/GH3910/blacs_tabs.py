"""Manual BLACS GUI for the G&H 3910 RF driver."""

from qtutils.qt import QtWidgets
from blacs.device_base_class import DeviceTab
from blacs.tab_base_classes import MODE_MANUAL, define_state


class GH3910Tab(DeviceTab):

    def initialise_GUI(self):
        layout = self.get_tab_layout()
        form = QtWidgets.QFormLayout()

        # --------------------
        # Frequency
        # --------------------

        self.frequency = QtWidgets.QDoubleSpinBox()
        self.frequency.setRange(80, 110)
        self.frequency.setDecimals(6)
        self.frequency.setSingleStep(0.01)
        self.frequency.setSuffix(" MHz")
        self.frequency.setValue(100)

        form.addRow("Frequency", self.frequency)

        # --------------------
        # Attenuation
        # --------------------

        self.attenuation = QtWidgets.QSpinBox()
        self.attenuation.setRange(650, 1023)
        self.attenuation.setValue(891)

        form.addRow("Attenuation", self.attenuation)

        # --------------------
        # Modulation mode
        # --------------------

        self.modulation = QtWidgets.QComboBox()
        self.modulation.addItems([
            "analog",
            "digital",
            "combined",
        ])

        form.addRow("RF modulation", self.modulation)

        panel = QtWidgets.QWidget()
        panel.setLayout(form)
        layout.addWidget(panel)

        # --------------------
        # Buttons
        # --------------------

        refresh = QtWidgets.QPushButton("Read from hardware")
        apply = QtWidgets.QPushButton("Apply settings")

        layout.addWidget(refresh)
        layout.addWidget(apply)

        # --------------------
        # Status
        # --------------------

        self.status = QtWidgets.QLabel(
            "Read from hardware to initialise values"
        )

        layout.addWidget(self.status)
        layout.addStretch()

        refresh.clicked.connect(self.refresh)
        apply.clicked.connect(self.apply)

    def initialise_workers(self):
        device = self.settings[
            "connection_table"
        ].find_by_name(self.device_name)

        serial_number = int(
            device.properties["serial_number"]
        )

        self.create_worker(
            "main_worker",
            "user_devices.GH3910.blacs_workers.GH3910Worker",
            {
                "serial_number": serial_number,
            },
        )

        self.primary_worker = "main_worker"

    @define_state(MODE_MANUAL, True)
    def refresh(self, *args):
        settings = yield self.queue_work(
            self.primary_worker,
            "read_settings",
        )

        self.frequency.setValue(settings["frequency_mhz"])
        self.attenuation.setValue(settings["attenuation"])
        self.modulation.setCurrentText(
            settings["modulation_mode"]
        )

        self.status.setText(
            f"Hardware: {settings['frequency_mhz']:.6f} MHz / "
            f"{settings['attenuation']} / "
            f"{settings['modulation_mode']}"
        )

    @define_state(MODE_MANUAL, True)
    def apply(self, *args):
        desired = {
            "frequency_mhz": self.frequency.value(),
            "attenuation": self.attenuation.value(),
            "modulation_mode": self.modulation.currentText(),
        }

        settings = yield self.queue_work(
            self.primary_worker,
            "apply_settings",
            desired,
        )

        self.frequency.setValue(settings["frequency_mhz"])
        self.attenuation.setValue(settings["attenuation"])
        self.modulation.setCurrentText(
            settings["modulation_mode"]
        )

        self.status.setText(
            f"Hardware: {settings['frequency_mhz']:.6f} MHz / "
            f"{settings['attenuation']} / "
            f"{settings['modulation_mode']}"
        )