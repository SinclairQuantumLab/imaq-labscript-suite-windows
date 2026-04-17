# IMAQ `labscript-suit` for Windows

This repo contains `uv` project to seamlessly install `labscript-suite` and customization and for the use in IMAQ Lab, Josiah Sinclair Group.

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

3. Open Powershell terminal and go to `$HOME` (the Powershell version of `%USERPROFILE%`). Then, `git clone` this repo:

    ```powershell
    cd $HOME
    git clone https://github.com/SinclairQuantumLab/imaq-labscript-suite-windows.git labscript-suite
    ```

    `labscript-suite` folder should have been created.


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
cd $HOME
### 1. Install `labscript-suite` and create profile and Desktop shortcuts
git clone https://github.com/SinclairQuantumLab/imaq-labscript-suite-windows.git labscript-suite
cd labscript-suite
uv sync
uv run labscript-profile-create -n imaq_lab -c
uv run desktop-app install blacs lyse runmanager runviewer

### 2. Apply IMAQ customization
# PrawnBlaster & PrawnDO demo
mv .\userlib\labscriptlib\imaq_lab\connection_table.py .\userlib\labscriptlib\imaq_lab\connection_table_dummy.py
cp -r .\imaq-library\labscriptlib_prawn-demo\* userlib\labscriptlib\imaq_lab\
 
```
