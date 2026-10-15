import secrets
import time

from flask import abort, redirect, request, url_for

from vighi.core import db
from vighi.core.sesion import puede
from vighi.dominio.estudios import REGISTRO, validar_combinacion
from vighi.servicios.catalogo import muestras_posibles, sitios_posibles
from vighi.servicios.consultas import etiqueta, listas, responsables
from vighi.servicios.lotes import asignar_lote, lotes_para_formulario, tipos_lote, validar_lote


CAMPOS_PROTOCOLO = ["fecha_recoleccion", "dni", "cobertura", "plan", "n_afiliado", "nombre", "apellido", "sexo", "exento",
                    "fecha_nacimiento", "email", "telefono", "medico", "lugar_recoleccion", "lugar_entrega", "observaciones"]
CAMPOS_ESTUDIO = ["categoria", "subcategoria", "sitio", "tipo_muestra", "cantidad", "citologia_hormonal", "observaciones",
                  "responsable_id", "tecnicas_especiales"]
CAMPOS_PACIENTE = ["apellido", "nombre", "fecha_nacimiento", "sexo", "cobertura", "plan", "n_afiliado", "exento", "email", "telefono"]


def dni_valido(dni):
    texto = (dni or "").strip().replace(".", "").replace(" ", "").replace("-", "")
    return bool(texto.strip("0"))


def sincronizar_paciente(pid, dni, campos=None):
    if not dni_valido(dni):
        return
    p = protocolo_o_404(pid)
    campos = [c for c in CAMPOS_PACIENTE if p[c]] if campos is None else [c for c in campos if c in CAMPOS_PACIENTE]
    if not campos:
        return
    db.ex(f"UPDATE protocolos SET {', '.join(c + '=?' for c in campos)} WHERE dni=? AND id<>?", [p[c] for c in campos] + [dni, pid])


def leer_protocolo():
    d = {k: request.form.get(k, "").strip() for k in CAMPOS_PROTOCOLO}
    d["numero"] = request.form.get("numero", "").strip()
    return d


def limpiar_valor(texto):
    return " ".join((texto or "").replace(",", " ").replace(";", " ").split())[:80]


def sin_repetidos(valores):
    vistos = {}
    for v in valores:
        if v:
            vistos.setdefault(v.lower(), v)
    return list(vistos.values())


def recordar_tecnicas(e):
    pedidas = [x for x in (e.get("tecnicas_especiales") or "").split("; ") if x]
    if not pedidas:
        return
    actuales = listas().get("tecnicas_especiales", [])
    conocidas = {x.lower() for x in actuales}
    nuevas = list(dict.fromkeys(x for x in pedidas if x.lower() not in conocidas))
    if nuevas:
        db.lote_ex([("INSERT INTO listas (nombre, orden, valor) VALUES (?,?,?)", ("tecnicas_especiales", len(actuales) + i, v)) for i, v in enumerate(nuevas)])


def leer_estudio(prefijo, tipo):
    t = REGISTRO[tipo]
    campo = lambda k: request.form.get(prefijo + k, "").strip()
    return {"tipo": tipo, "categoria": t.categoria,
            "subcategoria": t.subcategoria_fija or campo("subcategoria"),
            "sitio": t.sitio_fijo or campo("sitio"),
            "tipo_muestra": campo("tipo_muestra"),
            "cantidad": campo("cantidad") if campo("cantidad") in t.cantidades else None,
            "citologia_hormonal": campo("citologia_hormonal") if t.citologia_hormonal else None,
            "observaciones": campo("observaciones"),
            "responsable_id": int(campo("responsable_id")) if campo("responsable_id").isdigit() else None,
            "tecnicas_especiales": ("; ".join(sin_repetidos(limpiar_valor(x) for x in request.form.getlist(prefijo + "tecnicas_especiales"))) or None)
            if t.pide_tecnicas else None,
            "lote_sel": campo("lote_id"),
            "id": int(campo("id")) if campo("id").isdigit() else None}


def estudios_del_formulario():
    indices = sorted({int(k.split("-")[1]) for k in request.form
                      if k.startswith("e-") and k.endswith("-tipo") and k.split("-")[1].isdigit()})
    return [leer_estudio(f"e-{i}-", request.form[f"e-{i}-tipo"]) for i in indices
            if request.form.get(f"e-{i}-tipo") in REGISTRO]


def validar_estudios(lista, existentes=(), actual_id=None, con_lote=True):
    error = validar_combinacion(list(existentes) + lista)
    if error:
        return None, error
    if not (con_lote and lista):
        return None, None
    return validar_lote(lista[0]["lote_sel"], lista[0]["tipo"], actual_id)


def crear_estudio(protocolo_id, e, lote, usuario_id):
    eid = db.ex(f"INSERT INTO estudios (protocolo_id, tipo, creado_por, creado_en, {', '.join(CAMPOS_ESTUDIO)}) "
                f"VALUES (?,?,?,?,{','.join('?' * len(CAMPOS_ESTUDIO))})",
                [protocolo_id, e["tipo"], usuario_id, db.ahora()] + [e[k] for k in CAMPOS_ESTUDIO])
    recordar_tecnicas(e)
    db.auditar(usuario_id, protocolo_id, "nuevo_estudio", etiqueta(e), eid)
    asignar_lote(protocolo_id, lote, usuario_id)
    return eid


def contexto_formulario():
    return {"listas": listas(),
            "resp": {t: responsables(t) for t in REGISTRO},
            "lotes_abiertos": {t: lotes_para_formulario(t) for t in REGISTRO},
            "tipos_lote_de": {t: tipos_lote(t) for t in REGISTRO}}


SQL_PROTOCOLO = "SELECT p.*, u.iniciales AS creador FROM protocolos p LEFT JOIN usuarios u ON u.id=p.creado_por WHERE p.id=?"
SQL_HISTORIAL_PROTOCOLO = """SELECT a.*, u.iniciales FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id
                        WHERE protocolo_id=? ORDER BY a.id DESC"""


def protocolo_o_404(pid):
    p = db.uno(SQL_PROTOCOLO, (pid,))
    if not p:
        abort(404)
    return p


def completo(p, estudios):
    return bool(p["apellido"] and p["nombre"] and estudios and all(e["cantidad"] for e in estudios if not e["anulado"]))


def error_plan(d, anterior=None):
    plan = (d.get("plan") or "").strip()
    if "cobertura" not in d:
        cobertura = (anterior["cobertura"] if anterior is not None else "") or ""
    else:
        cobertura = d.get("cobertura") or ""
    if plan and plan not in db.planes_por_cobertura().get(cobertura, []):
        return f"El plan {plan} no corresponde a la cobertura {cobertura or '(sin cobertura)'}."
    return None


VIGENCIA_EDICION = 900


def edicion_vigente(pid):
    return db.uno("""SELECT e.usuario_id, e.token, e.desde, e.vence, u.nombre FROM ediciones e LEFT JOIN usuarios u ON u.id=e.usuario_id
                     WHERE e.protocolo_id=? AND e.vence>=?""", (pid, time.time()))


def ediciones_en_curso():
    return {r["protocolo_id"]: r for r in db.q("""SELECT e.protocolo_id, e.usuario_id, e.desde, u.nombre FROM ediciones e
                                                  LEFT JOIN usuarios u ON u.id=e.usuario_id WHERE e.vence>=?""", (time.time(),))}


def tomar_edicion(pid, usuario_id):
    token = secrets.token_hex(16)
    ahora_ = time.time()
    db.ex("DELETE FROM ediciones WHERE protocolo_id=? AND vence<?", (pid, ahora_))
    try:
        db.ex("INSERT INTO ediciones (protocolo_id, usuario_id, token, desde, vence) VALUES (?,?,?,?,?)",
              (pid, usuario_id, token, db.ahora(), ahora_ + VIGENCIA_EDICION))
    except db.IntegrityError:
        db.ex("UPDATE ediciones SET token=?, vence=? WHERE protocolo_id=? AND usuario_id=?", (token, ahora_ + VIGENCIA_EDICION, pid, usuario_id))
    fila = db.uno("SELECT token FROM ediciones WHERE protocolo_id=?", (pid,))
    if fila and fila["token"] == token:
        return token, None
    return None, edicion_vigente(pid)


def edicion_propia(pid, usuario_id, token):
    fila = db.uno("SELECT usuario_id, token FROM ediciones WHERE protocolo_id=?", (pid,))
    return bool(token and fila and fila["usuario_id"] == usuario_id and fila["token"] == token)


def soltar_edicion(pid, usuario_id=None, token=None):
    if token is None:
        db.ex("DELETE FROM ediciones WHERE protocolo_id=?", (pid,))
    else:
        db.ex("DELETE FROM ediciones WHERE protocolo_id=? AND usuario_id=? AND token=?", (pid, usuario_id, token))


CAMPOS_RAPIDOS = ["apellido", "nombre", "fecha_nacimiento", "cobertura", "plan", "medico", "lugar_recoleccion", "lugar_entrega", "fecha_recoleccion"]


def protocolos_del_paciente(base):
    if not dni_valido(base["dni"]):
        return [base]
    protocolos = db.q("SELECT p.*, u.iniciales AS creador FROM protocolos p LEFT JOIN usuarios u ON u.id=p.creado_por WHERE p.dni=? ORDER BY p.id DESC", (base["dni"],))
    return protocolos if any(x["id"] == base["id"] for x in protocolos) else [base]


SQL_COMENTARIOS = """SELECT c.*, u.iniciales, u.nombre AS autor FROM comentarios c LEFT JOIN usuarios u ON u.id=c.usuario_id
                     WHERE c.protocolo_id=? ORDER BY c.id DESC"""


def comentarios_de(pid):
    return db.q(SQL_COMENTARIOS, (pid,))


def volver_a_comentarios(pid):
    destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for("protocolos.protocolo", pid=pid)
    return redirect(destino.split("#")[0] + "#comentarios")


def opciones_de_edicion(estudios):
    vacio = {"muestras": {}, "sitios": {}, "responsables": {}, "lote": {}}
    activos = [x for x in estudios if not x["anulado"]]
    if not activos or not puede("protocolo_editar"):
        return vacio
    primero = min(activos, key=lambda x: x["id"])
    return {"muestras": {x["id"]: muestras_posibles(x) for x in activos},
            "sitios": {x["id"]: sitios_posibles(x) for x in activos},
            "responsables": {t: responsables(t) for t in {x["tipo"] for x in activos}},
            "lote": {"estudio": primero["id"], "abiertos": lotes_para_formulario(primero["tipo"], primero["lote_id"]), "nuevos": tipos_lote(primero["tipo"])}}
