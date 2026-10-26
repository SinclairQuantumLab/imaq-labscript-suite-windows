from labscript_devices import register_classes


register_classes(
    'RemoteSpinnakerCamera',
    BLACS_tab='user_devices.RemoteSpinnakerCamera.blacs_tabs.RemoteSpinnakerCameraTab',
    runviewer_parser=None,
)