import json
import socket

from blacs.tab_base_classes import Worker


class RemoteSpinnakerCameraWorker(Worker):
    def init(self):
        self.host = self.host
        self.port = int(self.port)

        response = self.request({'cmd': 'ping'})
        print('RemoteSpinnakerCamera ping:', response)

        response = self.request({'cmd': 'test_pyspin'})
        print('RemoteSpinnakerCamera PySpin:', response)

        response = self.request({'cmd': 'list_cameras'})
        print('RemoteSpinnakerCamera cameras:', response)

    def request(self, command):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.host, self.port))
            sock.sendall(json.dumps(command).encode())
            data = sock.recv(65536)

        return json.loads(data.decode())

    def ping(self):
        return self.request({'cmd': 'ping'})

    def list_cameras(self):
        return self.request({'cmd': 'list_cameras'})

    def snap_one_image(self):
        return self.request({'cmd': 'snap_one_image'})

    def program_manual(self, values):
        return {}

    def transition_to_buffered(self, device_name, h5file, initial_values, fresh):
        return {}

    def transition_to_manual(self):
        return True

    def abort(self):
        return True