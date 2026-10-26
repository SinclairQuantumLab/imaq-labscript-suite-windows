from labscript import TriggerableDevice, set_passed_properties


class RemoteSpinnakerCamera(TriggerableDevice):
    description = 'Remote Spinnaker Camera'

    @set_passed_properties(
        property_names={
            'connection_table_properties': [
                'server_host',
                'server_port',
                'camera_index',
                'trigger_edge_type',
            ]
        }
    )
    def __init__(
        self,
        name,
        parent_device,
        connection,
        server_host='127.0.0.1',
        server_port=51000,
        camera_index=0,
        trigger_edge_type='rising',
        **kwargs,
    ):
        TriggerableDevice.__init__(
            self,
            name,
            parent_device,
            connection,
            **kwargs,
        )

        self.server_host = server_host
        self.server_port = server_port
        self.camera_index = camera_index
        self.trigger_edge_type = trigger_edge_type

        self.BLACS_connection = f'{server_host}:{server_port}'

    def expose(self, t, duration):
        self.trigger(t, duration)

    def generate_code(self, hdf5_file):
        TriggerableDevice.generate_code(self, hdf5_file)