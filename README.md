# IMAQ `labscript-suit` for Windows

This repo contains `uv` project to seamlessly install `labscript-suite` and customization and for the use in IMAQ Lab, Josiah Sinclair Group.

## ControlPC snapshot with QUA integration

The `controlpc-withqua` branch captures the ControlPC environment and experiment
source on October 26, 2026. It starts from the `controlpc-beforequa` backup.

- `pyproject.toml` and `uv.lock` include the `opx` dependency group. Install that
  group with `uv sync --locked --group opx` after providing the local Spinnaker
  wheel referenced in `pyproject.toml`.
- `environment-snapshots/controlpc-withqua-freeze.txt` records the installed
  packages, including `qm-qua==1.4.1` and `pydantic==2.14.1`.
- `imaq-library/qua-integration/` contains a source snapshot of
  `user_devices/` and `labscriptlib/imaq_lab/`, including the OPX driver,
  connection tables, QUA lessons, MOT shots, supporting device drivers, and
  offline regression tests. `MANIFEST.json` records source repository commits,
  local changes, and SHA-256 hashes of the archived files.

The live `userlib/` repositories remain separate and ignored by this repository.
To restore the archived code into a Labscript profile, copy the two source trees
from `imaq-library/qua-integration/` into the corresponding directories under that
profile's `userlib/`, after backing up its existing files. Machine configuration,
Runmanager globals, shot data, vendor drivers, and the Spinnaker wheel are supplied
separately. Restart the applications and recompile the connection table and shots
after installing the code.

The OPX driver snapshot includes the fix that keeps scaled variable waits below
the observed 24-bit boundary on QOP 3.8.1. The reproduction and recorded results
are under `user_devices/opx/diagnostics/` in the archive. The separate automatic
section-padding issue for `qua_logic` remains unresolved in this snapshot;
`mot_loading_measurement_qua.py` uses fixed timing for the original MOT loading
protocol. Archived test sequences and legacy shots retain their current behavior.
`VALIDATION.json` records the checks and an existing syntax error in the unused
`NIRFCombiner/blacs_workers.py` stub, which is preserved as part of the backup.

Run the archived OPX regression tests without executing a hardware sequence:

```powershell
$env:PYTHONPATH = (Resolve-Path .\imaq-library\qua-integration).Path
& .\.venv\Scripts\python.exe -m unittest discover -s .\imaq-library\qua-integration\user_devices\opx\tests -v
```

## Quick Labscript installation in Windows with `uv`

1. Make sure to back up and remove all the files bekow from the previous installation:
   - Labscript suite & profile folder: `%USERPROFILE%\Labscript-suite`
   - `Experiments` folder
   - Shortcut files in `%USERPROFILE%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs`:
      - `BLACS - the labscript suite.lnk`
      - `lyse - the labscript suite.lnk`
      - `runmanager - the labscript suite.lnk`
      - `runviewer - the labscript suite.lnk`

2. Install [`uv`](https://docs.astral.sh/uv/) following [this link](https://docs.astral.sh/uv/getting-started/installation/) and close the `powershell` for the installation.

3. Open Powershell terminal and go to `$HOME` (the Powershell version of `%USERPROFILE%`). Then, `git clone` this repo **with the folder name `labscript-suite` (important)**:

    ```powershell
    cd $HOME
    git clone https://github.com/SinclairQuantumLab/imaq-labscript-suite-windows.git labscript-suite
    ```

    `labscript-suite` folder should have been created through the command line above.


4.  Go to the created folder and run `uv sync`:

    ```powershell
    cd labscript-suite
    uv sync
    ```
    This will install `labscript-suite` and required packages.


6. Run the below to create Labscript profile names as `imaq_lab`:

    ```powershell
    uv run labscript-profile-create -n imaq_lab -c
    ```

    See [this page](https://labscriptsuite.org/en/latest/installation/regular-pypi/) for the available options for the `labscript-profile-create` command.

7. Run the below to create the shortcuts in Desktop:

    ```powershell
    uv run desktop-app install blacs lyse runmanager runviewer
    ```

That's it! Try opneing `BLACS` app and it should give no error.

## Customizing for IMAQ Lab

### Creating PrawnBlaster & PrawnDO demo

Rename the existing demo `connection_table.py` to `connection_table_demo.py` and copy the `connection_table.py` for the Prawn demo pi picos' and demo pulse sequence:
 ```powershell
 mv .\userlib\labscriptlib\imaq_lab\connection_table.py .\userlib\labscriptlib\imaq_lab\connection_table_dummy.py
 cp -r .\imaq-library\labscriptlib_prawn-demo\* userlib\labscriptlib\imaq_lab\
 ```

The connection_table.py should be recompiled in `BLACS` ignore error when `BLACS` restarts and just open it again.

## One-shot setup script
Copy & paste the below script to a Powershell terminal (innitial location doesn't matter) and all the steps above will be done.

```powershell
$APPARATUS_NAME = "imaq_lab"

cd $HOME
### 1. Install `labscript-suite` and create profile and Desktop shortcuts
git clone https://github.com/SinclairQuantumLab/imaq-labscript-suite-windows.git labscript-suite
cd labscript-suite
uv sync
uv run labscript-profile-create -n $APPARATUS_NAME -c
uv run desktop-app install blacs lyse runmanager runviewer

### 2. Apply IMAQ customization
# PrawnBlaster & PrawnDO demo
mv ".\userlib\labscriptlib\$APPARATUS_NAME\connection_table.py" ".\userlib\labscriptlib\$APPARATUS_NAME\connection_table_dummy.py"
cp -r .\imaq-library\labscriptlib_prawn-demo\* "userlib\labscriptlib\$APPARATUS_NAME\"
 
```

Make sure to open `BLACS`, recompile and restart it, and open `BLACS` again after closing an error dialog that pops up.
