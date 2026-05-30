#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>
#include <BH1750.h>

// ================= Pins =================
#define I2C_SDA 21
#define I2C_SCL 22

#define SOIL_PIN 32
#define PUMP_PIN 25

// ================= Pump Safety =================
// Maximum pump duration accepted from any control message
#define MAX_PUMP_DURATION_MS 5000

// ================= Watering Strategy =================
// These can be updated at runtime via MQTT topic: plant/control
int dryThreshold   = 2500;  // soil_raw above this → soil is dry
int pumpDurationMs = 1000;  // pump runs for this many ms per watering cycle

// ================= Pump Signal =================
#define PUMP_ON  HIGH
#define PUMP_OFF LOW

// ================= WiFi =================
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// ================= MQTT =================
const char* MQTT_SERVER = "YOUR_MQTT_SERVER_IP";
const int   MQTT_PORT   = 1883;

const char* TOPIC_SENSOR  = "plant/sensors";   // ESP32 publishes here
const char* TOPIC_CONTROL = "plant/control";   // ESP32 subscribes here

// ================= Objects =================
WiFiClient      espClient;
PubSubClient    client(espClient);
Adafruit_BMP280 bmp;
BH1750          lightMeter;

// ================= State =================
bool bmpOk     = false;
bool lightOk   = false;
bool pumpState = false;

unsigned long lastPublish = 0;
const unsigned long PUBLISH_INTERVAL = 5000;

// ================= MQTT Callback =================
// Called by PubSubClient when a message arrives on a subscribed topic.
// Handles strategy updates and manual pump triggers from plant/control.
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char msg[256];
  if (length >= sizeof(msg)) {
    Serial.println("[MQTT] Incoming message too long — ignored.");
    return;
  }
  memcpy(msg, payload, length);
  msg[length] = '\0';

  Serial.print("[MQTT] Message on '");
  Serial.print(topic);
  Serial.print("': ");
  Serial.println(msg);

  if (strcmp(topic, TOPIC_CONTROL) != 0) return;

  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, msg);
  if (err) {
    Serial.print("[Control] JSON error: ");
    Serial.println(err.c_str());
    return;
  }

  // Update dry threshold (must be a valid ADC range)
  if (doc.containsKey("dry_threshold")) {
    int v = doc["dry_threshold"].as<int>();
    if (v > 0 && v < 4096) {
      dryThreshold = v;
      Serial.print("[Control] dry_threshold updated to: ");
      Serial.println(dryThreshold);
    }
  }

  // Update pump duration (capped by safety limit)
  if (doc.containsKey("pump_duration_ms")) {
    int v = doc["pump_duration_ms"].as<int>();
    if (v > 0 && v <= MAX_PUMP_DURATION_MS) {
      pumpDurationMs = v;
      Serial.print("[Control] pump_duration_ms updated to: ");
      Serial.println(pumpDurationMs);
    }
  }

  // Manual pump trigger — runs immediately for the requested duration
  if (doc.containsKey("manual_pump_ms")) {
    int v = doc["manual_pump_ms"].as<int>();
    if (v > 0) {
      v = min(v, MAX_PUMP_DURATION_MS);
      Serial.print("[Control] Manual pump for ");
      Serial.print(v);
      Serial.println(" ms");
      digitalWrite(PUMP_PIN, PUMP_ON);
      pumpState = true;
      delay(v);
      digitalWrite(PUMP_PIN, PUMP_OFF);
      pumpState = false;
      Serial.println("[Control] Manual pump done.");
    }
  }
}

// ================= WiFi Connect =================
void connectWiFi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected.");
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());
}

// ================= MQTT Connect =================
void connectMQTT() {
  while (!client.connected()) {
    Serial.print("Connecting to MQTT... ");

    String clientId = "ESP32-Plant-";
    clientId += String(random(0xffff), HEX);

    if (client.connect(clientId.c_str())) {
      Serial.println("connected.");
      // Re-subscribe on every (re)connect to survive broker restarts
      client.subscribe(TOPIC_CONTROL);
      Serial.print("Subscribed to: ");
      Serial.println(TOPIC_CONTROL);
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" — retry in 5 seconds");
      delay(5000);
    }
  }
}

// ================= Sensors Setup =================
void setupSensors() {
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(100000);

  if (bmp.begin(0x76)) {
    bmpOk = true;
    Serial.println("SUCCESS: BMP280 Online.");
  } else {
    bmpOk = false;
    Serial.println("ERROR: BMP280 failed to start!");
  }

  if (lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x23, &Wire)) {
    lightOk = true;
    Serial.println("SUCCESS: BH1750 Online.");
  } else {
    lightOk = false;
    Serial.println("ERROR: BH1750 failed to start!");
  }
}

// ================= Setup =================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n--- Plant System MQTT Version ---");

  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, PUMP_OFF);

  setupSensors();
  connectWiFi();

  client.setServer(MQTT_SERVER, MQTT_PORT);
  client.setCallback(mqttCallback);

  Serial.println("Setup complete.");
}

// ================= Loop =================
void loop() {
  if (!client.connected()) {
    connectMQTT();
  }

  client.loop();  // process incoming MQTT messages → calls mqttCallback

  if (millis() - lastPublish >= PUBLISH_INTERVAL) {
    lastPublish = millis();

    int   soilValue   = analogRead(SOIL_PIN);
    float temperature = bmpOk   ? bmp.readTemperature()       : -999;
    float pressure    = bmpOk   ? bmp.readPressure() / 100.0F : -999;
    float light       = lightOk ? lightMeter.readLightLevel() : -999;

    String soilState;

    if (soilValue > dryThreshold) {
      soilState = "dry";
      Serial.println("Soil is DRY -> Pump ON");

      digitalWrite(PUMP_PIN, PUMP_ON);
      pumpState = true;
      delay(pumpDurationMs);

      digitalWrite(PUMP_PIN, PUMP_OFF);
      pumpState = false;

      Serial.println("Pump OFF");
    } else {
      soilState = "wet";
      digitalWrite(PUMP_PIN, PUMP_OFF);
      pumpState = false;
      Serial.println("Soil is WET -> Pump OFF");
    }

    StaticJsonDocument<300> doc;
    doc["plant_id"]          = "plant_1";
    doc["temperature_c"]     = temperature;
    doc["pressure_hpa"]      = pressure;
    doc["light_lux"]         = light;
    doc["soil_raw"]          = soilValue;
    doc["soil_state"]        = soilState;
    doc["pump"]              = pumpState ? "on" : "off";
    doc["dry_threshold"]     = dryThreshold;
    doc["pump_duration_ms"]  = pumpDurationMs;
    doc["uptime_ms"]         = millis();

    char buffer[300];
    serializeJson(doc, buffer);

    Serial.println("\n--- Publishing MQTT ---");
    Serial.println(buffer);

    if (client.publish(TOPIC_SENSOR, buffer)) {
      Serial.println("MQTT publish success.");
    } else {
      Serial.println("MQTT publish failed.");
    }
  }
}
