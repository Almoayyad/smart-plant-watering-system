# Smart Plant Watering System — Server Documentation

## Project Overview

This is a university IoT project that automates plant watering using an ESP32
microcontroller and a cloud-style server stack running in Docker.

The ESP32 reads environmental sensors and decides when to water the plant.
The server receives the data, stores it, and displays it on a live web dashboard.

The system was developed and tested on a Windows laptop and is designed to be
deployed on a Raspberry Pi as the final local edge server.

---

## Final Architecture

The data flow is bidirectional. The ESP32 publishes sensor data; the dashboard
can publish control commands back to the ESP32.

```
┌─────────────────────────────────────────────────────────┐
│                      ESP32 Device                       │
│                                                         │
│  BMP280 ──┐                                             │
│  BH1750 ──┼──► main.cpp ──► MQTT publish (JSON)  ──►  │
│  Soil   ──┘     every 5 seconds   plant/sensors         │
│  Pump   ◄── controlled by ESP32 logic                   │
│             ◄── MQTT subscribe ◄── plant/control ◄──   │
└──────────────────────────────────┬──────────────────────┘
                                   │ WiFi / port 1883
                                   ▼
┌─────────────────────────────────────────────────────────┐
│              Docker Compose (laptop / Pi)                │
│                                                         │
│  ┌─────────────────┐                                    │
│  │   Mosquitto     │  MQTT broker — routes all topics   │
│  │   port 1883     │                                    │
│  └────────┬────────┘                                    │
│           │  plant/sensors                              │
│  ┌────────▼────────┐                                    │
│  │  subscriber.py  │  Parses JSON → saves to SQLite     │
│  └────────┬────────┘                                    │
│           │                                             │
│  ┌────────▼────────┐                                    │
│  │  plant_data.db  │  SQLite database (shared volume)   │
│  └────────┬────────┘                                    │
│           │                                             │
│  ┌────────▼────────┐  plant/control                     │
│  │ streamlit_app   │ ──────────────────► Mosquitto ──► ESP32
│  │  port 8501      │  (when user clicks Apply)          │
│  └─────────────────┘                                    │
└─────────────────────────────────────────────────────────┘
```

---

## File Structure

```
plant_server/
├── database.py        SQLite helper — init table, insert rows, query data
├── subscriber.py      MQTT subscriber → parses JSON → saves to SQLite
├── streamlit_app.py   Streamlit web dashboard
├── requirements.txt   Python dependencies
├── Dockerfile         Docker image for Python services
├── docker-compose.yml Defines all three services
├── mosquitto.conf     Minimal Mosquitto broker config
└── README_server.md   This file
```

---

## Docker Compose Services

The entire server stack is defined in `docker-compose.yml` and starts with a
single command.

### 1. Mosquitto (MQTT Broker)

- Image: `eclipse-mosquitto:2`
- Port: `1883` (exposed to the network so the ESP32 can connect)
- Config: `mosquitto.conf` — allows anonymous connections (no username/password)
- Role: receives MQTT messages published by the ESP32 and forwards them to
  any subscriber listening on the same topic

### 2. Subscriber (Python)

- Built from `Dockerfile` using `requirements.txt`
- Runs: `python subscriber.py`
- Role: connects to the Mosquitto broker, listens on topic `plant/sensors`,
  parses each incoming JSON message, and inserts it into `plant_data.db`
- Automatically retries connection if the broker is not ready yet
- Writes to a shared Docker volume so the dashboard can read the same database

### 3. Streamlit Dashboard

- Built from the same `Dockerfile`
- Runs: `streamlit run streamlit_app.py`
- Port: `8501` (open in browser)
- Role: reads the latest rows from `plant_data.db` and displays them as
  metrics, charts, and alerts
- Auto-refreshes every 5 seconds — no manual page reload needed

---

## How to Run the Project

### Requirements

- Docker Desktop installed and running
- ESP32 powered on and connected to WiFi
- ESP32 `MQTT_SERVER` in `main.cpp` set to your laptop's IP address
  (check with `ipconfig` on Windows — look for IPv4 Address)

### Steps

**1. Open a terminal in the `plant_server` folder:**

```powershell
cd plant_server
```

**2. Start all services:**

```powershell
docker compose up --build
```

Wait until you see output from all three containers. The subscriber will print:

```
[DB] Database ready: /data/plant_data.db
[MQTT] Connected to broker mosquitto:1883
[MQTT] Subscribed to topic: plant/sensors
```

**3. Open the dashboard in your browser:**

```
http://localhost:8501
```

**4. Power on the ESP32.**

Within a few seconds, data will appear on the dashboard.

**5. Stop everything when done:**

```powershell
docker compose down
```

---

## MQTT Topics

The system uses two MQTT topics.

### plant/sensors — ESP32 publishes, server subscribes

The ESP32 publishes one JSON message every 5 seconds.

**Example message:**

```json
{
  "plant_id":         "plant_1",
  "temperature_c":    26.27,
  "pressure_hpa":     1021.03,
  "light_lux":        6.83,
  "soil_raw":         3027,
  "soil_state":       "dry",
  "pump":             "off",
  "dry_threshold":    2500,
  "pump_duration_ms": 1000,
  "uptime_ms":        31004
}
```

| Field              | Source  | Description                                      |
|--------------------|---------|--------------------------------------------------|
| `plant_id`         | ESP32   | Fixed identifier for this plant                  |
| `temperature_c`    | BMP280  | Air temperature in degrees Celsius               |
| `pressure_hpa`     | BMP280  | Atmospheric pressure in hectopascals             |
| `light_lux`        | BH1750  | Ambient light level in lux                       |
| `soil_raw`         | ADC     | Raw analog value from soil moisture sensor       |
| `soil_state`       | ESP32   | `"dry"` or `"wet"` based on threshold comparison |
| `pump`             | ESP32   | `"on"` or `"off"` — current pump state           |
| `dry_threshold`    | ESP32   | Current active dry threshold (adjustable)        |
| `pump_duration_ms` | ESP32   | Current active pump duration in ms (adjustable)  |
| `uptime_ms`        | ESP32   | Milliseconds since last ESP32 boot               |

---

### plant/control — Dashboard publishes, ESP32 subscribes

The Streamlit dashboard publishes control messages when the user clicks
"Apply watering strategy" or "Manual pump test". The ESP32 applies the
new values immediately on receipt.

**Example — update strategy:**

```json
{
  "dry_threshold":    2800,
  "pump_duration_ms": 2000
}
```

**Example — manual pump test:**

```json
{
  "manual_pump_ms": 1000
}
```

All fields are optional — send only the ones you want to change.

| Field              | Range       | Description                                    |
|--------------------|-------------|------------------------------------------------|
| `dry_threshold`    | 1 – 4095    | New dry/wet decision threshold (ADC value)     |
| `pump_duration_ms` | 1 – 5000    | Pump run time per watering cycle (ms)          |
| `manual_pump_ms`   | 1 – 5000    | Triggers the pump immediately for this duration|

Safety: the ESP32 caps any incoming `pump_duration_ms` or `manual_pump_ms`
at 5000 ms and ignores invalid JSON silently.

---

## Database Table

File: `plant_data.db`  
Table: `sensor_data`

| Column          | Type    | Description                               |
|-----------------|---------|-------------------------------------------|
| `id`            | INTEGER | Auto-increment primary key                |
| `timestamp`     | TEXT    | UTC timestamp added by the server         |
| `plant_id`      | TEXT    | Plant identifier from ESP32               |
| `temperature_c` | REAL    | BMP280 temperature in °C                  |
| `pressure_hpa`  | REAL    | BMP280 pressure in hPa                    |
| `light_lux`     | REAL    | BH1750 light level in lux                 |
| `soil_raw`      | INTEGER | Raw ADC reading from soil moisture sensor |
| `soil_state`    | TEXT    | `"dry"` or `"wet"`                        |
| `pump`          | TEXT    | `"on"` or `"off"`                         |
| `dry_threshold` | INTEGER | Threshold value used by ESP32             |
| `uptime_ms`     | INTEGER | ESP32 uptime in milliseconds              |

The timestamp is added by `subscriber.py` on the server side (not by the ESP32)
so it reflects actual wall-clock time regardless of ESP32 clock accuracy.

---

## Dashboard Features

The Streamlit dashboard at `http://localhost:8501` shows:

- **Live metric cards** — temperature, pressure, light, soil value, soil state,
  pump status. Updated on every refresh.

- **Auto-refresh** — the page reloads every 5 seconds automatically.
  A manual "Refresh now" button is also available at the top right.

- **Live alerts** — soil DRY warning; light too low/high based on adjustable
  thresholds; pump ON indicator.

- **Adjustable watering settings** — number inputs for `dry_threshold` and
  `pump_duration_ms`. Clicking "Apply watering strategy" publishes the new
  values to `plant/control` and the ESP32 updates immediately.

- **Manual pump test** — triggers the pump for 1 second directly from the
  dashboard via `plant/control`.

- **Light alert settings** (sidebar) — configurable minimum and maximum
  thresholds for both live light level (lux) and daily light exposure (lux·h).

- **Daily light exposure** — today's accumulated lux-hours estimated from stored
  SQLite readings using numerical integration of the time series.

- **Sensor history charts** — one chart per sensor (temperature, light, soil,
  pressure) showing the trend over the last 200 readings.

- **Soil moisture chart** — includes a red dashed line marking the dry threshold
  so the trigger point is immediately visible.

- **Watering strategy panel** — shows the current soil value vs. threshold and
  whether the condition is DRY or WET.

- **Raw data table** — expandable section showing the 50 most recent rows from
  the database.

---

## Watering Strategy

The watering logic runs entirely on the ESP32. The server only observes and
records — it does not control the pump.

```
soil_raw > dry_threshold  →  soil is DRY  →  pump runs for 1 second
soil_raw ≤ dry_threshold  →  soil is WET  →  pump stays off
```

Current configuration:

| Parameter      | Value |
|----------------|-------|
| `dry_threshold`| 2500  |
| Wet range      | ~2100–2300 (sensor in water) |
| Dry range      | ~3000+ (sensor in air)       |

The ESP32 checks the soil every 5 seconds and activates the pump for exactly
1 second if the soil is dry. The pump state is included in the MQTT message
immediately after the decision is made.

---

## Verify MQTT Messages Manually

To confirm the ESP32 is publishing correctly, open a separate terminal and run:

```powershell
docker exec -it plant_mosquitto mosquitto_sub -h localhost -t plant/sensors -v
```

You should see one line every 5 seconds:

```
plant/sensors {"plant_id":"plant_1","temperature_c":26.27,"pressure_hpa":1021.03,...}
```

If nothing appears, check that the ESP32 is connected to WiFi and that the
`MQTT_SERVER` IP in `main.cpp` matches your current laptop IP (`ipconfig`).

---

## Environment Variables

These are set automatically in Docker Compose. You only need them if running
`subscriber.py` or `streamlit_app.py` manually outside Docker.

| Variable     | Default         | Description                         |
|--------------|-----------------|-------------------------------------|
| `MQTT_BROKER`| `localhost`     | MQTT broker hostname or IP          |
| `MQTT_PORT`  | `1883`          | MQTT broker port                    |
| `DB_PATH`    | `plant_data.db` | Path to the SQLite database file    |

---

## Raspberry Pi Deployment

The development and testing were done on a Windows laptop. The final deployment
target is a Raspberry Pi acting as a local edge server.

Because everything runs in Docker Compose, moving to the Pi requires no code
changes — only configuration.

**Steps to deploy on Raspberry Pi:**

1. Copy the `plant_server` folder to the Raspberry Pi (via USB, `scp`, or git)

2. Make sure Docker and Docker Compose are installed on the Pi:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-plugin
   sudo usermod -aG docker $USER
   ```

3. Start the server stack:
   ```bash
   cd plant_server
   docker compose up --build -d
   ```

4. Find the Pi's IP address:
   ```bash
   hostname -I
   ```

5. Update the ESP32 code — change `MQTT_SERVER` in `main.cpp` to the Pi's IP,
   then re-upload the firmware via PlatformIO.

6. Open the dashboard from any device on the same network:
   ```
   http://<raspberry-pi-ip>:8501
   ```

The Pi will run 24/7 as a standalone server. The laptop is no longer needed
once the Pi is running.

---

## Demo Steps (for University Presentation)

Follow these steps to demonstrate the system live:

1. **Start Docker Desktop** on the laptop (or Pi).

2. **Start the server stack:**
   ```powershell
   docker compose up --build
   ```

3. **Power on the ESP32.** Wait for it to connect to WiFi and MQTT.

4. **Open the dashboard** at `http://localhost:8501`.
   Live sensor values appear within 5 seconds.

5. **Show DRY state:**
   - Hold the soil sensor in the air (or keep it dry).
   - `soil_raw` will read above 2500.
   - Dashboard shows `SOIL STATE: DRY` and a yellow warning.
   - The pump activates for 1 second and `pump: on` appears briefly.

6. **Show WET state:**
   - Dip the soil sensor in a glass of water.
   - `soil_raw` drops to ~2100–2300.
   - Dashboard shows `SOIL STATE: WET` and the condition turns green.
   - Pump stays off.

7. **Show the trend charts:**
   - Switch between the Temperature, Light, Soil, and Pressure tabs.
   - Point out the red dashed dry threshold line on the soil chart.

8. **Remove the sensor from water:**
   - `soil_raw` rises above 2500 again.
   - System returns to DRY state and the pump activates.

9. **Show the raw data table:**
   - Expand the "Show raw data table" section.
   - Every row is a real sensor reading stored in SQLite.

---

## University Presentation Summary

> This project implements a Smart Plant Watering System using an ESP32
> microcontroller and a containerized server stack. The ESP32 reads temperature,
> pressure, light, and soil moisture data, and automatically activates a water
> pump when the soil becomes too dry. Sensor data is published over WiFi using
> the MQTT protocol to a Mosquitto broker running in Docker. A Python subscriber
> receives the messages and stores them in a SQLite database. A Streamlit web
> dashboard reads the database and displays live sensor values, historical charts,
> and the current watering state — refreshing automatically every 5 seconds. The
> entire server stack is defined in a single Docker Compose file, making it fully
> reproducible on any machine, including a Raspberry Pi acting as a local edge
> server.
