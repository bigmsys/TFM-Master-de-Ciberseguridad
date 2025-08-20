#!/root/python/.venv/bin/python3
import ssl
import json
import time
import pyotp
import paho.mqtt.client as mqtt
import configparser
import os
import random
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes

# Carga la configuración del archivo config.ini
cfg = configparser.ConfigParser()
cfg.read(os.environ.get("CLIENT_CFG", os.path.join(os.path.dirname(__file__), "config.ini")))

# Parámetros MQTT
USER      = cfg["mqtt"]["user"]
PASS      = cfg["mqtt"]["password"]
SECRET    = cfg["mqtt"]["secret"]
BROKER    = cfg["mqtt"].get("broker", "localhost")
PORT      = cfg["mqtt"].getint("port", 8883)
CLIENT_ID = cfg["mqtt"].get("client_id", f"{USER}-metric")

# Topics
TOPIC_TEMP = cfg["mqtt"].get("topic_temp", f"metrics/{USER}/Temperatura")
TOPIC_HUM  = cfg["mqtt"].get("topic_hum",  f"metrics/{USER}/Humedad")

# Archivo de la CA para autenticación con SSL/TLS
CAFILE = cfg["tls"]["ca_certs"]

# Función: Genera código TOTP y se organiza como se espera
def set_creds(c):
    c.username_pw_set(f"{USER}|{pyotp.TOTP(SECRET).now()}", PASS)

# Función: Publica 2 métricas: Temperatura y Humedad
def on_connect(c,u,f,rc,pr):
    if rc!=mqtt.CONNACK_ACCEPTED:
        print(f"❌ {rc}"); return
    print("✅ Conectado, publicando…")
    msgs = [
        (TOPIC_TEMP, {"ts": int(time.time()), "value": round(random.uniform(-5, 60), 1), "unit": "C"}),
        (TOPIC_HUM,  {"ts": int(time.time()), "value": round(random.uniform(0, 100), 1), "unit": "%"}),
    ]
    u["pending"]=set()
    for t,p in msgs:
        info=c.publish(t, json.dumps(p), qos=1, retain=False)
        u["pending"].add(info.mid)

# Función: Se confirman las publicaciones y se desconecta
def on_publish(c,u,mid,reasonCode=None,properties=None):
    u["pending"].discard(mid)
    if not u["pending"]:
        print("📈 Métricas enviadas, desconectando…")
        c.disconnect()

# Se establece el client_id como fijo
cli=mqtt.Client(client_id=CLIENT_ID,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                protocol=mqtt.MQTTv5, userdata={})
# Se valida la CA
cli.tls_set(ca_certs=CAFILE, cert_reqs=ssl.CERT_REQUIRED)

# Si se desconecta indebidamente antes de publicar, publica un aviso en metrics/(user)/Estado
cli.will_set(f"metrics/{USER}/Estado",
                json.dumps({"event":"unsafe_disconnection","ts":int(time.time())}),
                qos=1, retain=False)

# Se genera el TOTP
set_creds(cli)
cli.on_connect=on_connect
cli.on_publish=on_publish

# Sesión efímera
props = Properties(PacketTypes.CONNECT)
props.SessionExpiryInterval = 0
cli.connect(BROKER, PORT, keepalive=10,
            clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY,
            properties=props)

# Bucle para que se publiquen ambas métricas y desconecte
cli.loop_forever()
