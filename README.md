# Quick Labscript installation in Windows with `uv`

1. Make sure to back up and remove `%USERPROFILE%\labscript-suite\` folder, if exists, from the previous installation.

2. Install [`uv`](https://docs.astral.sh/uv/) following [this link](https://docs.astral.sh/uv/getting-started/installation/) and close the `powershell` for the installation.

3. `git clone` this repo in `C:\`. `C:\Labscript-windows\` folder will be downloaded.

4. Open `powershell` and go to the repo folder. Run the below in the terminal:

    ```powershell
    > uv sync
    ```
    
    The will install `labscript-suite` and required packages.

5. Run the below to create Labscript profile:

    ```powershell
    > uv run labscript-profile-create # [OPTIONS]
    ```

    See [this page](https://labscriptsuite.org/en/latest/installation/regular-pypi/) to find details on the `[OPTIONS]`.

6. Run the below to create the shortcuts in Desktop:

    ```powershell
    > uv run desktop-app install blacs lyse runmanager runviewer
    ```

That's it!