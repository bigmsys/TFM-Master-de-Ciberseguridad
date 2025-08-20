#!/root/python/.venv/bin/python3

from flask import Flask, request, jsonify
import MySQLdb
import bcrypt
import pyotp
import configparser

# Inicializa Flask y carga la configuración del archivo config.ini
app = Flask(__name__)
cfg = configparser.ConfigParser()
cfg.read('config.ini')

# Función: Abre una conexión nueva a MySQL
def get_db():
    return MySQLdb.connect(
        host=cfg['mysql']['host'],
        user=cfg['mysql']['user'],
        passwd=cfg['mysql']['password'],
        db=cfg['mysql']['database']
    )

# Health check de los directorios
@app.route('/auth/user', methods=['GET'])
def auth_user_health():
    return jsonify({"allow": False}), 200

@app.route('/auth/superuser', methods=['GET'])
def auth_super_health():
    return jsonify({"allow": False}), 200

@app.route('/auth/acl', methods=['GET'])
def auth_acl_health():
    return jsonify({"allow": False}), 200

# Función: Comprobación Usuario|TOTP + Password
@app.route('/auth/user', methods=['POST'])
def auth_user():
    data = request.get_json() or {}
    user_totp = data.get('username','')
    pwd = data.get('password','')

    # split user|otp
    try:
        user, otp = user_totp.split('|')
    except:
        return jsonify({"allow": False}), 401

    # Consulta en la BBDD la contraseña y el secreto TOTP
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT password, totp_secret FROM users WHERE username=%s", (user,))
    row = cur.fetchone()
    cur.close()
    db.close()

    # Valida la contraseña con bcrypt
    if not row or not bcrypt.checkpw(pwd.encode(), row[0].encode()):
        return jsonify({"Ok": False}), 401

    # Verifica TOTP de manera que permite el codigo actual, el anterior y el posterior por posibles desajustes de horarios
    if not pyotp.TOTP(row[1]).verify(otp, valid_window=1):
        return jsonify({"Ok": False}), 401

    return jsonify({"Ok": True}), 200

# Función: Nadie es super usuario
@app.route('/auth/superuser', methods=['POST'])
def auth_super():
    return jsonify({"Ok": False}), 200

# Configuración sin restricciones acl
#@app.route('/auth/acl', methods=['POST'])
#def auth_acl():
#    # For simplicity, allow everything here:
#    return jsonify({"Ok": True}), 200

# Función: Configuración de ACL
@app.route('/auth/acl', methods=['POST'])
def auth_acl():
    d = request.get_json(silent=True) or request.form or {}
    user_totp = d.get("username","")
    topic = d.get("topic","")
    acc_raw = d.get("acc", d.get("access", d.get("type", 0)))

    # Normalización de tipo de acceso: 1=Read, 2=Write, 4=Subscribe
    try:
        acc = int(acc_raw)
    except:
        acc = {"read":1,"write":2,"subscribe":4,"1":1,"2":2,"4":4}.get(str(acc_raw).lower(),0)

    # Extrae el username de "user|TOTP"
    try: user, _ = user_totp.split("|", 1)
    except: return jsonify({"Ok": False}), 200

    # Bloquea topics del sistema
    if topic.startswith("$SYS/"):
        return jsonify({"Ok": False}), 200

    # Permiso Write: solo estas 3 rutas
    if acc == 2:
        allowed_pub = {
            f"metrics/{user}/Temperatura",
            f"metrics/{user}/Humedad",
            f"metrics/{user}/Estado",
        }
        return jsonify({"Ok": topic in allowed_pub}), 200

    # Permiso de Read / Subscribe: solo su subárbol propio
    if acc in (1, 4):
        ok = topic == f"metrics/{user}/#" or topic.startswith(f"metrics/{user}/")
        return jsonify({"Ok": ok}), 200

    return jsonify({"Ok": False}), 200

# Inicia el servidor flask
if __name__=='__main__':
    app.run(host='0.0.0.0', port=3000)
