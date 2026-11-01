# DHARAA ESP32 MicroPython Configuration
# Configure your network and sensor calibration parameters here

# 1. Network & Backend Configuration
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASS = "YOUR_WIFI_PASSWORD"

# Replace with the LAN IP address of the machine running Flask (e.g., http://192.168.1.15:5000)
# DO NOT use 127.0.0.1 or localhost on the ESP32!
BACKEND_URL = "http://192.168.1.100:5000"
DEVICE_ID = 1
DEVICE_KEY = "dharaa-esp32-secret-2026"

# 2. Hardware Pin Allocations (ESP32)
# Ensure all analog/digital inputs are within 0V - 3.3V tolerance
PIN_MOISTURE_ADC = 34   # ADC1_CH6 (Input only, 3.3V safe)
PIN_DHT22 = 5           # Data pin for DHT22 (needs 4.7k-10k pull-up if not on breakout)
PIN_RAIN_DO = 14        # Digital output from rain sensor comparator
PIN_FLOW = 27           # Flow sensor pulse line (attached to hardware interrupt)
PIN_RELAY = 26          # Output to 3.3V-compatible relay trigger pin
PIN_STATUS_LED = 2      # Onboard / breadboard LED for status indication

# 3. Sensor Calibration Constants
# Soil Moisture: Record raw ADC in bone-dry soil vs submerged in water
DRY_RAW = 3200
WET_RAW = 1100

# Rain Sensor: 0 for active LOW on common LM393 rain modules when wet surface detected
RAIN_WET_LEVEL = 0

# Water Flow Sensor (YF-S201): Pulses per Litre (None if uncalibrated)
FLOW_PULSES_PER_LITRE = 450.0

# 4. Local Safety & Hysteresis Limits (Enforced locally on ESP32)
MOISTURE_START_THRESHOLD = 35.0  # % (Low threshold to turn pump ON in Auto mode)
MOISTURE_STOP_THRESHOLD = 45.0   # % (Recovery threshold to turn pump OFF)
MAX_RUNTIME_SECONDS = 300        # Hard maximum 5-minute single session limit
COOLDOWN_SECONDS = 600           # Minimum 10 minutes required between irrigation runs
TELEMETRY_INTERVAL_SECONDS = 30  # Telemetry transmission period
