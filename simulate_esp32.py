"""
DHARAA Hardware Node Simulator (Virtual ESP32) — v1.1
Simulates sensor physics, Wi-Fi telemetry transmission, command polling,
pump actuation, and local safety rules for end-to-end testing without physical hardware.

ENHANCED: Supports AI-guided quantity-based pump stopping.
  - Parses target_pulses from ON command payload (JSON or plain string)
  - Tracks session-cumulative flow pulses
  - Stops pump when target is reached (or max runtime exceeded)
"""
import time
import random
import json
import requests

BACKEND_URL = "http://127.0.0.1:5000"
DEVICE_ID   = 1

# Simulation State
moisture        = 38.5     # Initial soil moisture (%)
temperature     = 28.2     # Celsius
humidity        = 64.0     # %
rain            = 0        # 0 = dry, 1 = raining
flow_pulses     = 0        # Per-interval accumulator (reset every telemetry send)
pump_state      = 0        # 0 = OFF, 1 = ON
pump_start_time = None
emergency_stop  = False
mode            = "AUTO"

# AI Quantity Tracking (session-level, not reset every interval)
session_target_pulses = 0   # 0 = no target (time-based mode)
session_total_pulses  = 0   # Cumulative pulses this pump session

print("=" * 60)
print("     DHARAA VIRTUAL ESP32 SIMULATOR v1.1 STARTING      ")
print("  Simulating Capacitive Sensor, DHT22, Flow & Relay")
print("  + AI Quantity-Based Pump Stopping (target_pulses)")
print(f"  Target Backend: {BACKEND_URL}")
print("=" * 60)

tick = 0
while True:
    try:
        tick += 1
        now = time.time()

        # 1. Physical Simulation Engine
        if pump_state == 1:
            moisture    = min(100.0, moisture + random.uniform(1.2, 2.5))
            interval_fp = int(random.uniform(40, 75))   # Flow pulses this tick
            flow_pulses += interval_fp
            session_total_pulses += interval_fp

            # Local max runtime safety watchdog (120s for fast demo; real is 300s)
            if pump_start_time and (now - pump_start_time) > 120:
                print("[SAFETY WATCHDOG] Local max runtime reached. Turning pump OFF.")
                pump_state            = 0
                pump_start_time       = None
                session_target_pulses = 0
                session_total_pulses  = 0

            # AI Quantity Target Check
            elif session_target_pulses > 0 and session_total_pulses >= session_target_pulses:
                ml_delivered = round(session_total_pulses / 450.0 * 1000.0, 1)
                print(f"[AI TARGET REACHED] {session_total_pulses} pulses / "
                      f"{session_target_pulses} target → {ml_delivered} ml delivered. Pump OFF.")
                pump_state            = 0
                pump_start_time       = None
                session_total_pulses  = 0
                session_target_pulses = 0

        else:
            moisture = max(10.0, moisture - random.uniform(0.1, 0.3))

        temperature = round(28.0 + random.uniform(-1.0, 1.5), 1)
        humidity    = round(65.0 + random.uniform(-3.0, 3.0),  1)

        # 2. Poll Backend for Commands
        try:
            cmd_res = requests.get(
                f"{BACKEND_URL}/api/commands/poll?device_id={DEVICE_ID}", timeout=3
            )
            if cmd_res.status_code == 200:
                data = cmd_res.json()
                if data.get("has_command"):
                    cmd      = data.get("command")
                    cmd_id   = cmd["id"]
                    cmd_type = cmd["type"]
                    payload  = cmd.get("payload", "")
                    print(f"\n[HARDWARE EVENT] Command #{cmd_id} → {cmd_type}")

                    if cmd_type == "EMERGENCY_STOP":
                        emergency_stop        = True
                        pump_state            = 0
                        pump_start_time       = None
                        session_target_pulses = 0
                        session_total_pulses  = 0
                        print(">> EMERGENCY STOP ACTIVATED ON HARDWARE NODE! <<")

                    elif cmd_type == "ON":
                        if not emergency_stop:
                            pump_state      = 1
                            pump_start_time = now
                            session_total_pulses = 0

                            # Parse AI target from payload
                            session_target_pulses = 0
                            if payload:
                                try:
                                    pdata = json.loads(payload)
                                    tp    = int(pdata.get("target_pulses", 0) or 0)
                                    session_target_pulses = tp
                                    if tp > 0:
                                        print(f">> AI Mode: target {tp} pulses "
                                              f"(~{tp / 450.0:.2f} L) <<")
                                    else:
                                        print(">> Time-based mode (no pulse target) <<")
                                except (ValueError, TypeError, KeyError):
                                    pass  # Plain string payload — time-based

                            print(">> Relay Click: 5V Pump Switched ON <<")
                        else:
                            print(">> Command Rejected: Emergency stop active <<")

                    elif cmd_type == "OFF":
                        pump_state            = 0
                        pump_start_time       = None
                        session_target_pulses = 0
                        session_total_pulses  = 0
                        print(">> Relay Click: 5V Pump Switched OFF <<")

                    elif cmd_type == "SET_MODE_AUTO":
                        mode = "AUTO"
                        print(">> Mode set to AUTO <<")

                    elif cmd_type == "SET_MODE_MANUAL":
                        mode = "MANUAL"
                        print(">> Mode set to MANUAL <<")

                    # Acknowledge execution
                    requests.post(
                        f"{BACKEND_URL}/api/commands/ack",
                        json={"command_id": cmd_id,
                              "status": "completed",
                              "reported_pump_state": pump_state},
                        timeout=3
                    )
        except Exception:
            pass

        # 3. Transmit Telemetry every tick (1s) for near-real-time frontend updates
        if tick % 1 == 0:
            payload_data = {
                "device_id":    DEVICE_ID,
                "moisture":     round(moisture, 1),
                "temperature":  temperature,
                "humidity":     humidity,
                "rain":         rain,
                "flow_pulses":  flow_pulses,
                "pump_state":   pump_state,
                "sensor_status": "OK"
            }
            try:
                res = requests.post(
                    f"{BACKEND_URL}/api/telemetry", json=payload_data, timeout=3
                )
                if res.status_code in [200, 201]:
                    flow_pulses = 0   # Reset per-interval pulse counter
                    resp_json   = res.json()
                    action  = resp_json.get("policy_evaluation", {}).get("action")
                    reason  = resp_json.get("policy_evaluation", {}).get("reason")
                    ai_act  = resp_json.get("ai_flow_action")

                    # Backend confirmed AI target reached via server-side check
                    if ai_act and ai_act.get("action") == "STOP" and pump_state == 1:
                        ml = ai_act.get("actual_water_ml", 0)
                        print(f"[BACKEND AI CONFIRM] Pump OFF: {ml} ml delivered.")
                        pump_state            = 0
                        pump_start_time       = None
                        session_target_pulses = 0
                        session_total_pulses  = 0

                    target_info = ""
                    if session_target_pulses > 0:
                        target_info = (f" | AI: {session_total_pulses}/"
                                       f"{session_target_pulses} pulses")
                    print(f"[TELEMETRY] Moisture: {moisture:.1f}% | "
                          f"Temp: {temperature}°C | Rain: {rain} | "
                          f"Pump: {'ON' if pump_state == 1 else 'OFF'} | "
                          f"Rule: {action} ({reason}){target_info}")
            except Exception as e:
                print(f"[TELEMETRY] Waiting for backend at {BACKEND_URL}... ({e})")

        time.sleep(1)

    except KeyboardInterrupt:
        print("\nSimulator stopped by user.")
        break
    except Exception as e:
        print("Simulator error:", e)
        time.sleep(2)
