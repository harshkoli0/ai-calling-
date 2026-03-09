import time
import config

BLUETOOTH_BUFFER_SIZE = 4096


class BluetoothBridge:
    """Manages the Bluetooth connection between Phone A and Phone B."""

    def __init__(self):
        self.connected: bool = False
        self.socket = None

    def connect(self) -> bool:
        """Connect to Phone B via Bluetooth RFCOMM (or simulate in demo mode)."""
        if config.DEMO_MODE:
            print("[BT DEMO] Simulating Bluetooth connection to Phone B.")
            self.connected = True
            return True

        try:
            import bluetooth  # pybluez

            self.socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            self.socket.connect((config.PHONE_B_BLUETOOTH_MAC, config.BLUETOOTH_PORT))
            self.connected = True
            print(f"[BT] Connected to {config.PHONE_B_BLUETOOTH_MAC}")
            return True
        except Exception as e:
            print(f"[BT] Connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Close the Bluetooth socket."""
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                print(f"[BT] Error closing socket: {e}")
            finally:
                self.socket = None
        self.connected = False
        print("[BT] Disconnected.")

    def send_audio(self, audio_bytes: bytes):
        """Send audio bytes to Phone B over Bluetooth."""
        if config.DEMO_MODE:
            print(f"[BT DEMO] Sending {len(audio_bytes)} bytes of audio.")
            return

        if not self.connected or self.socket is None:
            print("[BT] Cannot send audio — not connected.")
            return

        try:
            self.socket.send(audio_bytes)
        except Exception as e:
            print(f"[BT] Failed to send audio: {e}")

    def receive_audio(self) -> bytes:
        """Receive audio bytes from Phone B over Bluetooth."""
        if config.DEMO_MODE:
            time.sleep(2)
            return b"DEMO_AUDIO"

        if not self.connected or self.socket is None:
            print("[BT] Cannot receive audio — not connected.")
            return b""

        try:
            data = self.socket.recv(BLUETOOTH_BUFFER_SIZE)
            return data
        except Exception as e:
            print(f"[BT] Failed to receive audio: {e}")
            return b""
