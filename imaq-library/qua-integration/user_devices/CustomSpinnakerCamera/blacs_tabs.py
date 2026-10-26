from pathlib import Path

from qtutils.qt import QtWidgets
from blacs.tab_base_classes import define_state, MODE_MANUAL

from labscript_devices.SpinnakerCamera.blacs_tabs import SpinnakerCameraTab


class CustomSpinnakerCameraTab(SpinnakerCameraTab):

    worker_class = (
        "user_devices.CustomSpinnakerCamera.blacs_workers."
        "CustomSpinnakerCameraWorker"
    )

    save_directory = Path(
        r"C:\Users\imaq\labscript-suite\userlib\analysislib\Spinnaker FLIR Camera Manual Snaps"
    )

    def initialise_GUI(self):
        # Build the normal Spinnaker camera interface:
        super().initialise_GUI()

        # Add the custom Save Snap button:
        self.save_snap_button = QtWidgets.QPushButton(
            "Save Snap"
        )

        self.save_snap_button.clicked.connect(
            self.on_save_snap_clicked
        )

        # Existing layout:
        #
        # Attributes
        # Snap
        # Continuous
        #
        # Insert Save Snap between Snap and Continuous.
        self.ui.verticalLayout.insertWidget(
            2,
            self.save_snap_button,
        )

    def on_save_snap_clicked(self):
        self.save_snap()

    @define_state(
        MODE_MANUAL,
        queue_state_indefinitely=True,
        delete_stale_states=True,
    )
    def save_snap(self):
        yield self.queue_work(
            self.primary_worker,
            "snap_and_save",
            str(self.save_directory),
        )

    def on_continuous_clicked(self, button):
        # Saving a single snap while continuous acquisition is active
        # would conflict with the camera acquisition state.
        self.save_snap_button.setEnabled(False)

        super().on_continuous_clicked(button)

    def on_stop_clicked(self, button):
        super().on_stop_clicked(button)

        self.save_snap_button.setEnabled(True)
