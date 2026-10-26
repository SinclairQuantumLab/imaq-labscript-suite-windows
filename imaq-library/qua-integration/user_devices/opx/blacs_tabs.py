from collections.abc import Generator
from queue import Queue

from blacs.device_base_class import (
    MODE_BUFFERED,
    MODE_MANUAL,
    MODE_TRANSITION_TO_BUFFERED,
    MODE_TRANSITION_TO_MANUAL,
    DeviceTab,
    define_state,
)
from qtutils.qt import QtWidgets
from user_devices.opx.qua_manual_programs import (
    ACTIVE_KNOB,
    AMPLITUDE_KNOB,
    DURATION_KNOB,
    FREQUENCY_KNOB,
    KNOB_AO_PROPERTIES,
    OPERATION_KNOB,
    PHASE_KNOB,
    ManualChannelSpec,
    input_stream_name,
    manual_channel_specs_from_connection_table,
)

_MANUAL_STATUS_LABELS = {
    "stopped": "Stopped",
    "waiting": "Waiting",
    "running": "Running",
}


class OPXTab(DeviceTab):
    def initialise_GUI(self) -> None:
        """Build the manual-mode front panel: one widget group per `OPXManualChannel`.

        Labs needing a different manual panel (for example a custom calibration
        or homogenization UI) should subclass `OPXTab` and override
        `create_manual_channel_widgets()` rather than `initialise_GUI()`
        wholesale -- `initialise_workers()` and the status/Start/Stop/Reset
        wiring below don't depend on how the panel looks.
        """
        self.manual_channels: list[ManualChannelSpec] = (
            manual_channel_specs_from_connection_table(
                self.connection_table, self.device_name
            )
        )
        self._operation_combos: dict[str, QtWidgets.QComboBox] = {}

        if self.manual_channels:
            self.get_tab_layout().addWidget(self.create_manual_channel_widgets())
            self.get_tab_layout().addWidget(self.create_manual_status_widget())
            self.statemachine_timeout_add(1000, self.manual_status_monitor)

    def create_manual_channel_widgets(self) -> QtWidgets.QWidget:
        """Build one widget group per declared `OPXManualChannel`.

        Gate/frequency/amplitude/phase/duration are registered as standard
        BLACS digital/analog outputs, so front-panel persistence, locking,
        and push-on-change (`program_device()` -> `OPXWorker.program_manual`)
        all come for free. The operation dropdown deliberately is not one of
        these -- BLACS's AO widgets are numeric only, and encoding an enum as
        an index spinner is poor UX for what should be a dropdown. It pushes
        directly via `on_operation_changed` instead, bypassing
        `get_front_panel_values()` entirely, so it can never trigger the
        `channel not in self._last_programmed_values` check in
        `program_device()`.
        """
        do_properties = {
            input_stream_name(channel.name, ACTIVE_KNOB): {}
            for channel in self.manual_channels
        }
        ao_properties = {
            input_stream_name(channel.name, knob): dict(properties)
            for channel in self.manual_channels
            for knob, properties in KNOB_AO_PROPERTIES.items()
        }
        self.create_digital_outputs(do_properties)
        self.create_analog_outputs(ao_properties)
        do_widgets = self.create_digital_widgets({name: {} for name in do_properties})
        ao_widgets = self.create_analog_widgets({name: {} for name in ao_properties})

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        for channel in self.manual_channels:
            layout.addWidget(
                self._create_manual_channel_group(channel, do_widgets, ao_widgets)
            )
        layout.addStretch()
        return container

    def _create_manual_channel_group(
        self,
        channel: ManualChannelSpec,
        do_widgets: dict[str, QtWidgets.QWidget],
        ao_widgets: dict[str, QtWidgets.QWidget],
    ) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(f"{channel.name} ({channel.kind})")
        layout = QtWidgets.QVBoxLayout(group)
        layout.addWidget(do_widgets[input_stream_name(channel.name, ACTIVE_KNOB)])

        operation_row = QtWidgets.QWidget()
        operation_layout = QtWidgets.QHBoxLayout(operation_row)
        operation_layout.setContentsMargins(0, 0, 0, 0)
        operation_layout.addWidget(QtWidgets.QLabel("Operation"))
        operation_combo = QtWidgets.QComboBox()
        operation_combo.addItems(list(channel.operations))
        operation_combo.currentIndexChanged.connect(
            lambda index, name=channel.name: self.on_operation_changed(name, index)
        )
        operation_layout.addWidget(operation_combo)
        self._operation_combos[channel.name] = operation_combo
        layout.addWidget(operation_row)

        for knob in (FREQUENCY_KNOB, AMPLITUDE_KNOB, PHASE_KNOB, DURATION_KNOB):
            layout.addWidget(ao_widgets[input_stream_name(channel.name, knob)])

        return group

    def create_manual_status_widget(self) -> QtWidgets.QWidget:
        """Build the manual-mode status indicator plus Start/Stop/Reset buttons."""
        group = QtWidgets.QGroupBox("Manual program")
        layout = QtWidgets.QHBoxLayout(group)

        layout.addWidget(QtWidgets.QLabel("Status:"))
        self.manual_status_label = QtWidgets.QLabel("Stopped")
        layout.addWidget(self.manual_status_label)
        layout.addStretch()

        start_button = QtWidgets.QPushButton("Start")
        start_button.clicked.connect(self.on_manual_start_clicked)
        stop_button = QtWidgets.QPushButton("Stop")
        stop_button.clicked.connect(self.on_manual_stop_clicked)
        reset_button = QtWidgets.QPushButton("Reset")
        reset_button.clicked.connect(self.on_manual_reset_clicked)
        for button in (start_button, stop_button, reset_button):
            layout.addWidget(button)

        return group

    def get_save_data(self) -> dict[str, int]:
        return {
            name: combo.currentIndex() for name, combo in self._operation_combos.items()
        }

    def restore_save_data(self, data: dict[str, int]) -> None:
        for name, index in (data or {}).items():
            combo = self._operation_combos.get(name)
            if combo is None or not (0 <= index < combo.count()):
                continue
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def initialise_workers(self) -> None:
        """Create the BLACS worker responsible for OPX runtime execution."""
        self.logger.info("Initialising OPX BLACS worker.")
        self.create_worker(
            "opx_worker",
            "user_devices.opx.blacs_workers.OPXWorker",
            {"manual_channels": self.manual_channels},
        )
        self.primary_worker = "opx_worker"
        if self._operation_combos:
            self.push_operation_selections()

    @define_state(MODE_MANUAL, True)
    def push_operation_selections(self) -> Generator[None, None, None]:
        """Push each channel's current operation selection once at startup.

        Operation dropdowns aren't registered as BLACS AO/DO channels (see
        `create_manual_channel_widgets`), so they don't flow through
        `get_front_panel_values()`/`program_device()` automatically.
        """
        values = {
            input_stream_name(name, OPERATION_KNOB): combo.currentIndex()
            for name, combo in self._operation_combos.items()
        }
        yield self.queue_work(self.primary_worker, "program_manual", values)

    def on_operation_changed(self, channel_name: str, index: int) -> None:
        if index < 0:
            return
        self.push_operation_change(channel_name, index)

    @define_state(MODE_MANUAL, True)
    def push_operation_change(
        self, channel_name: str, index: int
    ) -> Generator[None, None, None]:
        """Push one channel's new operation index (see `create_manual_channel_widgets`)."""
        yield self.queue_work(
            self.primary_worker,
            "program_manual",
            {input_stream_name(channel_name, OPERATION_KNOB): index},
        )

    def on_manual_start_clicked(self) -> None:
        self.run_manual_program_command("start_manual_program")

    def on_manual_stop_clicked(self) -> None:
        self.run_manual_program_command("stop_manual_program")

    def on_manual_reset_clicked(self) -> None:
        self.run_manual_program_command("reset_manual_program")

    @define_state(MODE_MANUAL, True)
    def run_manual_program_command(
        self, worker_method: str
    ) -> Generator[None, None, None]:
        """Run a manual-program lifecycle command, then refresh the status label."""
        yield self.queue_work(self.primary_worker, worker_method)
        self.manual_status_monitor()

    @define_state(
        MODE_MANUAL
        | MODE_BUFFERED
        | MODE_TRANSITION_TO_BUFFERED
        | MODE_TRANSITION_TO_MANUAL,
        True,
    )
    def manual_status_monitor(self) -> Generator[None, None, None]:
        """Poll the worker's manual-program status and update the indicator."""
        status = yield self.queue_work(self.primary_worker, "manual_program_status")
        self.manual_status_label.setText(_MANUAL_STATUS_LABELS.get(status, str(status)))

    @define_state(
        MODE_MANUAL
        | MODE_BUFFERED
        | MODE_TRANSITION_TO_BUFFERED
        | MODE_TRANSITION_TO_MANUAL,
        True,
    )
    def start_run(self, notify_queue: Queue[str]) -> Generator[None, None, None]:
        """Start the OPX job when this device is the primary pseudoclock."""
        self.statemachine_timeout_remove(self.status_monitor)
        yield self.queue_work(self.primary_worker, "start_run")
        self.status_monitor()
        self.statemachine_timeout_add(100, self.status_monitor, notify_queue)

    @define_state(
        MODE_MANUAL
        | MODE_BUFFERED
        | MODE_TRANSITION_TO_BUFFERED
        | MODE_TRANSITION_TO_MANUAL,
        True,
    )
    def status_monitor(
        self, notify_queue: Queue[str] | None = None
    ) -> Generator[None, None, None]:
        """Poll the worker until the active OPX job has finished."""
        status = yield (self.queue_work(self.primary_worker, "check_status"))
        done_condition = status == 0
        if notify_queue is not None and done_condition:
            notify_queue.put("done")
            self.statemachine_timeout_remove(self.status_monitor)
            self.statemachine_timeout_add(2000, self.status_monitor)

    @define_state(MODE_BUFFERED, True)
    def push_tick_playback_time_dilation(
        self, time_dilation: float
    ) -> Generator[None, None, object]:
        """Queue one runtime time-dilation value for an input-stream-controlled section."""
        return (
            yield self.queue_work(
                self.primary_worker,
                "push_tick_playback_time_dilation",
                time_dilation,
            )
        )

    @define_state(MODE_BUFFERED, True)
    def resume_tick_playback(self) -> Generator[None, None, object]:
        """Resume a custom QUA tick program that paused with `qua.pause()`."""
        return (yield self.queue_work(self.primary_worker, "resume_tick_playback"))
