from labscript_devices import register_classes

register_classes(
    'PicoScope2405A',
    BLACS_tab='user_devices.PicoScope2405A.blacs_tabs.PicoScope2405ATab',
    runviewer_parser=None,
)
