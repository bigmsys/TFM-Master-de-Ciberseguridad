# Securización de Broker MQTT (TFM Máster de Ciberseguridad)

Implementación de un broker **Mosquitto** securizado con:
- **TLS** (CA propia)
- **Autenticación TOTP (OTP)** vía **backend HTTP (Flask + MySQL)**
- **ACL estrictas por usuario** (publica sólo en su rama)
- **Sesión efímera** (MQTT v5, sin estado residual)
- **LWT** (detectar desconexiones no limpias)

## Arquitectura

[Cliente IoT] --TLS/8883--> [Mosquitto + go-auth] --HTTP--> [Flask Backend] --SQL--> [MySQL]

- **Mosquitto** con plugin **mosquitto-go-auth** (backend **HTTP**).
- **Backend Flask** valida `user|OTP` + contraseña base contra **MySQL**.
- **ACL**: cada usuario sólo puede publicar en `metrics/<user>/{Temperatura,Humedad,Estado}` y leer `metrics/<user>/#`.
- **Cliente**: publica métricas y se desconecta (QoS 1, **SessionExpiry=0**, **LWT**).

---

## Requisitos

- Ubuntu/Debian (o similar)
- Mosquitto + mosquitto-clients
- Python 3.10+ (virtualenv recomendado)
- MySQL/MariaDB
- OpenSSL

---

## Certificados (TLS)

```bash
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
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial   -out server.crt -days 365 -sha256 -extfile server.ext
```

En los clientes sólo se distribuye ca.crt.

Verificación rápida:

```bash
openssl x509 -in ca.crt -text -noout
openssl x509 -in server.crt -text -noout
openssl verify -CAfile ca.crt server.crt
```

Si usas hostname del broker, añade en clientes:
```bash
echo "192.168.122.154 broker.mosquitto" | sudo tee -a /etc/hosts
```

---

## Backend (Flask + MySQL)
### app.py (resumen de endpoints):

- `POST /auth/user` → valida username="user|OTP" + password="base" (bcrypt + TOTP).
- `POST /auth/acl` → 1=read, 2=write, 4=subscribe.  
  WRITE permitido: metrics/<user>/{Temperatura,Humedad,Estado}  
  READ/SUB permitido: metrics/<user>/#  
  Deniega $SYS/#
- `POST /auth/superuser` → siempre `{"Ok": false}` (sin superusuarios).

### Arranque con systemd

`/etc/systemd/system/backend-mqtt.service`

```ini
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
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now backend-mqtt
sudo systemctl status backend-mqtt
```

---

## Base de datos

Tabla mínima users:

```sql
CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) UNIQUE NOT NULL,
  password VARCHAR(100) NOT NULL, -- bcrypt
  totp_secret VARCHAR(64) NOT NULL
);
```

Alta de usuario (`crear_usuario.py`) genera bcrypt + totp_secret:

```bash
chmod 600 config.ini  # proteger credenciales
./crear_usuario.py
```

---

## Cliente de métricas (Python)
### Puntos clave del cliente:

- TLS con ca.crt  
- username = user|OTP (TOTP), password = base  
- Publica Temperatura y Humedad (QoS 1)  
- LWT en metrics/<user>/Estado (ej. unsafe_disconnection)  
- SessionExpiryInterval=0 (sesión efímera, MQTT v5)  
- Se desconecta tras recibir los PUBACK  

### Prueba rápida de suscripción:

```bash
OTP=$(python3 - <<'PY'
import pyotp; print(pyotp.TOTP("WS4CXP7MUNHEHQK2CZYMR65Z5KWTCM3G").now())
PY)
mosquitto_sub -h broker.mosquitto -p 8883 --cafile /root/certs/ca.crt   -u "iotclient01|$OTP" -P "12qwert5" -t 'metrics/iotclient01/#' -v -d
```

### Publicación de ejemplo:

```bash
OTP=$(python3 - <<'PY'
import pyotp; print(pyotp.TOTP("WS4CXP7MUNHEHQK2CZYMR65Z5KWTCM3G").now())
PY)
mosquitto_pub -h broker.mosquitto -p 8883 --cafile /root/certs/ca.crt   -u "iotclient01|$OTP" -P "12qwert5"   -t "metrics/iotclient01/Temperatura" -m '{"value":22.5}'
```

---

## Cron

```bash
crontab -e
* * * * * /root/python/.venv/bin/python /root/python/enviar_metricas.py >/dev/null 2>&1
```

En el script, usa rutas absolutas para config.ini y ca.crt (cron no hereda tu entorno).

---

## Seguridad y buenas prácticas

- Tiempo: NTP activo en todas las máquinas (TOTP depende del reloj).
- Usuarios: un usuario por dispositivo y ClientId fijo; deshabilitar cuentas no usadas.
- ACL: mínimo privilegio; bloquear $SYS/#.
- TLS: SAN correcto en server.crt; rotación periódica; clientes confían sólo en CA.
- Backend: responder 200 con {"Ok": false} en denegaciones (no 401); systemd con Restart=always.
- Archivos sensibles: chmod 600 config.ini.

---

## Troubleshooting

- error code: 401 en go-auth → OTP caducado o backend devolviendo 401. Devuelve 200 {"Ok":false} para denegar sin “api error”.
- No ves métricas con cron → rutas relativas/hostname sin resolver/venv distinto. Usa IP o /etc/hosts y rutas absolutas.
- Cert no válido → revisa subjectAltName y que el cliente use el hostname correcto.

---

## Licencia

Copyright (C) 2025 bigmsys

Este proyecto se distribuye bajo los términos de la **GNU General Public License v3.0 (GPL-3.0)**.  
Puedes redistribuirlo y/o modificarlo bajo dicha licencia publicada por la Free Software Foundation.  

Este software se distribuye "tal cual", sin ninguna garantía, incluso sin la garantía implícita de **COMERCIABILIDAD** o **IDONEIDAD PARA UN PROPÓSITO PARTICULAR**.  
Consulta el archivo [LICENSE](LICENSE) para más detalles o visita <https://www.gnu.org/licenses/gpl-3.0.html>.

