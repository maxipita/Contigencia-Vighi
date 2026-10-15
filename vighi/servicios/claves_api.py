import hashlib
import secrets
from datetime import datetime, timedelta

from vighi.core import db

SQL_CLAVES = """SELECT k.id, k.nombre, k.creada_en, k.ultimo_uso, k.activa, u.iniciales FROM claves_api k
                LEFT JOIN usuarios u ON u.id=k.creada_por ORDER BY k.activa DESC, k.id DESC"""


def huella(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def crear_clave(nombre, yo):
    token = "vgh_" + secrets.token_urlsafe(32)
    db.ex("INSERT INTO claves_api (nombre, huella, creada_por, creada_en) VALUES (?,?,?,?)", (nombre, huella(token), yo, db.ahora()))
    db.auditar(yo, None, "clave_api", f"creó la clave «{nombre}»")
    return token


def clave_valida(token):
    if not token:
        return None
    k = db.uno("SELECT id, nombre, ultimo_uso FROM claves_api WHERE huella=? AND activa=1", (huella(token),))
    if k:
        limite = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        if not k["ultimo_uso"] or k["ultimo_uso"] < limite:
            db.ex("UPDATE claves_api SET ultimo_uso=? WHERE id=?", (db.ahora(), k["id"]))
    return k


def revocar_clave(kid, yo):
    k = db.uno("SELECT id, nombre FROM claves_api WHERE id=? AND activa=1", (kid,))
    if k:
        db.ex("UPDATE claves_api SET activa=0 WHERE id=?", (kid,))
        db.auditar(yo, None, "clave_api", f"revocó la clave «{k['nombre']}»")
    return k


def claves():
    return db.q(SQL_CLAVES)
