"""
streamlit_app.py — Streamlit dashboard for the Smart Plant Watering System.

Reads sensor data from SQLite and visualizes it.
Publishes adjustable watering settings to MQTT topic: plant/control.

Run with:
  streamlit run streamlit_app.py
"""

import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import paho.mqtt.publish as mqtt_publish
import streamlit as st

import database

# ─── MQTT Settings ───────────────────────────────────────────────────────────
# Defaults to localhost for local development.
# In Docker Compose, MQTT_BROKER is set to "mosquitto" via environment variable.
MQTT_BROKER   = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_CONTROL = "plant/control"

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Smart Plant Watering",
    page_icon="🌱",
    layout="wide",
)

# ─── Helper: publish one MQTT control message ─────────────────────────────────
def publish_control(payload: dict) -> bool:
    """Connect to broker, publish payload to plant/control, disconnect."""
    try:
        mqtt_publish.single(
            topic=TOPIC_CONTROL,
            payload=json.dumps(payload),
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
            client_id="streamlit-dashboard",
        )
        return True
    except Exception as e:
        st.error(f"MQTT publish failed — is the broker running? ({e})")
        return False

# ─── Helper: today's light readings for daily exposure calculation ────────────
def get_today_light_data() -> pd.DataFrame:
    """
    Query all light readings stored today (UTC date).
    Used to estimate daily lux-hour exposure.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sql = (
        "SELECT timestamp, light_lux FROM sensor_data "
        "WHERE timestamp LIKE ? ORDER BY id ASC"
    )
    with database.get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=(f"{today}%",))

# ─── Sidebar: Light Alert Settings ───────────────────────────────────────────
# These thresholds are dashboard-only settings (not sent to ESP32).
# Values persist across auto-refreshes via Streamlit session state.
with st.sidebar:
    st.header("☀️ Light Alert Settings")
    st.caption("Adjust thresholds for live and daily light alerts.")

    st.markdown("**Live light level**")
    min_live_lux = st.number_input(
        "Min live light (lux)",
        min_value=0.0, max_value=10000.0,
        value=50.0, step=10.0,
        key="min_live_lux",
        help="Alert if the latest reading falls below this value.",
    )
    max_live_lux = st.number_input(
        "Max live light (lux)",
        min_value=0.0, max_value=100000.0,
        value=50000.0, step=1000.0,
        key="max_live_lux",
        help="Alert if the latest reading exceeds this value.",
    )

    st.divider()

    st.markdown("**Daily light exposure**")
    min_daily_lux_h = st.number_input(
        "Min daily exposure (lux·h)",
        min_value=0.0, max_value=10000.0,
        value=100.0, step=10.0,
        key="min_daily_lux_h",
        help="Alert if today's accumulated light is below this value.",
    )
    max_daily_lux_h = st.number_input(
        "Max daily exposure (lux·h)",
        min_value=0.0, max_value=100000.0,
        value=5000.0, step=100.0,
        key="max_daily_lux_h",
        help="Alert if today's accumulated light exceeds this value.",
    )

# ─── Header ──────────────────────────────────────────────────────────────────
col_title, col_btn = st.columns([6, 1])
col_title.title("🌱 Smart Plant Watering System")
col_title.caption("Live dashboard — data from ESP32 via MQTT → SQLite")
if col_btn.button("🔄 Refresh now", use_container_width=True):
    st.rerun()

# ─── Load Data ───────────────────────────────────────────────────────────────
database.init_db()
df = database.get_recent_data(limit=200)

# ─── No Data State ───────────────────────────────────────────────────────────
if df.empty:
    st.info(
        "No data yet. Make sure the ESP32 is running and subscriber.py "
        "is connected to the MQTT broker."
    )
    if st.button("🔄 Refresh"):
        st.rerun()
    st.stop()

# ─── Latest Row ──────────────────────────────────────────────────────────────
latest = df.iloc[-1]

# ─── Status Line ─────────────────────────────────────────────────────────────
st.markdown(
    f"**Last reading:** `{latest['timestamp']}`   |   "
    f"Total records: `{len(df)}`"
)

# ─── Live Alerts ─────────────────────────────────────────────────────────────
if latest["soil_state"] == "dry":
    st.warning("⚠️  Soil is DRY — pump should activate on the next cycle.")

live_lux = float(latest["light_lux"]) if pd.notna(latest["light_lux"]) else 0.0
if live_lux < min_live_lux:
    st.warning(
        f"⚠️  Light level is too low ({live_lux:.1f} lux < {min_live_lux:.0f} lux). "
        "Plant may need more light."
    )
elif live_lux > max_live_lux:
    st.warning(
        f"⚠️  Light level is too high ({live_lux:.1f} lux > {max_live_lux:.0f} lux)."
    )
else:
    st.success(f"✅ Live light is within the selected range ({live_lux:.1f} lux).")

if latest["pump"] == "on":
    st.info("💧 Pump is currently ON.")

# ─── Current Readings ────────────────────────────────────────────────────────
st.subheader("Current Readings")

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("🌡️ Temperature",  f"{latest['temperature_c']:.1f} °C")
col2.metric("🌀 Pressure",     f"{latest['pressure_hpa']:.1f} hPa")
col3.metric("☀️ Light",        f"{latest['light_lux']:.1f} lux")
col4.metric("💧 Soil Raw",     int(latest["soil_raw"]))
col5.metric("🌱 Soil State",   str(latest["soil_state"]).upper())
col6.metric("⚙️ Pump",         str(latest["pump"]).upper())

# ─── Watering Strategy ───────────────────────────────────────────────────────
st.subheader("Watering Strategy")

threshold = int(latest["dry_threshold"])
soil_raw  = int(latest["soil_raw"])

col_a, col_b = st.columns(2)
col_a.markdown(f"""
| Setting          | Value |
|------------------|-------|
| Dry Threshold    | `{threshold}` |
| Current Soil     | `{soil_raw}` |
| Condition        | **{'DRY 🔴' if soil_raw > threshold else 'WET 🟢'}** |
""")
col_b.info(
    f"If `soil_raw` > `{threshold}` → soil is **dry** → pump runs.  \n"
    f"If `soil_raw` ≤ `{threshold}` → soil is **wet** → pump stays off."
)

# ─── Adjustable Watering Settings ────────────────────────────────────────────
st.subheader("Adjustable Watering Settings")
st.caption(
    f"Send new settings to the ESP32 via MQTT (topic: `{TOPIC_CONTROL}`).  "
    "Changes take effect on the next ESP32 watering cycle."
)

col_s1, col_s2 = st.columns(2)

new_threshold = col_s1.number_input(
    "Dry threshold (ADC value)",
    min_value=500, max_value=4000,
    value=threshold,
    step=50,
    key="new_threshold",
    help="ESP32 compares soil_raw against this value. Higher = triggers watering sooner.",
)
new_duration = col_s2.number_input(
    "Pump duration per cycle (ms)",
    min_value=100, max_value=5000,
    value=1000,
    step=100,
    key="new_duration",
    help="How long the pump runs when soil is dry. Maximum allowed: 5000 ms.",
)

col_b1, col_b2 = st.columns(2)

if col_b1.button("📤 Apply watering strategy", use_container_width=True):
    payload = {
        "dry_threshold":    new_threshold,
        "pump_duration_ms": new_duration,
    }
    if publish_control(payload):
        st.toast(
            f"Strategy sent: threshold={new_threshold}, duration={new_duration} ms",
            icon="✅",
        )

if col_b2.button("💧 Manual pump test (1 second)", use_container_width=True):
    if publish_control({"manual_pump_ms": 1000}):
        st.toast("Manual pump triggered for 1 second.", icon="💧")

# ─── Light Alert Details ──────────────────────────────────────────────────────
st.subheader("Light Alert Details")

# Estimate today's accumulated light exposure from stored readings.
# Method: sum of (light_lux × Δt_hours) for each reading interval.
# Gaps larger than 10 minutes are capped to avoid inflating the estimate
# when the ESP32 was offline for part of the day.
df_today = get_today_light_data()

if df_today.empty:
    st.info("No light data recorded today yet.")
    daily_lux_h = 0.0
else:
    df_today["time_dt"] = pd.to_datetime(df_today["timestamp"], utc=True)
    df_today = df_today.sort_values("time_dt").reset_index(drop=True)
    dt_hours = (
        df_today["time_dt"]
        .diff()
        .dt.total_seconds()
        .div(3600)
        .fillna(5 / 3600)        # assume 5 s for the very first reading
        .clip(upper=600 / 3600)  # cap gaps at 10 minutes
    )
    daily_lux_h = float((df_today["light_lux"] * dt_hours).sum())

col_d1, col_d2 = st.columns(2)
col_d1.metric("Today's light exposure", f"{daily_lux_h:.1f} lux·h")
col_d1.caption(
    f"Estimated from {len(df_today)} readings since midnight UTC."
)

if daily_lux_h < min_daily_lux_h:
    col_d2.warning(
        f"⚠️  Daily exposure is too low ({daily_lux_h:.1f} lux·h).  \n"
        f"Minimum set to {min_daily_lux_h:.0f} lux·h. "
        "The plant may not be getting enough light today."
    )
elif daily_lux_h > max_daily_lux_h:
    col_d2.warning(
        f"⚠️  Daily exposure is very high ({daily_lux_h:.1f} lux·h).  \n"
        f"Maximum set to {max_daily_lux_h:.0f} lux·h. "
        "The plant may be getting too much light."
    )
else:
    col_d2.success(
        f"✅ Daily exposure is within the selected range ({daily_lux_h:.1f} lux·h)."
    )

# ─── Sensor History ───────────────────────────────────────────────────────────
st.subheader("Sensor History")

tab1, tab2, tab3, tab4 = st.tabs(
    ["🌡️ Temperature", "☀️ Light", "💧 Soil", "🌀 Pressure"]
)

with tab1:
    fig = px.line(df, x="timestamp", y="temperature_c",
                  title="Temperature over Time",
                  labels={"temperature_c": "°C", "timestamp": "Time"})
    fig.update_traces(line_color="#FF6B6B")
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    fig = px.line(df, x="timestamp", y="light_lux",
                  title="Light Level over Time",
                  labels={"light_lux": "lux", "timestamp": "Time"})
    fig.update_traces(line_color="#FFD93D")
    st.plotly_chart(fig, use_container_width=True)

with tab3:
    fig = px.line(df, x="timestamp", y="soil_raw",
                  title="Soil Moisture (raw ADC) over Time",
                  labels={"soil_raw": "ADC value", "timestamp": "Time"})
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Dry threshold ({threshold})",
        annotation_position="top left",
    )
    fig.update_traces(line_color="#6BCB77")
    st.plotly_chart(fig, use_container_width=True)

with tab4:
    fig = px.line(df, x="timestamp", y="pressure_hpa",
                  title="Atmospheric Pressure over Time",
                  labels={"pressure_hpa": "hPa", "timestamp": "Time"})
    fig.update_traces(line_color="#4D96FF")
    st.plotly_chart(fig, use_container_width=True)

# ─── Raw Data Table ──────────────────────────────────────────────────────────
with st.expander("Show raw data table"):
    st.dataframe(df.tail(50), use_container_width=True)

# ─── Auto Refresh ────────────────────────────────────────────────────────────
# Streamlit re-runs the entire script after st.rerun().
# Sleeping here and calling rerun() is all that is needed — no extra packages.
st.caption("Auto-refreshing every 5 seconds...")
time.sleep(5)
st.rerun()
