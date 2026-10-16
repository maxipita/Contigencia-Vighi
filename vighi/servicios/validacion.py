from vighi.core import db
from vighi.servicios.protocolos import CAMPOS_PACIENTE, dni_valido, error_plan, protocolo_o_404, sincronizar_paciente

PACIENTE_PROVISORIO = ("IA", "EnProceso")
CAMPOS_ACTIVACION = ["fecha_recoleccion", "cobertura", "plan", "medico", "lugar_recoleccion", "lugar_entrega", "observaciones"]

SQL_PENDIENTES = """SELECT p.id, p.numero, p.medico, p.cobertura, p.fecha_recoleccion, p.creado_en,
                           (SELECT COUNT(*) FROM estudios e WHERE e.protocolo_id=p.id AND e.anulado=0) AS muestras,
                           (SELECT COUNT(*) FROM ordenes o WHERE o.protocolo_id=p.id) AS ordenes,
                           (SELECT l.codigo FROM estudios e JOIN lotes l ON l.id=e.lote_id WHERE e.protocolo_id=p.id AND e.anulado=0 ORDER BY e.id LIMIT 1) AS lote
                    FROM protocolos p WHERE p.pendiente_validacion=1 AND p.borrador=0 ORDER BY p.id"""


def es_provisorio(p):
    return (p["apellido"], p["nombre"]) == PACIENTE_PROVISORIO


def solo_pap(estudios):
    activos = [e for e in estudios if not e["anulado"]]
    return bool(activos) and all(e["tipo"] == "PAP" for e in activos)


def pendientes():
    return db.q(SQL_PENDIENTES)


def siguiente(pid):
    ids = [r["id"] for r in pendientes() if r["id"] != pid]
    return next((i for i in ids if i > pid), ids[0] if ids else None)


def faltantes_activacion(d, estudios):
    activos = [e for e in estudios if not e["anulado"]]
    falta = []
    if not d.get("medico"):
        falta.append("el médico")
    if not d.get("cobertura"):
        falta.append("la cobertura")
    if not activos or not all(e["cantidad"] for e in activos):
        falta.append("la cantidad de cada muestra")
    return falta


def activar(pid, yo):
    p = protocolo_o_404(pid)
    cambios = {"borrador": 0, "pendiente_validacion": 1}
    if not (p["apellido"] or "").strip():
        cambios["apellido"] = PACIENTE_PROVISORIO[0]
    if not (p["nombre"] or "").strip():
        cambios["nombre"] = PACIENTE_PROVISORIO[1]
    db.ex(f"UPDATE protocolos SET {', '.join(k + '=?' for k in cambios)} WHERE id=?", list(cambios.values()) + [pid])
    db.auditar(yo["id"], pid, "completar", p["numero"])
    db.auditar(yo["id"], pid, "activar_pap", "pendiente de validación")


def leer_formulario(form):
    return {k: form.get(k, "").strip() for k in ["dni"] + CAMPOS_PACIENTE}


def error_validacion(d, p):
    if not d["apellido"] or not d["nombre"]:
        return "Completá el apellido y el nombre del paciente."
    if (d["apellido"], d["nombre"]) == PACIENTE_PROVISORIO:
        return "Reemplazá el nombre provisorio por el del paciente."
    return error_plan(d)


def guardar(pid, d, yo):
    p = protocolo_o_404(pid)
    columnas = list(d)
    db.ex(f"UPDATE protocolos SET {', '.join(c + '=?' for c in columnas)}, pendiente_validacion=0, validado_por=?, validado_en=? WHERE id=?",
          [d[c] for c in columnas] + [yo["id"], db.ahora(), pid])
    db.auditar(yo["id"], pid, "validar", ", ".join(c for c in columnas if d[c] != (p[c] or "")))
    if dni_valido(d["dni"]):
        sincronizar_paciente(pid, d["dni"], None)
