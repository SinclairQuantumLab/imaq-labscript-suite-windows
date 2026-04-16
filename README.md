# Quick Labscript installation in Windows with `uv`

1. Make sure to back up and remove `%USERPROFILE%\labscript-suite\` folder, if exists, from the previous installation.

2. Install [`uv`](https://docs.astral.sh/uv/) following [this link](https://docs.astral.sh/uv/getting-started/installation/) and close the `powershell` for the installation.

3. Open `powershell` and `git clone` this repo in `C:\`. `C:\Labscript-windows\` folder will be downloaded.

   ```powershell
   > cd C:\
   > git clone https://github.com/SinclairQuantumLab/Labscript-windows.git
    ```

5. Go to the repo folder and run `uv sync`:

    ```powershell
    > cd C:\Labscript-windows
    > uv sync
    ```
    
    This will install `labscript-suite` and required packages.

6. Run the below to create Labscript profile:

    ```powershell
    > uv run labscript-profile-create # [OPTIONS]
    ```

    See [this page](https://labscriptsuite.org/en/latest/installation/regular-pypi/) to find details on the `[OPTIONS]`.

7. Run the below to create the shortcuts in Desktop:

    ```powershell
    > uv run desktop-app install blacs lyse runmanager runviewer
    ```

That's it!
