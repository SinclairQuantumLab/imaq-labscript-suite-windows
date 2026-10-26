from datetime import datetime
from pathlib import Path

from PIL import Image

from labscript_devices.SpinnakerCamera.blacs_workers import SpinnakerCameraWorker


class CustomSpinnakerCameraWorker(SpinnakerCameraWorker):

    def snap_and_save(self, directory):
        # Acquire a single image using the standard Spinnaker camera interface:
        image = self.camera.snap()

        # Send it to BLACS for display:
        self._send_image_to_parent(image)

        # Ensure the destination directory exists:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        # Timestamp including milliseconds:
        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S_%f"
        )[:-3]

        filepath = (
            directory
            / f"{self.device_name}_{timestamp}.tiff"
        )

        # Save the raw image data:
        Image.fromarray(image).save(filepath)

        print(f"Saved manual snap to: {filepath}")