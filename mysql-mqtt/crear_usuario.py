#!/root/python/.venv/bin/python3
import configparser
import MySQLdb
import bcrypt
import pyotp

# Leer configuración de conexión de config.ini
config = configparser.ConfigParser()
config.read('config.ini')

# Abre una conexión a MySQL
db = MySQLdb.connect(
    host=config['mysql']['host'],
    user=config['mysql']['user'],
    passwd=config['mysql']['password'],
    db=config['mysql']['database']
)

# Creación de usuario
def crear_usuario(username, password):
    cursor = db.cursor()

    # Comprobación de si el usuarion ya existe
    cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        print(f"El usuario '{username}' ya existe.")
        cursor.close()
        db.close()
        return

    # Creación del hash y TOTP
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    totp_secret = pyotp.random_base32()

    # Insertar nuevo usuario
    sql = "INSERT INTO users (username, password, totp_secret) VALUES (%s, %s, %s)"
    cursor.execute(sql, (username, password_hash, totp_secret))
    db.commit()

    # Mostrar info
    print(f"Usuario creado: {username}")
    print(f"Secreto TOTP: {totp_secret}")

    cursor.close()
    db.close()

# Input interactivo
if __name__ == "__main__":
    user = input("Usuario: ")
    pwd = input("Contraseña: ")
    crear_usuario(user, pwd)
