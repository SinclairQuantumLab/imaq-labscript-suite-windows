from labscript_devices import register_classes


register_classes(
    "CustomSpinnakerCamera",
    BLACS_tab=(
        "user_devices.CustomSpinnakerCamera.blacs_tabs."
        "CustomSpinnakerCameraTab"
    ),
    runviewer_parser=None,
)