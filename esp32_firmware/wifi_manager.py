# DHARAA Wi-Fi Connection Manager for MicroPython
import time
import config

try:
    import network
    MICROPYTHON = True
except ImportError:
    MICROPYTHON = False

class WiFiManager:
    def __init__(self, ssid=config.WIFI_SSID, password=config.WIFI_PASS):
        self.ssid = ssid
        self.password = password
        self.wlan = None
        if MICROPYTHON:
            self.wlan = network.WLAN(network.STA_IF)
            self.wlan.active(True)

    def connect(self, timeout_seconds=15):
        if not MICROPYTHON or self.wlan is None:
            print("[WiFi Mock] Connected to Wi-Fi.")
            return True

        if self.wlan.isconnected():
            return True

        print(f"[WiFi] Connecting to SSID '{self.ssid}'...")
        self.wlan.connect(self.ssid, self.password)

        start_time = time.time()
        while not self.wlan.isconnected():
            if time.time() - start_time > timeout_seconds:
                print("[WiFi] Connection timeout. Retrying in background.")
                return False
            time.sleep(0.5)

        ip_info = self.wlan.ifconfig()
        print(f"[WiFi] Connected successfully! IP Address: {ip_info[0]}")
        return True

    def is_connected(self):
        if not MICROPYTHON or self.wlan is None:
            return True
        return self.wlan.isconnected()

    def ensure_connected(self):
        if not self.is_connected():
            return self.connect(timeout_seconds=8)
        return True
