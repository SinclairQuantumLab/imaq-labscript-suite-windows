# Quick Labscript installation in Windows with `uv`

1. Make sure to back up and remove all the files bekow from the previous installation:
   - Labscript suite & profile folder: `%USERPROFILE%\Labscript-suite`
   - `Experiment` folder
   - Shortcut files in `%USERPROFILE%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs`:
      - `BLACS - the labscript suite.lnk`
      - `lyse - the labscript suite.lnk`
      - `runmanager - the labscript suite.lnk`
      - `runviewer - the labscript suite.lnk`

2. Install [`uv`](https://docs.astral.sh/uv/) following [this link](https://docs.astral.sh/uv/getting-started/installation/) and close the `powershell` for the installation.

3. Open Powershell terminal and go to `$HOME` (the Powershell version of `%USERPROFILE%`). Then, `git clone` this repo:

    ```powershell
    cd $HOME
    git clone https://github.com/SinclairQuantumLab/labscript-suite-windows.git
    ```

    `labscript-suite-windows` folder should have been created.


4.  Go to the created folder and run `uv sync`:

    ```powershell
    cd labscript-suite-windows
    uv sync
    ```
    This will install `labscript-suite` and required packages.

5. **(IMPORTANT) RENAME THE `labscript-suite-windows` FOLDER TO `labscript-suite`!!!**
    ```powershell
    cd ..\
    mv labscript-suite-windows labscript-suite
    cd labscript-suite
    ```
    > **NOTE**: We cannot take this step before running `uv sync` because of a limitation in `uv`: it cannot install the package that has the same name to the project folder. 

6. Run the below to create Labscript profile names as `imaq_lab`:

    ```powershell
    uv run labscript-profile-create -n imaq_lab -c
    ```

    See [this page](https://labscriptsuite.org/en/latest/installation/regular-pypi/) for the available options for the `labscript-profile-create` command.

7. Run the below to create the shortcuts in Desktop:

    ```powershell
    uv run desktop-app install blacs lyse runmanager runviewer
    ```

That's it!
