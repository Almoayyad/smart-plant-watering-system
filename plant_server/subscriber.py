"""
subscriber.py — MQTT subscriber for plant sensor data.
Connects to the MQTT broker, receives JSON payloads from the ESP32,
and stores each message into SQLite using database.py.

Environment variables:
  MQTT_BROKER  — broker hostname or IP  (default: localhost)
  MQTT_PORT    — broker port            (default: 1883)
"""

import json
import os
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

import database

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_PORT", 1883))
TOPIC       = "plant/sensors"

# Required fields that must exist in every message
REQUIRED_FIELDS = [
    "plant_id", "temperature_c", "pressure_hpa",
    "light_lux", "soil_raw", "soil_state", "pump",
    "dry_threshold", "uptime_ms",
]


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connected to broker {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(TOPIC)
        print(f"[MQTT] Subscribed to topic: {TOPIC}")
    else:
        print(f"[MQTT] Connection failed with code {rc}")


def on_message(client, userdata, msg):
    raw = msg.payload.decode("utf-8")
    print(f"\n[MQTT] Received on '{msg.topic}':\n  {raw}")

    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON parse failed: {e}")
        return

    # Validate required fields
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        print(f"[WARN] Missing fields (skipping save): {missing}")
        return

    # Add server-side timestamp (UTC ISO format)
    data["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Save to database
    try:
        database.insert_reading(data)
        print(f"[DB] Saved: plant_id={data['plant_id']}  "
              f"soil={data['soil_raw']} ({data['soil_state']})  "
              f"pump={data['pump']}  "
              f"temp={data['temperature_c']}°C")
    except Exception as e:
        print(f"[ERROR] Failed to save to database: {e}")


def main():
    database.init_db()

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT} ...")

    # Retry loop so Docker startup order doesn't matter
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            break
        except Exception as e:
            print(f"[MQTT] Could not connect: {e} — retrying in 5 seconds...")
            time.sleep(5)

    client.loop_forever()


if __name__ == "__main__":
    main()
