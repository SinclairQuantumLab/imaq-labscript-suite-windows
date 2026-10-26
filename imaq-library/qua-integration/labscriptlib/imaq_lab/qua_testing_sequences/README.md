# OPX1000 + NI learning sequences

Ten increasingly involved sequences for the existing
`labscriptlib/imaq_lab/connection_table.py`. Select the numbered `.py` files in
runmanager, compile them, and queue the resulting shots to BLACS.
No replacement connection table or runmanager globals file is needed.

## Wiring used by every lesson

| Signal | Physical output | Destination / Labscript name |
| --- | --- | --- |
| NI analog sample clock | con1, LF-FEM slot 3, DO7 | 6738 `/PXI1Slot3/PFI0`, `ni_pxie_6738_1_clock` |
| NI digital sample clock | con1, LF-FEM slot 3, DO8 | 6535 `/PXI1Slot6/PFI4`, `ni_pxie_6535_clock` |
| OPX scope TTL | con1, LF-FEM slot 3, DO1 | Scope |
| OPX scope analog | con1, LF-FEM slot 3, AO3 | Scope, nominal +0.1 V pulses |
| NI scope analog | PXI1Slot3 AO30 | `c1_AO30`, between -0.2 and +0.2 V |
| NI scope digital | PXI1Slot6 DO01 / DIO1 | `do1`, `port0/line1` (bit 1) |

`flag 0` and `flag 1` in the existing table are logical clock-line labels. They
do not select physical OPX outputs. `opx_configuration.py` routes those lines to
DO7 and DO8 per shot. The internal `opx_main_clock_line` is unused.

The integration uses a QUA element named `clock` for section duration waits. It
references AO1 with zero offset and never plays an analog pulse on it. The NI
clock elements and DO1 scope element are digital-only; AO3 has its own element.

## Run in this order

All times below are nominal Labscript times. Lessons 1-8 use a one-second
timeline; lessons 9-10 intentionally change the physical playback duration.
Each shot also has a 1 ms completion guard and a final 1 us clock pulse.

| File | What to learn / expected scope signal |
| --- | --- |
| `01_opx_digital_pulse.py` | OPX DO1 high from 125 to 135 ms. NI AO30 stays at 0 V and DO01 stays low. |
| `02_opx_analog_pulse_train.py` | A QUA `for_` loop produces five +0.1 V, 100 us pulses on OPX AO3, starting at 125 ms with 10 ms spacing. |
| `03_ni_single_voltage.py` | NI AO30 is +0.1 V from 250 to 750 ms. OPX DO7 supplies the sparse sample-clock edges. |
| `04_ni_voltage_staircase.py` | NI AO30 changes every 125 ms through +0.1, +0.2, -0.1, -0.2, +0.1 and 0 V. A Python loop builds the NI buffer during compilation. |
| `05_ni_digital_pattern.py` | NI DO01 pulses start at 125, 250 and 500 ms; widths are 31.25, 62.5 and 125 ms. OPX DO8 clocks these changes. |
| `06_ni_analog_ramp.py` | NI AO30 ramps 0 to +0.2 V from 125 to 625 ms, sampled at 1 kHz. It holds +0.2 V until 750 ms, then returns to zero. |
| `07_independent_ni_clocks.py` | The same ramp plus NI DO01 high during 250-375 and 500-625 ms. Compare dense clock edges on DO7 with sparse edges on DO8. |
| `08_qua_and_ni_together.py` | The NI ramp runs while OPX AO3 and DO1 emit ten simultaneous 100 us pulses at 10 ms spacing, beginning at 125 ms. NI DO01 gates 125-625 ms. |
| `09_fixed_time_dilation.py` | Two nominal 0.5 s sections: the first takes 0.5 s, the second 1 s. Each ramps AO30 to +0.2 V then resets to zero. DO01 gate widths are 0.25 s then 0.5 s. |
| `10_qua_runtime_clock_speed.py` | A QUA `if_`/`else_` chooses a 2x or 0.5x time multiplier for both NI clocks. `SLOW_BRANCH = 1` gives a 1 s ramp and a roughly 2 s shot. Set it to 0 and recompile for a 0.25 s ramp and roughly 0.5 s shot. |

DO1 on the OPX and DO01 on the NI card are different signals. The first two
lessons still include the full apparatus from your table, so BLACS still arms
the NI devices. Their clocks carry repeated holds and the completion edge.

Both NI clocks also emit identical-value holds at 7.8125, 15.625, and 23.4375 ms.
Together with t=0, these give the early lessons four uploaded samples after
the NI worker removes the final duplicate row. AO30 stays at zero and DO01
stays low at these edges. The table's nonzero AO/shutter defaults keep these
tasks in buffered mode. The first hardware run exposed the generic two-sample
finite-timing minimum (-200077); the next exposed this PXIe-6535 configuration's
four-sample initial-transfer minimum at StartTask (-200294). Both requirements
must be met before OPX can start the shot.

## Compile and queue in BLACS

1. Keep the existing apparatus connection table configured in runmanager and
   BLACS. It must be the OPX version with `opx_main`, `c1_AO30`, and `do1`,
   matching the supplied `D:/connection_table.py`. If BLACS still has an older
   PulseBlaster table loaded, compile the existing OPX table and load that
   compiled table in BLACS first. These lessons do not edit the table.
2. Use runmanager and BLACS from `C:/Users/imaq/labscript-suite/.venv`. That
   environment already imports the installed `user_devices.opx` driver and the
   full apparatus table.
3. In runmanager, select `01_opx_digital_pulse.py` from this folder as the
   experiment script. Use the normal shot output directory. No new globals
   are required. Enable submission to the running BLACS instance and compile.
4. Run the queued shot in BLACS and use the scope's single-acquisition trigger
   for these short, finite shots. Work through the numbered files in order.
5. Restart runmanager after editing the shared configuration/support modules so
   its compiler reloads those imports, then compile a fresh shot. Changes to
   a script's constants also require a fresh compilation.

The programs use `execute` mode; there is no simulation flag to switch off.
BLACS arms the NI buffers before starting OPX as master. Running these files
with plain `python` is not a substitute for compilation and BLACS execution.
There is no call to `open_qm`, `execute`, or NI task creation in the lessons.

The full connection table owns additional AO/DO channels. These lessons issue
instructions only to AO30 and DO01; all other declared channels take the
defaults already specified by that table, including AO16 = 0.7 V, AO20 = 2.15 V,
and the two shutter outputs high. Every lesson returns AO30 to zero and DO01 low.

## How Labscript and QUA fit together

Each numbered file visibly defines its QUA program. `setup()` constructs your
existing table and attaches the per-shot OPX config and two clock playbacks.
Inside `qua.program()`, `begin()` initializes the test outputs and
`section()` joins the element timelines at the section boundaries.
Labscript `constant`, `ramp`, and `go_high`/`go_low` calls produce NI sample
arrays. The OPX driver derives the needed sample-clock schedule, then rebuilds
the QUA program with those clock ticks. This is why the builder runs twice;
keep device construction, file I/O, and other side effects outside it.

`finish()` joins all timelines and emits the extra completion edge on both NI
clocks. The installed inline segment compiler excludes the terminal stop tick,
while the NI worker omits its last duplicate sample. Some NI devices need that
extra edge to report a finite task complete. A shot can otherwise show the
right waveform but leave BLACS waiting. Tick timestamps and completion
timestamps are saved separately by the OPX worker.

Labscript times are seconds and NI analog values are volts. QM configuration
pulse lengths are nanoseconds. QUA `wait` and `play(duration=...)` durations
are 4 ns clock cycles. `wait_seconds()` makes that conversion explicit.

A time multiplier of 2 means twice as long / half the sample-clock speed.
The NI voltages and bit patterns were already buffered and do not change.
In lesson 10 the branch executes in QUA but is seeded by a constant; it is a
branching lesson without measurement feedback. The runtime section includes
an explicit scaled wait on the timing element to preserve its final hold.

The NI Runviewer preview uses nominal Labscript time. It does not show the
runtime dilation or reconstruct OPX AO3's QUA pulse train. Check those on the
scope. Software synchronization specifies the intended element timelines;
measure physical edge alignment and delays on the apparatus.

## Relationship to the original Examples folder

These lessons retain the original progression through OPX ticks, NI steps and
ramps, digital patterns, separate clocks, concurrent QUA/NI output, and fixed
and runtime clock dilation. The original two-6738 shared-clock exercise becomes
a staircase on AO30. The analog-input exercise is omitted because this table
has no active AI device. No second analog card, shared-clock fanout, or input
loopback is needed for this sequence set.

The three shared files are `opx_configuration.py`, `sequence_support.py`, and
`__init__.py`. Keep them beside the ten lessons. `validate_sequences.py` is an
offline checker; select only the numbered lessons as experiments.

## Repeat offline validation

From PowerShell, with this folder installed at the requested location:

```powershell
& 'C:/Users/imaq/labscript-suite/.venv/Scripts/python.exe' `
  'C:/Users/imaq/labscript-suite/userlib/labscriptlib/imaq_lab/qua_testing_sequences/validate_sequences.py'
```

The checker compiles the unchanged apparatus table and all ten lessons in
separate processes. It confirms connection-table equality, physical OPX routes,
clock counts versus NI buffer lengths, output limits and endpoints, other
channels' defaults, saved completion streams, and the lesson-specific behavior.
It decodes the serialized QUA into readable `.qua.py` files. Inspection shots
and a `validation.json` report go into `_compiled`; use normal runmanager
compilation for shots you submit to BLACS.

Validation uses the real local compiler and installed driver. It does not
connect to the QOP server, perform server-side compilation, or execute hardware.
The first queued shot in BLACS is the hardware check.

Validated on October 21, 2026: all ten lessons passed, and the optional fast
branch of lesson 10 also passed. Environment: Python 3.13.13, Labscript 3.4.2,
labscript-devices 3.3.0, and qm-qua 1.4.1. `VALIDATION.json` records the checks
and file hashes. The supplied and installed connection-table files matched;
their contents were not changed.

The shared initializer includes the identical-value holds above. Validation
calls the installed NI worker's AO/DO programming methods with a fake task
that checks both finite timing and the observed digital initial-transfer
minimum at StartTask. The old one- and two-sample shots fail these checks;
the corrected first lesson uploads four samples to each card. These checks
model the reported requirements and create no real NI task. They do not
establish hardware execution success.

References: [QM configuration and LF-FEM port addressing](https://docs.quantum-machines.co/1.2.4/docs/Introduction/config/),
[Labscript NI devices](https://labscriptsuite.org/projects/labscript-devices/en/stable/devices/ni_daqs/),
and the [NI worker completion-edge implementation](https://github.com/labscript-suite/labscript-devices/blob/master/labscript_devices/NI_DAQmx/blacs_workers.py).
