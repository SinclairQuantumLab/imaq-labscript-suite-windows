import numpy as np
import pyqtgraph as pg

from qtutils.qt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
)

from blacs.device_base_class import DeviceTab
from blacs.tab_base_classes import define_state, MODE_MANUAL


class PicoScope2405ATab(DeviceTab):

    def initialise_GUI(self):
        self.running = False

        container = QWidget()
        outer = QVBoxLayout(container)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start display")
        self.stop_button = QPushButton("Stop display")
        self.status_label = QLabel("Stopped")

        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.status_label)
        controls.addStretch()

        self.plot = pg.PlotWidget()
        self.plot.addLegend()
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "Voltage", units="V")
        self.plot.showGrid(x=True, y=True)

        self.cursor = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#ffffff", width=1),
        )
        self.plot.addItem(self.cursor)
        self.cursor.hide()

        self.plot.scene().sigMouseMoved.connect(self.on_mouse_moved)
        self.plot.scene().sigMouseClicked.connect(self.on_plot_clicked)

        self.display_frozen = False

        colours = ["#ffff00", "#00ffff", "#ff00ff", "#00ff00"]
        self.curves = [
            self.plot.plot(pen=pg.mkPen(colour, width=1.5), name=f"Channel {ch}")
            for colour, ch in zip(colours, "ABCD")
        ]

        outer.addLayout(controls)
        outer.addWidget(self.plot)
        self.get_tab_layout().addWidget(container)

        self.start_button.clicked.connect(self.start_display)
        self.stop_button.clicked.connect(self.stop_display)

    def initialise_workers(self):
        connection_object = self.settings["connection_table"].find_by_name(
            self.device_name
        )

        serial_number = connection_object.BLACS_connection
        if serial_number in (None, "", "None"):
            serial_number = None
        else:
            serial_number = str(serial_number)

        worker_initialisation_kwargs = dict(connection_object.properties)
        worker_initialisation_kwargs["serial_number"] = serial_number

        self.create_worker(
            "main_worker",
            "user_devices.PicoScope2405A.blacs_workers.PicoScope2405AWorker",
            worker_initialisation_kwargs,
        )
        self.primary_worker = "main_worker"

    def on_mouse_moved(self, scene_position):
        if not self.plot.sceneBoundingRect().contains(scene_position):
            self.cursor.hide()
            return

        mouse_point = self.plot.plotItem.vb.mapSceneToView(scene_position)

        self.cursor.setPos(mouse_point.x())
        self.cursor.show()

        self.status_label.setText(
            f"Cursor: {mouse_point.x() * 1e6:.2f} µs, "
            f"{mouse_point.y():.3f} V"
        )

    def on_plot_clicked(self, event):
        if event.button() != 1:
            return

        if self.display_frozen:
            self.display_frozen = False
            self.start_display()
        else:
            self.display_frozen = True
            self.stop_display()
            self.status_label.setText("Frozen — click plot to resume")

    @define_state(MODE_MANUAL, True)
    def start_display(self, checked=False):
        result = yield self.queue_work(self.primary_worker, "start_display")
        self.running = bool(result)
        self.status_label.setText("Running" if self.running else "Failed")

        if self.running:
            self.statemachine_timeout_add(100, self.update_display)

    @define_state(MODE_MANUAL, True, delete_stale_states=True)
    def update_display(self):
        if not self.running or self.display_frozen:
            return

        result = yield self.queue_work(
            self.primary_worker,
            "get_display_waveform",
        )

        if not result:
            return

        t = np.asarray(result["time"])

        for index, channel in enumerate("ABCD"):
            samples = result["channels"].get(channel)
            if samples is None:
                self.curves[index].clear()
            else:
                self.curves[index].setData(
                    t,
                    np.asarray(samples),
                    skipFiniteCheck=True,
                )

        self.status_label.setText(
            f'{result["sample_rate"] / 1e6:.3f} MS/s'
        )

    @define_state(MODE_MANUAL, True)
    def stop_display(self, checked=False):
        self.running = False
        self.statemachine_timeout_remove(self.update_display)
        yield self.queue_work(self.primary_worker, "stop_display")
        self.status_label.setText("Stopped")
