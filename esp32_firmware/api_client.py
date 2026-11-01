# DHARAA REST API Client for MicroPython
import json
import config

try:
    import urequests as requests
except ImportError:
    import requests

class DHARAAApiClient:
    def __init__(self, base_url=config.BACKEND_URL, device_id=config.DEVICE_ID):
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.headers = {
            "Content-Type": "application/json",
            "X-Device-Key": config.DEVICE_KEY
        }

    def post_telemetry(self, moisture, temperature, humidity, rain, flow_pulses, pump_state, sensor_status="OK"):
        """
        POST sensor readings to Flask /api/telemetry.
        Returns response JSON or None if failed.
        """
        url = f"{self.base_url}/api/telemetry"
        payload = {
            "device_id": self.device_id,
            "moisture": moisture,
            "temperature": temperature,
            "humidity": humidity,
            "rain": rain,
            "flow_pulses": flow_pulses,
            "pump_state": pump_state,
            "sensor_status": sensor_status
        }
        try:
            res = requests.post(url, headers=self.headers, data=json.dumps(payload), timeout=8)
            data = res.json()
            res.close()
            return data
        except Exception as e:
            print("[API] Failed to send telemetry:", e)
            return None

    def poll_command(self):
        """
        GET /api/commands/poll?device_id=...
        """
        url = f"{self.base_url}/api/commands/poll?device_id={self.device_id}"
        try:
            res = requests.get(url, headers=self.headers, timeout=5)
            data = res.json()
            res.close()
            if data and data.get("has_command"):
                return data.get("command")
            return None
        except Exception as e:
            print("[API] Failed to poll command:", e)
            return None

    def acknowledge_command(self, command_id, status="completed", reported_pump_state=0):
        """
        POST /api/commands/ack
        """
        url = f"{self.base_url}/api/commands/ack"
        payload = {
            "command_id": command_id,
            "status": status,
            "reported_pump_state": reported_pump_state
        }
        try:
            res = requests.post(url, headers=self.headers, data=json.dumps(payload), timeout=5)
            res.close()
            return True
        except Exception as e:
            print("[API] Failed to acknowledge command:", e)
            return False
