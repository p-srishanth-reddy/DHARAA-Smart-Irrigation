# 🌾 DHARAA: Smart Irrigation & Agronomic IoT System

DHARAA is an IoT smart-irrigation and agronomic decision-support platform designed for precision water conservation, crop health optimization, and safe pump actuation using an **ESP32** (MicroPython) edge node and a **Flask REST API** with **SQLite** persistent storage.

---

## 🌟 Architecture & Core Features

- **Hardware Edge Node (ESP32 / MicroPython):**
  - Capacitive Soil Moisture Sensor (ADC GPIO34) with linear dry/wet calibration formula.
  - DHT22 Ambient Temperature & Relative Humidity (GPIO5).
  - Digital Surface Rain Sensor (GPIO14) for immediate rain inhibition.
  - Water Flow Sensor (GPIO27) with hardware rising-edge interrupt for pulse counting.
  - Relay Module (GPIO26) controlling 5V water pump power.
  - Local Safety Watchdog (Startup OFF, 5-min max runtime, 10-min cooldown, emergency stop).
- **Backend Services (Flask REST API + SQLite):**
  - 8-table relational schema for users, farms, devices, telemetry, schedules, commands, and events.
  - Open-Meteo live weather forecast integration with 30-minute caching and stale warnings.
  - Machine Learning Crop Recommendation: Random Forest Classifier trained on agronomic macronutrient data (95% held-out test accuracy).
  - Agronomic Rule Engine: Automated hysteresis band (Moisture < 35% ON, >= 45% OFF).
  - Command lifecycle state machine: `pending` → `delivered` → `acknowledged` → `completed`.
- **Frontend Dashboard (HTML5 / Modern Dark CSS / Chart.js):**
  - Live field telemetry metrics with stale & sensor error badges.
  - Pump actuation station with distinct **Requested State** vs. **Reported State**.
  - One-click **Emergency Stop** instant hardware lockout.
  - Farm property management, automated irrigation schedules, weather forecasts, and historical analytics.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
Python 3.10+ installed with dependencies:
```bash
pip install -r requirements.txt
```

### 2. Start the Backend Server
```bash
python -m backend.app
```
The server will initialize `backend/dharaa.db` and start listening on:
- Web Dashboard: `http://localhost:5000`
- API Health Check: `http://localhost:5000/api/health`

### 3. Run the Hardware Simulator (Virtual ESP32)
In a separate terminal, launch the simulator:
```bash
python simulate_esp32.py
```
The simulator generates live capacitive moisture readings, simulates soil drying/wetting dynamics, polls commands from the backend, actuates virtual pump relays, and reports hardware acknowledgements.

### 4. Deploying to Physical ESP32 Hardware
1. Flash **MicroPython** firmware to your ESP32 board.
2. Edit `esp32_firmware/config.py`:
   - Set `WIFI_SSID` and `WIFI_PASS`.
   - Set `BACKEND_URL` to your laptop/server's LAN IP (e.g. `http://192.168.1.50:5000`).
   - Calibrate `DRY_RAW` and `WET_RAW` using dry soil vs submerged in water.
3. Upload all files from `esp32_firmware/` (`config.py`, `sensors.py`, `safety.py`, `wifi_manager.py`, `api_client.py`, `irrigation.py`, `main.py`) to the ESP32 root directory using Thonny, `mpremote`, or `ampy`.
4. Power on the ESP32.

## 🗺️ Farm Locality Hierarchy & Coordinate-Based Timezone
Each farm in DHARAA is geo-aware and resolves its administrative hierarchy and exact IANA timezone from its coordinates:
- **Locality Breakdown:** Displays *Village/Locality*, *Mandal/Taluk*, *District*, and *State* (e.g., `Sultan Bazar, Nampally mandal, Hyderabad, Telangana`).
- **Coordinate-Based IANA Timezone:** Resolved using `timezonefinder` from latitude and longitude. Stored in `farms.timezone` and natively supports daylight-saving time (DST) worldwide.
- **Offline Resilience:** All location details and coordinates are stored with the farm in SQLite, remaining available when external geocoding APIs are offline.
- **Auto-Detection & Operator Manual Correction:** Coordinates can be auto-looked up via Nominatim (`POST /api/farms/lookup-coordinates`), and operators can manually edit any place details or correct the IANA timezone in the web interface (`/farms`).

---

## 🕒 Automatic Schedule Execution Service
The DHARAA Flask backend includes a non-blocking background scheduler daemon (`backend/services/scheduler_service.py`) running every 15 seconds:
- **Timezone Awareness:** Uses the farm owner's configured timezone (`users.timezone`, e.g. `Asia/Kolkata`) to compare daily `start_time` (24h `HH:MM`).
- **Single Execution per Occurrence:** Tracks execution via `last_run_date` (`YYYY-MM-DD`). A schedule runs at most once per scheduled daily occurrence.
- **Restart Policy:** Skips missed occurrences after server downtime rather than unexpectedly activating pumps. If a schedule's start time passed while the server was down, it is recorded as `skipped: missed occurrence during downtime`.
- **Pre-Flight Safety Protocol:** Before queueing a pump `ON` command, the scheduler verifies:
  1. Associated ESP32 node is online (last telemetry < 120s old).
  2. Soil moisture sensor health is `'OK'`.
  3. Surface rain sensor detects dry conditions (`rain == 0`).
  4. Cooldown elapsed (>= 600s since previous session ended).
  5. Current soil moisture is below the target threshold.
  6. Runtime cap (<= 300s default, max 600s hard cap).
- **Execution Tracking & Logs:** Logs skip reasons (offline, rain, cooldown, target met, downtime) and updates `schedules.last_run_status` and the user notifications feed.

---

## 🛡️ Safety & Reliability Protocols
1. **Startup OFF Guarantee:** The relay GPIO is set to LOW immediately upon boot before any networking or sensor routines execute.
2. **Local Hardware Watchdog:** The 5-minute single session runtime limit is enforced in local firmware. Even if Wi-Fi or backend server crashes, the ESP32 turns the pump OFF locally.
3. **Emergency Stop:** Immediate top-priority halt that overrides all automated schedules and AI recommendations.
4. **Rain Invalidation:** Rain sensor wet detection inhibits pump start to prevent waterlogging and conserve energy.
5. **No Fabricated Readings:** Parameters not present in the hardware kit (Tank Level, Electricity, NPK, Multi-depth) are honestly labeled as "Not Monitored" per project specifications.
