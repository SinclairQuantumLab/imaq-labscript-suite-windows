#####################################################################
#                                                                   #
# Copyright 2019, Monash University and contributors                #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################



from blacs.device_base_class import DeviceTab, define_state
from qtutils.qt.QtCore import*
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *
from PyQt5.QtWidgets import QGridLayout, QLabel

class NICounterTab(DeviceTab):
    def initialise_GUI ( self ):
        """
        Initializes the GUI tab for the NICounter
        """

        layout = self.get_tab_layout()
        row = QGridLayout()

        self.ready_acquisition = QPushButton()
        self.ready_acquisition.setText("Ready Acquisition")
        self.ready_acquisition.setStyleSheet("border :1px solid black")
        row.addWidget(self.ready_acquisition, 0, 0)

        self.read_data = QPushButton()
        self.read_data.setText("Read")
        self.read_data.setStyleSheet("border :1px solid black")
        row.addWidget(self.read_data, 0, 1)

        self.triggers_label = QLabel()
        self.triggers_label.setText("Triggers: None")
        row.addWidget(self.triggers_label, 0, 2)

        self.data_label = QLabel()
        self.data_label.setText("Counts: None")
        row.addWidget(self.data_label, 1, 0)

        layout.addLayout(row)

        self.ready_acquisition.clicked.connect(self.ready_acquisition_worker)
        self.read_data.clicked.connect(self.read_data_worker)

    MODE_MANUAL = 1
    @define_state(MODE_MANUAL,True)  
    def ready_acquisition_worker(self, btn):
        """Prepare the NI counter card for acquisition: see worker method

        Args:
            btn (QPushButton): the button that was pressed


        """

        results = yield(self.queue_work('main_worker','ready_acquisition',))


    @define_state(MODE_MANUAL,True)  
    def read_data_worker(self, btn):
        """Read data from the NI counter card see worker method

        Args:
            btn (QPushButton): the button that was pressed

        """

        counts, triggers = yield(self.queue_work('main_worker','read_data',))
        self.data_label.setText("Counts: {}".format(counts))
        self.triggers_label.setText("Triggers: {}".format(triggers))



    def initialise_workers(self):
        connection_table = self.settings['connection_table']
        device = connection_table.find_by_name(self.device_name)

        self.MAX_name = device.properties['MAX_name']
        self.counter_channel = device.properties['counter_channel']
        self.input_channel = device.properties['input_channel']
        self.gate_channel = device.properties['gate_channel']

        # Create and set the primary worker
        self.create_worker(
            'main_worker',
            'user_devices.NICounter.blacs_workers.NICounterWorker',
            {
                'MAX_name': self.MAX_name,
                'counter_channel': self.counter_channel,
                'input_channel': self.input_channel,
                'gate_channel': self.gate_channel
                
            },
        )
        self.primary_worker = 'main_worker'

