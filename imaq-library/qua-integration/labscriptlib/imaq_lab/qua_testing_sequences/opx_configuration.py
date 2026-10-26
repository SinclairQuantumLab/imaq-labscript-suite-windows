"""Physical OPX routes for every lesson; no hardware connection happens here.

All ports are (controller, LF-FEM slot, output). Digital marker routing is
called digitalInputs in the QM config because it describes the receiving element.
The 'clock' element is used by the integration to wait between section boundaries.
Its AO1 has zero offset and is never played. Only AO3 plays an analog waveform.
"""

from copy import deepcopy

CLOCK_ELEMENTS = {"analog": "ni_analog_clock", "analog2": "ni_analog2_clock", "digital": "ni_digital_clock"}
SCOPE_DIGITAL = "scope_digital"
SCOPE_ANALOG = "scope_analog"
SECTION_ELEMENTS = [*CLOCK_ELEMENTS.values(), SCOPE_DIGITAL, SCOPE_ANALOG]
TICK_NS = 1_000  # 1 us high; NI examples use sample rates of 1 kHz or less.
ANALOG_PULSE_NS = 100_000  # 100 us, nominal +0.1 V with direct LF-FEM output.

READOUT_AI = 1  # Detector -> con1, LF-FEM slot 3, ANALOG INPUT 1.
READOUT_ELEMENT = SCOPE_ANALOG  # Reuse existing AO3; readout plays ZERO there.
READOUT_NS = 2_000
READOUT_TIME_OF_FLIGHT_NS = 100  # Starting value from reference; calibrate on bench.

CONFIG = {
    "controllers": {
        "con1": {
            "type": "opx1000",
            "fems": {
                3: {
                    "type": "LF",
                    "analog_outputs": {
                        1: {"offset": 0.0, "output_mode": "direct"},
                        3: {"offset": 0.0, "output_mode": "direct"},
                        7: {"offset": 0.0, "output_mode": "direct"},
                        6: {"offset": 0.0, "output_mode": "direct"},
                    },
                    "digital_outputs": {1: {}, 6:{}, 7: {}, 8: {}},
                    "analog_inputs": {
                        READOUT_AI: {"offset": 0.0, "gain_db": 0},
                    },
                }
            },
        }
    },
    "elements": {
        "clock": {"singleInput": {"port": ("con1", 3, 1)}},
        "ni_analog_clock": {
            "digitalInputs": {
                "marker": {"port": ("con1", 3, 7), "delay": 0, "buffer": 0}
            },
            "operations": {"tick": "ni_tick_pulse"},
            "singleInput": {"port": ("con1", 3, 7)},
        },
        "ni_analog2_clock": {
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 3, 6),
                    "delay": 0,
                    "buffer": 0,
                }
            },
            "operations": {"tick": "ni_clock2_pulse"},
        },
        "ni_digital_clock": {
            "digitalInputs": {
                "marker": {"port": ("con1", 3, 8), "delay": 0, "buffer": 0}
            },
            "operations": {"tick": "ni_tick_pulse"},
            "singleInput": {"port": ("con1", 3, 6)},
        },
        "scope_digital": {
            "digitalInputs": {
                "marker": {"port": ("con1", 3, 1), "delay": 0, "buffer": 0}
            },
            "operations": {"high": "scope_digital_pulse"},
        },
        "scope_analog": {
            "singleInput": {"port": ("con1", 3, 3)},
            "operations": {
                "pulse": "scope_analog_pulse",
                "read": "detector_readout_pulse",
            },
            "outputs": {"out1": ("con1", 3, READOUT_AI)},
            "time_of_flight": READOUT_TIME_OF_FLIGHT_NS,
            "smearing": 0,
        },
    },
    "pulses": {
        "ni_tick_pulse": {
            "operation": "control",
            "length": TICK_NS,
            "digital_marker": "high_marker",
            "waveforms": {"single": "marker_wf"},
        },
        "ni_clock2_pulse": {
            "operation": "control",
            "length": TICK_NS,
            "digital_marker": "high_marker",
        },
        "scope_digital_pulse": {
            "operation": "control",
            "length": ANALOG_PULSE_NS,
            "digital_marker": "high_marker",
        },
        "scope_analog_pulse": {
            "operation": "control",
            "length": ANALOG_PULSE_NS,
            "waveforms": {"single": "small_voltage"},
        },
        "detector_readout_pulse": {
            "operation": "measurement",
            "length": READOUT_NS,
            "waveforms": {"single": "readout_zero"},
            "integration_weights": {"ones": "detector_ones"},
        },
    },
    "waveforms": {
        "small_voltage": {"type": "constant", "sample": 0.5},
        "readout_zero": {"type": "constant", "sample": 0.0},
        "marker_wf": {"type": "constant", "sample": 0.2}
        },
    "digital_waveforms": {"high_marker": {"samples": [(1, 0)]}},
    "integration_weights": {
        "detector_ones": {
            "cosine": [(1.0, READOUT_NS)],
            "sine": [(0.0, READOUT_NS)],
        },
    },
}


def make_config():
    return deepcopy(CONFIG)
