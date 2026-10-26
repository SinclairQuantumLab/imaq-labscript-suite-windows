
from zprocess import ZMQClient 

from blacs.tab_base_classes import Worker


#this blacs worker uses zprocess to communicate with a remote spinnaker camera server. the original blacs_workers.py was kept for debugging purposes, but this worker is the one that should be used with the RemoteSpinnakerCameraServer because it is the method recommended by labscipt.


class RemoteSpinnakerCameraZProcessWorker(Worker):
    def init(self):
        
        self.port = int(self.port)
        self.client = ZMQClient(allow_insecure=True)
        
        try:
            print('RemoteSpinnakerCamera ping', self.ping())
            print('RemoteSpinnakerCamera PySpin', self.request({'cmd': 'test_pyspin'}))
            print('RemoteSpinnakerCamera cameras:', self.list_cameras())
        except Exception as e:
            print('RemoteSpinnakerCamera server not available yet:', e)

    def request(self, command, timeout=10):
        return self.client.get(
            self.port,
            host = self.host, 
            data=command,
            timeout=timeout
        )

    def ping(self):
        return self.request({'cmd': 'ping'})

    def list_cameras(self):
        return self.request({'cmd': 'list_cameras'})
    
    def arm_hardware_trigger_capture(self):
        return self.request({'cmd': 'arm_hardware_trigger_capture'}, timeout=10)

    def disarm_hardware_trigger_capture(self):
        return self.request({'cmd': 'disarm_hardware_trigger_capture'}, timeout=10)

    def get_hardware_trigger_capture_status(self):
        return self.request({'cmd': 'get_hardware_trigger_capture_status'}, timeout=5)

    def snap_one_image(self):
        return self.request({'cmd': 'snap_one_image'}, timeout=30)
    
    def snap_on_hardware_trigger(self):
        return self.request(
            {'cmd': 'snap_on_hardware_trigger'},
            timeout=15,
    )

    def program_manual(self, values):
        return {}

    def transition_to_buffered(self, device_name, h5file, initial_values, fresh):
        return {}

    def transition_to_manual(self):
        return True

    def abort(self):
        return True