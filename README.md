# TFM-Master-de-Ciberseguridad
Este es el repositorio para el TFM del Máster de Ciberseguridad

Securización de Broker MQTT (TFM Máster de Ciberseguridad)

Implementación de un broker Mosquitto securizado con:

TLS (CA propia)

Autenticación TOTP (OTP) vía backend HTTP (Flask + MySQL)

ACL estrictas por usuario (publica solo en su rama)

Sesión efímera (MQTT v5, sin estado residual)

LWT (detectar desconexiones no limpias)

Arquitectura
[Cliente IoT] --TLS/8883--> [Mosquitto + go-auth] --HTTP--> [Flask Backend] --SQL--> [MySQL]


Mosquitto con plugin mosquitto-go-auth (backend HTTP).

Backend Flask valida user|OTP + contraseña base contra MySQL.

ACL: cada usuario solo puede publicar en metrics/<user>/{Temperatura,Humedad,Estado} y leer metrics/<user>/#.

Cliente: publica métricas y se desconecta (QoS 1, SessionExpiry=0, LWT).

Requisitos

Ubuntu/Debian (o similar)

Mosquitto + mosquitto-clients

Python 3.10+ (virtualenv recomendado)

MySQL/MariaDB

OpenSSL

Certificados (TLS)
# CA
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt -subj "/C=ES/ST=Madrid/L=Madrid/O=ACME/CN=ACME"

# Servidor
openssl genrsa -out server.key 4096
openssl req -new -key server.key -out server.csr -subj "/C=ES/ST=Madrid/L=Madrid/O=ACME/CN=broker.mosquitto"

# Extensiones (SAN)
cat > server.ext << 'EOF'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName=DNS:broker.mosquitto,IP:192.168.122.154,IP:127.0.0.1
EOF

# Firma del cert del broker
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365 -sha256 -extfile server.ext


En los clientes solo se distribuye ca.crt.

Mosquitto

/etc/mosquitto/conf.d/default_listeners.conf

listener 8883 0.0.0.0
protocol mqtt
cafile  /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile  /etc/mosquitto/certs/server.key
tls_version tlsv1.2
allow_anonymous false


/etc/mosquitto/conf.d/auth.conf

# Plugin + backend HTTP
auth_plugin /etc/mosquitto/go-auth/go-auth.so
auth_opt_backends http

# HTTP → Flask
auth_opt_http_host 192.168.122.99
auth_opt_http_port 3000
auth_opt_http_response_mode json
auth_opt_http_params_mode   json
auth_opt_http_method        POST
auth_opt_http_getuser_uri   /auth/user
auth_opt_http_superuser_uri /auth/superuser
auth_opt_http_aclcheck_uri  /auth/acl

# Logs (sube a info en prod)
auth_opt_log_level debug
auth_opt_log_dest stdout


Tip: si usas hostname del broker, añade en clientes:
echo "192.168.122.154 broker.mosquitto" >> /etc/hosts

Backend (Flask + MySQL)

Estructura:

backendpy-mqtt/
  app.py
  config.ini
  requirements.txt


config.ini

[mysql]
host = 192.168.122.72
user = mqtt
password = 12qwert5
database = mqtt_auth


Endpoints:

POST /auth/user → valida username="user|OTP" + password="base"

POST /auth/acl → 1=read, 2=write, 4=subscribe

POST /auth/superuser → siempre Ok:false (sin superusuarios)

ACL (resumen):

WRITE permitido: metrics/<user>/{Temperatura,Humedad,Estado}

READ/SUB permitido: metrics/<user>/#

Deniega $SYS/#

Arranque con systemd (/etc/systemd/system/backend-mqtt.service)

[Unit]
Description=Backend Flask MQTT Auth
After=network.target mysql.service

[Service]
WorkingDirectory=/root/python
ExecStart=/root/python/.venv/bin/python /root/python/app.py
Restart=always
User=root

[Install]
WantedBy=multi-user.target

systemctl daemon-reload
systemctl enable --now backend-mqtt

Base de datos

Tabla mínima users:

CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) UNIQUE NOT NULL,
  password VARCHAR(100) NOT NULL, -- bcrypt
  totp_secret VARCHAR(64) NOT NULL
);


Alta de usuario (crear_usuario.py) genera bcrypt + totp_secret:

./crear_usuario.py


Permisos del config.ini: chmod 600 config.ini.

Cliente de métricas (Python)

config.ini (cliente)

[mqtt]
user = iotclient01
password = 12qwert5
secret = WS4CXP7MUNHEHQK2CZYMR65Z5KWTCM3G
broker = broker.mosquitto
port = 8883
client_id = iotclient01-metric
topic_temp = metrics/%(user)s/Temperatura
topic_hum  = metrics/%(user)s/Humedad

[tls]
ca_certs = /root/certs/ca.crt


Características del cliente:

TLS con ca.crt

username = user|OTP (TOTP), password = base

Publica Temperatura y Humedad (QoS 1)

LWT en metrics/<user>/Estado (unsafe_disconnection)

SessionExpiryInterval=0 (sesión efímera)

Se desconecta tras recibir los PUBACK

Prueba rápida:

# Suscriptor (OTP fresco)
OTP=$(python3 - <<'PY'
import pyotp; print(pyotp.TOTP("WS4CXP7MUNHEHQK2CZYMR65Z5KWTCM3G").now())
PY)
mosquitto_sub -h broker.mosquitto -p 8883 --cafile /root/certs/ca.crt \
  -u "iotclient01|$OTP" -P "12qwert5" -t 'metrics/iotclient01/#' -v -d

Cron (opcional)
crontab -e
* * * * * /root/python/.venv/bin/python /root/python/enviar_metricas.py >/dev/null 2>&1


En el script, usa rutas absolutas para config.ini y ca.crt (cron no hereda tu entorno).

Seguridad y buenas prácticas

Tiempo: NTP activo en todas las máquinas (TOTP depende del reloj).

Usuarios: uno por dispositivo y ClientId fijo; deshabilitar cuentas no usadas.

ACL: mínimo privilegio; bloquear $SYS/#.

TLS: SAN correcto en server.crt; rotación periódica; clientes solo confían en CA.

Backend: responde 200 con {"Ok": false} en denegaciones (no 401); systemd con Restart=always.

Archivos sensibles: chmod 600 config.ini.

Troubleshooting

error code: 401 en go-auth → normalmente OTP caducado o backend devolviendo 401. Devuelve 200 {"Ok":false}.

No ves métricas con cron → rutas relativas, hostname sin resolver, o venv distinto. Usa IP//etc/hosts y rutas absolutas.

Cert no válido → revisa subjectAltName y que el cliente use -servername/hostname correcto.

Licencia

Este repositorio es parte de un TFM. Ajusta la licencia según necesidades (MIT, Apache-2.0, etc.).
