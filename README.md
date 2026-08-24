# IMAQ `labscript-suite` for Windows

This repository contains a `uv` project for seamlessly installing `labscript-suite` and the customizations used by the IMAQ Lab in the Josiah Sinclair Group on 64-bit Windows.

## Quick Labscript installation in Windows with `uv`

1. Make sure to back up and remove all the items below from the previous installation:
   - Labscript suite & profile folder: `$HOME\labscript-suite`
   - `C:\Experiments` folder
   - Shortcut files in `%USERPROFILE%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs`:
      - `BLACS - the labscript suite.lnk`
      - `lyse - the labscript suite.lnk`
      - `runmanager - the labscript suite.lnk`
      - `runviewer - the labscript suite.lnk`

2. Install [`uv`](https://docs.astral.sh/uv/) by following [these instructions](https://docs.astral.sh/uv/getting-started/installation/), and close PowerShell after the installation.

3. Open a PowerShell terminal and go to `$HOME` (the PowerShell equivalent of `%USERPROFILE%`). Then, clone this repository **with the folder name `labscript-suite` (important)**:

    ```powershell
    cd $HOME
    git clone https://github.com/SinclairQuantumLab/imaq-labscript-suite-windows.git labscript-suite
    ```

    The command above creates the `labscript-suite` folder.

4. Go to the created folder and run `uv sync`:

    ```powershell
    cd labscript-suite
    uv sync
    ```
    This installs `labscript-suite` and its required packages.

5. Set the `APPARATUS_NAME` of the `labscript-suite` profile to be built as below.

    ```powershell
    $APPARATUS_NAME = "<APPARATUS_NAME>"
    ```

    The following rules describe the required format for `APPARATUS_NAME`:

    - As a Sinclair Group convention, use the computer's hostname after modifying it according to the naming rules below (e.g., **`IMAQ-Analysis-Computer` to `IMAQ_Analysis_Computer`**), unless there is a good reason not to.
    - The name should have a [valid format for Python modules](https://docs.python.org/3/reference/lexical_analysis.html#names-identifiers-and-keywords), including:
        - uppercase and lowercase letters (`A-Z` and `a-z`)
        - the underscore (`_`)
        - digits (0 through 9), which cannot appear as the first character

    > **NOTE**: `APPARATUS_NAME` should be a valid Python identifier so that modules in `userlib\analysislib\<APPARATUS_NAME>\` and `userlib\labscriptlib\<APPARATUS_NAME>\` (such as `connection_table.py`) can be imported straightforwardly by experiment and analysis code. These directories are created when the labscript profile is built in the next step.

    The PowerShell variable `$APPARATUS_NAME` is used multiple times throughout the remainder of this document.

6. Run the command below to create a labscript profile with `<APPARATUS_NAME>`:

    ```powershell
    uv run labscript-profile-create -n $APPARATUS_NAME -c
    ```

    See [this page](https://labscriptsuite.org/en/latest/installation/regular-pypi/) for the available options for the `labscript-profile-create` command.

    > **NOTE**: the minimal cleanup required to rebuild the profile is to remove the following folders from `$HOME\labscript-suite\`: `.venv`, `app_saved_configs`, `labconfig`, and `userlib`.
    > If the following exception is raised, reboot the computer and try again:
    > - `zprocess.security.AuthenticationFailure: Failed to authenticate with server. Ensure both client and server have the same shared secret.`

7. Run the command below to create shortcuts in the Windows Start menu:

    ```powershell
    uv run desktop-app install blacs lyse runmanager runviewer
    ```

That's it! Try opening `BLACS`; it should launch like the screenshot below without errors.

![BLACS running successfully with the dummy connection table](<README_BLACS with dummy.png>)

## Customizing for IMAQ Lab

### Setting up PrawnBlaster & PrawnDO demo

1. The commands below rename the existing dummy `connection_table.py` in `userlib\labscriptlib\<APPARATUS_NAME>\` to `connection_table_dummy.py` and copy the contents of `sinclairlab-library\labscriptlib_prawn-demo\` for the Prawn demo:

    ```powershell
    cd $HOME\labscript-suite\
    mv .\userlib\labscriptlib\$APPARATUS_NAME\connection_table.py .\userlib\labscriptlib\$APPARATUS_NAME\connection_table_dummy.py
    cp -r .\sinclairlab-library\labscriptlib_prawn-demo\* userlib\labscriptlib\$APPARATUS_NAME\
    ```

    > **NOTE**: `$APPARATUS_NAME` is the PowerShell variable set during the installation above.

2. Open the `userlib\labscriptlib\$APPARATUS_NAME\connection_table.py.template` file and replace placeholders such as `<COM PORT>` and `<PICO BOARD NAME>`.

    > To specify '<COM PORT>', open your Device Manager and look under Ports (COM & LPT) for a USB Serial Device. Plug in the PrawnBlaster and PrawnDO one at a time to determine which COM corresponds to each board. For example, if plugging in your PrawnBlaster causes a new USB Serial Device (COM9) to appear in Device Manager, replace '<COM PORT>' with 'COM9' in the PrawnBlaster connection table entry (notice <> are also removed). To specify '<PICO BOARD NAME>', look at the name printed on each Raspberry Pi Pico. If your PrawnBlaster Pico is labeled 'Pico 2 W' or similar, replace '<PICO BOARD NAME>' with pico2. If your Pico is labeled 'Raspberry Pi Pico' or similar, '<PICO BOARD NAME>' with pico1. Don't forget to specify these lines again in the PrawnDO connection table entry. 

3. Remove the `.template` extension from `connection_table.py.template` manually or by running the command below:

    ```powershell
    cd $HOME\labscript-suite\userlib\labscriptlib\$APPARATUS_NAME\
    mv connection_table.py.template connection_table.py
    ```

4. Run the commands below (or manually edit and rename the file) to replace the `<APPARATUS_NAME>` placeholder in `userlib\labscriptlib\<APPARATUS_NAME>\test_sequences\pulse_test.py.template` and remove the `.template` extension from the file name.

    ```powershell
    cd $HOME\labscript-suite\userlib\labscriptlib\$APPARATUS_NAME\test_sequences\
    (Get-Content pulse_test.py.template -Raw).Replace('<APPARATUS_NAME>', $APPARATUS_NAME) |
    Set-Content pulse_test.py.template
    mv pulse_test.py.template pulse_test.py
    ```

5. Open `BLACS`, recompile `connection_table.py`, and restart `BLACS`. After closing the error dialog that appears, open `BLACS` again.

## One-shot setup script

Set the PowerShell variable for the apparatus name used by labscript. See the detailed naming rules in the [Quick Labscript installation in Windows with `uv`](#quick-labscript-installation-in-windows-with-uv) section above.

```powershell
$APPARATUS_NAME = "<APPARATUS_NAME>"
```

Then, copy and paste the script below into a PowerShell terminal (the initial location does not matter) to perform all the steps above.

```powershell
cd $HOME
### 1. Install `labscript-suite`, create a profile, and create Start menu shortcuts
git clone https://github.com/SinclairQuantumLab/imaq-labscript-suite-windows.git labscript-suite
cd labscript-suite
uv sync
uv run labscript-profile-create -n $APPARATUS_NAME -c
uv run desktop-app install blacs lyse runmanager runviewer

### 2. Apply IMAQ customization
# PrawnBlaster & PrawnDO demo
mv ".\userlib\labscriptlib\$APPARATUS_NAME\connection_table.py" ".\userlib\labscriptlib\$APPARATUS_NAME\connection_table_dummy.py"
cp -r .\sinclairlab-library\labscriptlib_prawn-demo\* "userlib\labscriptlib\$APPARATUS_NAME\"
cd .\userlib\labscriptlib\$APPARATUS_NAME\test_sequences\
(Get-Content pulse_test.py.template -Raw).Replace('<APPARATUS_NAME>', $APPARATUS_NAME) |
Set-Content pulse_test.py.template
mv pulse_test.py.template pulse_test.py
cd $HOME\labscript-suite

```

Steps that have to be performed manually:

1. Make sure to **configure `.\userlib\labscriptlib\$APPARATUS_NAME\connection_table.py.template` and remove the `.template` extension** from the file name.
2. Then, open `BLACS`, recompile the connection table, and restart `BLACS`. After closing the error dialog that appears, open `BLACS` again.

## Initial testing demo
There are two different ways to use labscript to operate devices: manual mode and buffered mode. Manual mode refers to user interaction with the BLACS GUI (graphical user interface) to send individual commands to a device. To test manual mode using your PrawnBlaster/PrawnDO:
1. Plug your BNC connector (wired to Digital Output 11 and Ground on PrawnD) into any oscilloscope or multimeter.
2. Open BLACS and toggle 'do11' on and off under the 'prawn_do' tab. 
3. As you toggle the 'do11' button, you should be able to observe a ~3.3V TTL signal go "high" and "low" on your oscilloscope or multimeter. If this works, you have successfully demonstrated use of manual mode!
To test buffered mode, we will use an another labscript program called runmanager, which complies experimental sequences called "shots". These "shot" files are then passed to BLACS, which calls the workers of every device used in that sequence. To run a sequence, do the following:
1. Plug your BNC connector (wired to Digital Output 11 and Ground on PrawnD) into an oscilloscope. You will be viewing a 30 ms sequence of 100 3.3V pulses (high for 100 us and low for 200 ms), so adjust scope settings for such a sequence to be visible. 
2. Open runmanager and BLACS. Both programs buts be open to run shots.
3. In runmanager, select pulse_test.py as your "labscript file". This file is located at labscript-suite/sinclairlab-library/labscriptlib_prawn-demo/test_sequences.
4. To run the shot, click "Engage" in top left corner.
5. If shot executes successfully, you should be able to view a series of square pulses that align with the pulse width and amplitude specified in your sequence.
6. Try to create a more interesting sequence building off the basic pulse test, such as varying pulse width or spacing! 


## Developer Notes

- <a name="DN20260729A"></a>(2026/07/29) The Sinclair Group's naming convention for `APPARATUS_NAME` could require lowercase letters to follow the [PEP 8 Style Guide on module names](https://peps.python.org/pep-0008/#package-and-module-names). We decided against this because keeping `APPARATUS_NAME` visually distinct from other modules seemed more desirable.

- <a name="DN20260729B"></a>(2026/07/29) When attempting to rebuild the labscript profile, `zprocess.security.AuthenticationFailure` can be raised because a `zlock` or `zlog` process is still running. As an alternative to rebooting the computer, find and stop these processes:

    ```powershell
    $servers = Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -match '(?:labscript_utils|zprocess)\.z(?:lock|log)'
    }
    $servers | Select-Object ProcessId, Name, CommandLine
    $servers | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
    }
    ```
