"""
DHARAA Hardware Node Simulator (Virtual ESP32)
Simulates sensor physics, Wi-Fi telemetry transmission, command polling,
pump actuation, and local safety rules for end-to-end testing without physical hardware.
"""
import time
import random
import requests

BACKEND_URL = "http://127.0.0.1:5000"
DEVICE_ID = 1

# Simulation State
moisture = 38.5         # Initial soil moisture (%)
temperature = 28.2      # Celsius
humidity = 64.0         # %
rain = 0                # 0 = dry, 1 = raining
flow_pulses = 0         # Accumulator
pump_state = 0          # 0 = OFF, 1 = ON
pump_start_time = None
emergency_stop = False
mode = "AUTO"

print("=" * 60)
print("     DHARAA VIRTUAL ESP32 SIMULATOR STARTING      ")
print("  Simulating Capacitive Sensor, DHT22, Flow & Relay")
print(f"  Target Backend: {BACKEND_URL}")
print("=" * 60)

tick = 0
while True:
    try:
        tick += 1
        now = time.time()

        # 1. Physical Simulation Engine
        if pump_state == 1:
            # When pump is ON, moisture increases, flow pulses generate
            moisture = min(100.0, moisture + random.uniform(1.2, 2.5))
            flow_pulses += int(random.uniform(40, 75))  # Water flowing
            # Check local max runtime safety watchdog (simulating 60s for demo)
            if pump_start_time and (now - pump_start_time) > 120:
                print("[SAFETY WATCHDOG] Local max runtime reached. Turning pump OFF.")
                pump_state = 0
                pump_start_time = None
        else:
            # When pump is OFF, moisture slowly evaporates/percolates
            moisture = max(10.0, moisture - random.uniform(0.1, 0.3))

        temperature = round(28.0 + random.uniform(-1.0, 1.5), 1)
        humidity = round(65.0 + random.uniform(-3.0, 3.0), 1)

        # 2. Check and Poll Backend for Commands
        try:
            cmd_res = requests.get(f"{BACKEND_URL}/api/commands/poll?device_id={DEVICE_ID}", timeout=3)
            if cmd_res.status_code == 200:
                data = cmd_res.json()
                if data.get("has_command"):
                    cmd = data.get("command")
                    cmd_id = cmd["id"]
                    cmd_type = cmd["type"]
                    print(f"\n[HARDWARE EVENT] Command Received: #{cmd_id} -> {cmd_type}")

                    if cmd_type == "EMERGENCY_STOP":
                        emergency_stop = True
                        pump_state = 0
                        pump_start_time = None
                        print(">> EMERGENCY STOP ACTIVATED ON HARDWARE NODE! <<")
                    elif cmd_type == "ON":
                        if not emergency_stop:
                            pump_state = 1
                            pump_start_time = now
                            print(">> Relay Click: 5V Pump Switched ON <<")
                        else:
                            print(">> Command Rejected: Emergency stop active <<")
                    elif cmd_type == "OFF":
                        pump_state = 0
                        pump_start_time = None
                        print(">> Relay Click: 5V Pump Switched OFF <<")
                    elif cmd_type == "SET_MODE_AUTO":
                        mode = "AUTO"
                        print(">> Mode set to AUTO <<")
                    elif cmd_type == "SET_MODE_MANUAL":
                        mode = "MANUAL"
                        print(">> Mode set to MANUAL <<")

                    # Acknowledge execution
                    ack_res = requests.post(f"{BACKEND_URL}/api/commands/ack", json={
                        "command_id": cmd_id,
                        "status": "completed",
                        "reported_pump_state": pump_state
                    }, timeout=3)
        except Exception as e:
            # Backend might not be running yet
            pass

        # 3. Transmit Telemetry every 3 seconds (accelerated for interactive demo)
        if tick % 3 == 0:
            payload = {
                "device_id": DEVICE_ID,
                "moisture": round(moisture, 1),
                "temperature": temperature,
                "humidity": humidity,
                "rain": rain,
                "flow_pulses": flow_pulses,
                "pump_state": pump_state,
                "sensor_status": "OK"
            }
            try:
                res = requests.post(f"{BACKEND_URL}/api/telemetry", json=payload, timeout=3)
                if res.status_code in [200, 201]:
                    flow_pulses = 0  # Reset pulse delta
                    resp_json = res.json()
                    action = resp_json.get("policy_evaluation", {}).get("action")
                    reason = resp_json.get("policy_evaluation", {}).get("reason")
                    print(f"[TELEMETRY POST] Moisture: {moisture:.1f}% | Temp: {temperature}°C | Rain: {rain} | Pump: {'ON' if pump_state == 1 else 'OFF'} | Rule Action: {action} ({reason})")
            except Exception as e:
                print(f"[TELEMETRY POST] Waiting for backend at {BACKEND_URL}...")

        time.sleep(1)

    except KeyboardInterrupt:
        print("\nSimulator stopped by user.")
        break
    except Exception as e:
        print("Simulator error:", e)
        time.sleep(2)
