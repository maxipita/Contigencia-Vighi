from flask import abort

from vighi.core import db

CAMPOS_LUGAR = (("lugar_recoleccion", "Lugar recolección"), ("lugar_entrega", "Lugar entrega"))
SQL_UBICACIONES = """SELECT u.*, (SELECT COUNT(*) FROM ubicacion_medicos m WHERE m.ubicacion_id=u.id) AS n_medicos
                     FROM ubicaciones u ORDER BY u.abreviatura"""


def sql_protocolos_por_lugar(campo):
    return f"SELECT {campo} AS lugar, COUNT(*) AS n FROM protocolos WHERE borrador=0 AND {campo} IS NOT NULL GROUP BY {campo}"


def error_ubicaciones(d, actual=None):
    for campo, rotulo in CAMPOS_LUGAR:
        v = d.get(campo)
        if not v or (actual is not None and v == (actual[campo] or "")):
            continue
        if not db.uno("SELECT 1 FROM ubicaciones WHERE abreviatura=?", (v,)):
            return f"{rotulo}: elegí una ubicación de la lista. Si falta, se crea en Ubicaciones."
    return None


def ubicacion_o_404(uid):
    return db.uno("SELECT * FROM ubicaciones WHERE id=?", (uid,)) or abort(404)


def destinos_por_ubicacion(ids=None):
    filas = db.q("SELECT id, ubicacion_id, canal, destino, informes, alcance FROM ubicacion_destinos ORDER BY canal, destino")
    salida = {}
    for f in filas:
        if ids is None or f["ubicacion_id"] in ids:
            salida.setdefault(f["ubicacion_id"], []).append(f)
    return salida


def emails_de_informes(destinos):
    return [d["destino"] for d in destinos if d["canal"] == "email" and d["informes"]]


def ubicaciones_del_protocolo(p):
    lugares = list(dict.fromkeys(l for l in (p["lugar_recoleccion"], p["lugar_entrega"]) if l))
    if not lugares:
        return {}
    ubicaciones = {u["abreviatura"]: dict(u) for u in db.q(
        f"SELECT id, abreviatura, nombre, contactos FROM ubicaciones WHERE abreviatura IN ({','.join('?' * len(lugares))})", tuple(lugares))}
    destinos = destinos_por_ubicacion({u["id"] for u in ubicaciones.values()}) if ubicaciones else {}
    for u in ubicaciones.values():
        u["emails"] = ", ".join(emails_de_informes(destinos.get(u["id"], [])))
    return ubicaciones
