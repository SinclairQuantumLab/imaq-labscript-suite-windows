import os
import subprocess

from blacs.device_base_class import DeviceTab
from blacs.tab_base_classes import define_state, MODE_MANUAL
from qtutils.qt.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel

SERVER_PYTHON = r'C:\Users\imaq\Remote_Devices\spinnaker-camera-server\spinnaker-camera-venv\Scripts\python.exe'
SERVER_SCRIPT = r'C:\Users\imaq\Remote_Devices\spinnaker-camera-server\test_camera_server_zprocess.py'

class RemoteSpinnakerCameraTab(DeviceTab):
    def initialise_GUI(self):
        device = self.settings['connection_table'].find_by_name(self.device_name)

        host, port = device.BLACS_connection.split(':')

        worker_kwargs = {
            'host': host,
            'port': int(port),
        }

        self.create_worker(
            'main_worker',
            'user_devices.RemoteSpinnakerCamera.blacs_workers_zprocess.RemoteSpinnakerCameraZProcessWorker',     #this can change depending on what blacs process is being used
            worker_kwargs,
        )

        self.primary_worker = 'main_worker'

        self.widget = QWidget()
        layout = QVBoxLayout(self.widget)

        self.start_server_button = QPushButton('Start camera server')
        self.start_server_button.clicked.connect(self.start_camera_server)
        layout.addWidget(self.start_server_button)

        self.hardware_trigger_button = QPushButton('Wait for PrawnDO trigger')
        self.hardware_trigger_button.clicked.connect(self.snap_on_hardware_trigger)
        layout.addWidget(self.hardware_trigger_button)

        self.arm_button = QPushButton('Arm continuous trigger capture')
        self.arm_button.clicked.connect(self.arm_hardware_trigger_capture)
        layout.addWidget(self.arm_button)

        self.disarm_button = QPushButton('Disarm trigger capture')
        self.disarm_button.clicked.connect(self.disarm_hardware_trigger_capture)
        layout.addWidget(self.disarm_button)

        self.status_button = QPushButton('Trigger capture status')
        self.status_button.clicked.connect(self.get_hardware_trigger_capture_status)
        layout.addWidget(self.status_button)

        self.status_label = QLabel('Remote Spinnaker camera ready.')
        layout.addWidget(self.status_label)

        self.snap_button = QPushButton('Snap one image')
        self.snap_button.clicked.connect(self.snap_one_image)
        layout.addWidget(self.snap_button)

        self.get_tab_layout().addWidget(self.widget)
    
    def start_camera_server(self, *args):
        if hasattr(self, 'camera_server_process'):
            if self.camera_server_process.poll() is None:
                self.status_label.setText('Camera server is already running.')
                return

        self.camera_server_process = subprocess.Popen(
            [SERVER_PYTHON, SERVER_SCRIPT],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

        self.status_label.setText('Started camera server.')

    @define_state(MODE_MANUAL, True)
    def snap_one_image(self, *args):
        self.status_label.setText('Snapping image...')

        response = yield self.queue_work(
            self.primary_worker,
            'snap_one_image',
        )

        if response.get('ok'):
            image_file = response.get('image_file')
            width = response.get('width')
            height = response.get('height')

            self.status_label.setText(
                f'Saved image: {image_file} ({width} x {height})'
            )

            if image_file and os.path.exists(image_file):
                os.startfile(image_file)
        else:
            self.status_label.setText(f'Error: {response}')
    
    @define_state(MODE_MANUAL, True)
    def snap_on_hardware_trigger(self, *args):
        self.status_label.setText('Waiting for hardware trigger...')

        response = yield self.queue_work(
        self.primary_worker,
        'snap_on_hardware_trigger',
        )

        if response.get('ok'):
            image_file = response.get('image_file')
            width = response.get('width')
            height = response.get('height')

            self.status_label.setText(
                f'Saved hardware-triggered image: {image_file} ({width} x {height})'
            )

            if image_file and os.path.exists(image_file):
                os.startfile(image_file)
        else:
            self.status_label.setText(f'Error: {response}') 

    @define_state(MODE_MANUAL, True)
    def arm_hardware_trigger_capture(self, *args):
        self.status_label.setText('Arming hardware trigger capture...')

        response = yield self.queue_work(
            self.primary_worker,
            'arm_hardware_trigger_capture',
        )

        self.status_label.setText(str(response))


    @define_state(MODE_MANUAL, True)
    def disarm_hardware_trigger_capture(self, *args):
        self.status_label.setText('Disarming hardware trigger capture...')

        response = yield self.queue_work(
            self.primary_worker,
            'disarm_hardware_trigger_capture',
        )

        self.status_label.setText(str(response))


    @define_state(MODE_MANUAL, True)
    def get_hardware_trigger_capture_status(self, *args):
        response = yield self.queue_work(
            self.primary_worker,
            'get_hardware_trigger_capture_status',
        )

        self.status_label.setText(str(response)) 

