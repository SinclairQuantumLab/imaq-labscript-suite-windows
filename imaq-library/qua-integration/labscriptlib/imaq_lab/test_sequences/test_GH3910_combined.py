"""GH3910 combined-mode test with sufficient buffered samples on each NI card.

Uses do9 for the digital modulation input and c2_AO11 for the analog input.
The expected gating assumes a HIGH digital input enables the RF output.
"""

import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

test_gh3910_aom_driver.configure(
    frequency_mhz=100.0,
    attenuation=891,
    modulation_mode="combined",
)

lab.start()

# Keep c1_AO0 at its default throughout. Repeat holds on each card's separate
# clock line so that all three cards receive enough buffered samples.

# 0 s: initialize with the digital gate LOW and analog modulation at zero.
c1_AO0.constant(0.0, 0.0)
c2_AO11.constant(0.0, 0.0)
do9.go_low(0.0)

# 0.5 s: hold the same values to provide another buffered sample.
c1_AO0.constant(0.5, 0.0)
c2_AO11.constant(0.5, 0.0)
do9.go_low(0.5)

# 1 s: set the digital gate HIGH, leaving analog modulation at zero.
c1_AO0.constant(1.0, 0.0)
c2_AO11.constant(1.0, 0.0)
do9.go_high(1.0)

# 2 s: increase analog modulation to 0.1 V.
c1_AO0.constant(2.0, 0.0)
c2_AO11.constant(2.0, 0.1)
do9.go_high(2.0)

# 3 s: increase analog modulation to 0.2 V.
c1_AO0.constant(3.0, 0.0)
c2_AO11.constant(3.0, 0.2)
do9.go_high(3.0)

# 4 s: increase analog modulation to 0.3 V.
c1_AO0.constant(4.0, 0.0)
c2_AO11.constant(4.0, 0.3)
do9.go_high(4.0)

# 5 s: check digital gating while the analog input remains at 0.3 V.
c1_AO0.constant(5.0, 0.0)
c2_AO11.constant(5.0, 0.3)
do9.go_low(5.0)

# 10 s: reset analog modulation to zero and keep the digital gate LOW.
c1_AO0.constant(10.0, 0.0)
c2_AO11.constant(10.0, 0.0)
do9.go_low(10.0)

# Leave time for the final reset before stopping.
lab.stop(10.1)
