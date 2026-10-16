from flask import abort

from vighi.core import db
from vighi.servicios import mensajeria

MAX_LISTA = 200
SQL_MEDICOS = "SELECT id, nombre, email FROM medicos ORDER BY nombre"
SQL_UBICACIONES_POR_MEDICO = "SELECT medico_id, COUNT(*) AS n FROM ubicacion_medicos GROUP BY medico_id"
SQL_PROTOCOLOS_POR_MEDICO = "SELECT medico, COUNT(*) AS n FROM protocolos WHERE borrador=0 AND medico IS NOT NULL AND medico<>'' GROUP BY medico"


def medico_o_404(mid):
    return db.uno("SELECT * FROM medicos WHERE id=?", (mid,)) or abort(404)


def limpiar_nombre(texto):
    return " ".join((texto or "").split())[:150]


def buscar(q):
    todos = db.q(SQL_MEDICOS)
    palabras = db.clave_nombre(q).split()
    if palabras:
        todos = [m for m in todos if all(p in db.clave_nombre(f"{m['nombre']} {m['email'] or ''}") for p in palabras)]
    return todos[:MAX_LISTA], len(todos)


def error_medico(nombre, email, mid=None):
    if not nombre:
        return "Falta el nombre del médico."
    clave = db.clave_nombre(nombre)
    if any(db.clave_nombre(m["nombre"]) == clave for m in db.q(SQL_MEDICOS) if m["id"] != (mid or 0)):
        return f"Ya existe un médico llamado «{nombre}» (se comparan sin tildes ni mayúsculas)."
    if email and not mensajeria.email_valido(email.lower()):
        return "El e-mail no es válido."
    return None


def ubicaciones_de(mid):
    return db.q("SELECT u.id, u.abreviatura FROM ubicacion_medicos m JOIN ubicaciones u ON u.id=m.ubicacion_id WHERE m.medico_id=? ORDER BY u.abreviatura", (mid,))


def protocolos_de(nombre):
    return db.uno("SELECT COUNT(*) AS n FROM protocolos WHERE borrador=0 AND medico=?", (nombre,))["n"]
