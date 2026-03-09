import config


class ADBBridge:
    """Manages the ADB connection to Phone A over USB."""

    def __init__(self):
        self.connected: bool = False
        self.device = None

    def connect(self) -> bool:
        """Connect to Phone A via ADB (or simulate in demo mode)."""
        if config.DEMO_MODE:
            print("[ADB DEMO] Simulating ADB connection to Phone A.")
            self.connected = True
            return True

        try:
            import adbutils

            adb = adbutils.AdbClient(host="127.0.0.1", port=5037)
            devices = adb.device_list()

            if not devices:
                print("[ADB] No devices found.")
                self.connected = False
                return False

            if config.ADB_DEVICE_SERIAL:
                for dev in devices:
                    if dev.serial == config.ADB_DEVICE_SERIAL:
                        self.device = dev
                        break
                if self.device is None:
                    print(f"[ADB] Device {config.ADB_DEVICE_SERIAL} not found.")
                    self.connected = False
                    return False
            else:
                self.device = devices[0]

            self.connected = True
            print(f"[ADB] Connected to device: {self.device.serial}")
            return True
        except Exception as e:
            print(f"[ADB] Connection failed: {e}")
            self.connected = False
            return False

    def get_device_info(self) -> str:
        """Return a human-readable description of the connected device."""
        if config.DEMO_MODE:
            return "Demo Phone A (USB)"

        if self.device:
            return self.device.serial

        return "Not connected"
