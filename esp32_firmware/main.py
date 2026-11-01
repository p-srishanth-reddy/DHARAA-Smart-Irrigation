# DHARAA Smart Irrigation System - MicroPython Firmware Entry Point
import time
import config
from sensors import SensorManager
from safety import SafetyManager
from wifi_manager import WiFiManager
from api_client import DHARAAApiClient
from irrigation import IrrigationController

def main():
    print("=" * 50)
    print("      DHARAA SMART IRRIGATION SYSTEM      ")
    print("           ESP32 MicroPython v1.0         ")
    print("=" * 50)

    # 1. Initialize Safety Subsystem (Guarantees Pump is OFF at startup)
    safety = SafetyManager()
    print("[INIT] Pump safety initialized. Pump is OFF.")

    # 2. Initialize Sensors & Irrigation Controller
    sensors = SensorManager()
    controller = IrrigationController(safety)
    api = DHARAAApiClient()

    # 3. Connect to Wi-Fi
    wifi = WiFiManager()
    wifi.connect()

    last_telemetry_time = 0

    print("[RUN] Entering main control and telemetry loop...")
    while True:
        try:
            now = time.time()

            # Local Runtime Safety Watchdog: Must execute every loop tick!
            safety.check_runtime_watchdog()

            # Ensure Wi-Fi link is alive
            wifi.ensure_connected()

            # 1. Poll for any pending commands from Backend / Dashboard
            cmd = api.poll_command()
            if cmd:
                cmd_id = cmd.get("id")
                success = controller.execute_command(cmd)
                api.acknowledge_command(
                    command_id=cmd_id,
                    status="completed" if success else "rejected",
                    reported_pump_state=safety.pump_state
                )

            # 2. Sample Sensors
            moisture, m_status = sensors.read_moisture()
            temp, hum, dht_status = sensors.read_dht22()
            rain = sensors.read_rain()
            flow_pulses = sensors.get_and_reset_flow_pulses()

            # Overall sensor status
            sensor_status = "OK"
            if m_status != "OK" or dht_status != "OK":
                sensor_status = f"{m_status}|{dht_status}"

            # 3. Local Auto Hysteresis & Rain Invalidation
            controller.check_automated_rules(moisture, (rain == 1), sensor_status)

            # 4. Transmit Telemetry at defined intervals
            if (now - last_telemetry_time) >= config.TELEMETRY_INTERVAL_SECONDS:
                resp = api.post_telemetry(
                    moisture=moisture,
                    temperature=temp,
                    humidity=hum,
                    rain=rain,
                    flow_pulses=flow_pulses,
                    pump_state=safety.pump_state,
                    sensor_status=sensor_status
                )
                if resp:
                    # If backend returned an immediate pending command in telemetry response
                    pending_cmd = resp.get("pending_command")
                    if pending_cmd:
                        controller.execute_command(pending_cmd)
                        api.acknowledge_command(
                            command_id=pending_cmd.get("id"),
                            status="completed",
                            reported_pump_state=safety.pump_state
                        )

                last_telemetry_time = now

            # Sleep between ticks (poll rate: 2 seconds)
            time.sleep(2)

        except Exception as e:
            print("[EXCEPTION in main loop]:", e)
            # Local safety rule: on critical unhandled exception, force pump OFF
            safety.force_pump_off("CRITICAL_UNHANDLED_EXCEPTION")
            time.sleep(5)

if __name__ == "__main__":
    main()
