from labscript_utils.device_registry import register_classes

register_classes(
    labscript_device_name="FakeVoltageGenerator",
    BLACS_tab=("labscript_devices.DummyIntermediateDevice.DummyIntermediateDeviceTab"),
    runviewer_parser=None,
)
