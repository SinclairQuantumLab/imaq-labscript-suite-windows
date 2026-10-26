from labscript_utils.device_registry import register_classes

blacs_tab = "user_devices.opx.blacs_tabs.OPXTab"
parser = "user_devices.opx.runviewer_parsers.OPXParser"

register_classes(
    labscript_device_name="OPX",
    BLACS_tab=blacs_tab,
    runviewer_parser=parser,
)
