import io
import json
import os
import re
import secrets
import socket
import sys
import unicodedata
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import d1
import db
import permisos
import trazabilidad
from estudios import NOMBRE_ETAPA, PASOS_IHQ, REGISTRO, SECTORES, TIPOS, validar_combinacion

try:
    import informes
except ImportError as _err:
    informes = None
    print(f"AVISO: los informes en PDF están desactivados ({_err}). Instalar con: {sys.executable} -m pip install -r requirements.txt")
SEMAFOROS = {"on_time": "On time", "delayed": "Delayed", "late": "Late"}
SIN_INFORMES = "Los informes en PDF no están disponibles: falta instalar reportlab (python -m pip install -r requirements.txt) y reiniciar el sistema."

PUERTO = int(os.environ.get("CONTINGENCIA_PUERTO", "8000"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


def _clave_secreta():
    ruta = os.path.join(db.DATA, "secret.key")
    os.makedirs(db.DATA, exist_ok=True)
    if not os.path.exists(ruta):
        with open(ruta, "w") as f:
            f.write(secrets.token_hex(32))
    with open(ruta) as f:
        return f.read().strip()


app.secret_key = _clave_secreta()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
app.teardown_appcontext(db.cerrar)


@app.errorhandler(d1.ErrorConexion)
def sin_base(error):
    return ("<!doctype html><meta charset='utf-8'><title>Sin conexión</title>"
            "<body style='font-family:sans-serif;max-width:560px;margin:15vh auto;padding:0 20px'>"
            "<h1>Sin conexión con la base de datos</h1>"
            "<p>No se pudo comunicar con Cloudflare D1. Revisá la conexión a internet y volvé a intentar en unos segundos.</p>"
            f"<p style='color:#666;font-size:13px'>{str(error)[:200]}</p></body>"), 503


SQL_USUARIO = """SELECT u.*, p.nombre AS perfil, p.permisos AS perfil_permisos FROM usuarios u
                      LEFT JOIN perfiles p ON p.id=u.perfil_id WHERE u.id=? AND u.activo=1"""
SQL_BORRADORES = "SELECT COUNT(*) AS n FROM protocolos WHERE borrador=1"


@app.before_request
def adelantar_lecturas():
    if session.get("uid") and request.endpoint != "static":
        db.precargar([(SQL_USUARIO, (session["uid"],)), (SQL_BORRADORES, ())])


def usuario_actual():
    uid = session.get("uid")
    if not uid:
        return None
    if g.get("yo_id") != uid:
        f = db.uno(SQL_USUARIO, (uid,))
        g.yo = {**dict(f), "permisos": permisos.efectivos(f, f["perfil_permisos"])} if f else None
        g.yo_id = uid
    return g.yo


def puede(permiso):
    u = usuario_actual()
    return bool(u and permiso in u["permisos"])


def requiere_login(f):
    @wraps(f)
    def envuelta(*a, **k):
        u = usuario_actual()
        if not u:
            return redirect(url_for("login", next=request.path))
        if u["debe_cambiar_clave"] and request.endpoint not in ("cambiar_clave", "logout"):
            return redirect(url_for("cambiar_clave"))
        return f(*a, **k)
    return envuelta


def requiere_permiso(*claves):
    def decorador(f):
        @wraps(f)
        @requiere_login
        def envuelta(*a, **k):
            if not any(puede(c) for c in claves):
                flash("No tenés permiso para esa acción. Pedíselo a un administrador.", "error")
                destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else None
                return redirect(destino or url_for("tablero"))
            return f(*a, **k)
        return envuelta
    return decorador


def requiere_admin(f):
    @wraps(f)
    @requiere_login
    def envuelta(*a, **k):
        if not usuario_actual()["admin"]:
            abort(403)
        return f(*a, **k)
    return envuelta


@app.before_request
def verificar_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST":
        token = request.form.get("_csrf") or request.headers.get("X-CSRF")
        if token != session["csrf"]:
            abort(400, "Formulario vencido: recargá la página e intentá de nuevo.")


@app.context_processor
def globales():
    u = usuario_actual()
    pendientes = db.uno(SQL_BORRADORES)["n"] if u else 0
    return {"yo": u, "csrf": session.get("csrf", ""), "TIPOS": TIPOS, "SECTORES": SECTORES, "REGISTRO": REGISTRO,
            "n_borradores": pendientes, "informes_ok": informes is not None, "SEMAFOROS": SEMAFOROS, "nombre_base": db.nombre_base(),
            "NOMBRE_ETAPA": NOMBRE_ETAPA, "puede": puede, "mis_sectores": set((u["sectores"] or "").split(",")) if u else set()}


@app.template_filter("fh")
def fecha_hora(v):
    if not v:
        return ""
    try:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return v


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


@app.template_filter("larga")
def fecha_larga(d):
    return f"{d.day} {MESES[d.month - 1]} {d.year}" if d else ""


@app.template_filter("dh")
def fecha_hora_dt(d):
    return d.strftime("%d/%m/%Y %H:%M hs") if d else ""


@app.template_filter("f")
def fecha(v):
    if not v:
        return ""
    try:
        return datetime.strptime(v, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return v


def es_local():
    return request.remote_addr in ("127.0.0.1", "::1")


@app.route("/configurar", methods=["GET", "POST"])
def configurar():
    if db.uno("SELECT 1 FROM usuarios WHERE admin=1 AND clave_hash IS NOT NULL"):
        return redirect(url_for("login"))
    if not es_local():
        abort(403, "La configuración inicial solo se hace desde la PC servidor.")
    if request.method == "POST":
        ini = request.form["iniciales"].strip().upper()
        clave = request.form["clave"]
        if len(clave) < 8 or clave != request.form["clave2"]:
            flash("La clave debe tener al menos 8 caracteres y coincidir en los dos campos.", "error")
        elif not ini:
            flash("Faltan las iniciales.", "error")
        else:
            existente = db.uno("SELECT id FROM usuarios WHERE iniciales=?", (ini,))
            h = generate_password_hash(clave)
            if existente:
                db.ex("UPDATE usuarios SET admin=1, activo=1, clave_hash=?, debe_cambiar_clave=0, nombre=? WHERE id=?",
                      (h, request.form["nombre"].strip() or ini, existente["id"]))
            else:
                db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, clave_hash, debe_cambiar_clave) "
                      "VALUES (?,?,?,1,?,0)", (ini, request.form["nombre"].strip() or ini, ",".join(SECTORES), h))
            flash("Administrador creado. Ya podés ingresar.", "ok")
            return redirect(url_for("login"))
    return render_template("configurar.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not db.uno("SELECT 1 FROM usuarios WHERE admin=1 AND clave_hash IS NOT NULL"):
        return redirect(url_for("configurar"))
    if request.method == "POST":
        u = db.uno("SELECT * FROM usuarios WHERE iniciales=? AND activo=1", (request.form["iniciales"].strip().upper(),))
        if u and u["clave_hash"] and check_password_hash(u["clave_hash"], request.form["clave"]):
            session.clear()
            session["uid"] = u["id"]
            db.auditar(u["id"], None, "login")
            destino = request.args.get("next", "")
            return redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("tablero"))
        flash("Iniciales o clave incorrectas (o el usuario todavía no tiene clave: pedísela al administrador).", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/clave", methods=["GET", "POST"])
@requiere_login
def cambiar_clave():
    yo = usuario_actual()
    if request.method == "POST":
        nueva = request.form["nueva"]
        if not check_password_hash(yo["clave_hash"], request.form["actual"]):
            flash("La clave actual no es correcta.", "error")
        elif len(nueva) < 8 or nueva != request.form["nueva2"]:
            flash("La nueva clave debe tener al menos 8 caracteres y coincidir en los dos campos.", "error")
        else:
            db.ex("UPDATE usuarios SET clave_hash=?, debe_cambiar_clave=0 WHERE id=?", (generate_password_hash(nueva), yo["id"]))
            db.auditar(yo["id"], None, "cambio_clave")
            flash("Clave actualizada.", "ok")
            return redirect(url_for("tablero"))
    return render_template("clave.html")


def listas():
    out = {}
    for r in db.q(SQL_LISTAS):
        out.setdefault(r["nombre"], []).append(r["valor"])
    return out


def responsables(tipo):
    sector = REGISTRO[tipo].sector_responsable
    return [u for u in db.q("SELECT id, iniciales, nombre, sectores FROM usuarios WHERE activo=1 ORDER BY iniciales")
            if sector in (u["sectores"] or "").split(",")]


SQL_ETAPAS = "SELECT estudio_id, etapa, fecha_hora FROM etapas"
SQL_CON_IHQ = "SELECT e.protocolo_id, e.tipo FROM micro m JOIN estudios e ON e.id=m.estudio_id WHERE m.solicita_ihq=1 AND e.anulado=0"
SQL_TIPOS = "SELECT e.protocolo_id, e.tipo FROM estudios e WHERE e.anulado=0"


def consultas_estudios(where="1=1", params=(), borradores=False):
    principal = f"""SELECT e.*, p.numero, p.apellido, p.nombre, p.dni, p.fecha_recoleccion, p.cargado_sistema, p.borrador,
                            u.iniciales AS responsable, l.codigo AS lote, t.tacos AS tacos_muestra,
                            (SELECT COUNT(*) FROM estudios x WHERE x.protocolo_id=e.protocolo_id AND x.anulado=0) AS hermanos,
                            (SELECT COUNT(*) FROM comentarios c WHERE c.protocolo_id=e.protocolo_id) AS n_comentarios
                     FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                     LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                     LEFT JOIN tacos_organo t ON t.organo=e.sitio AND t.tipo_lote=l.tipo_lote
                     WHERE {where}{'' if borradores else ' AND p.borrador=0'} ORDER BY p.id DESC, e.id"""
    return [(principal, tuple(params)), (SQL_ETAPAS, ()), (SQL_CON_IHQ, ()), (SQL_TIPOS, ())]


def tacos_del_estudio(e):
    if e["tipo"] != "BP" or e["tacos_muestra"] is None:
        return None
    frascos = int(e["cantidad"]) if (e["cantidad"] or "").isdigit() else 1
    return frascos * e["tacos_muestra"]


def sql_tacos(campo):
    return f"""SELECT e.{campo} AS clave,
                      SUM((CASE WHEN e.cantidad GLOB '[0-9]*' THEN CAST(e.cantidad AS INTEGER) ELSE 1 END) * COALESCE(t.tacos, 0)) AS tacos,
                      SUM(CASE WHEN t.tacos IS NULL THEN 1 ELSE 0 END) AS sin_dato
               FROM estudios e LEFT JOIN lotes l ON l.id=e.lote_id LEFT JOIN tacos_organo t ON t.organo=e.sitio AND t.tipo_lote=l.tipo_lote
               WHERE e.tipo='BP' AND e.anulado=0 AND e.{campo} IS NOT NULL{{filtro}} GROUP BY e.{campo}"""


def tacos_por(campo, valor=None):
    filas = db.q(sql_tacos(campo).format(filtro="" if valor is None else f" AND e.{campo}=?"), () if valor is None else (valor,))
    return {f["clave"]: (f["tacos"] or 0, f["sin_dato"] or 0) for f in filas}


def tacos_de_lote(lote_id):
    return tacos_por("lote_id", lote_id).get(lote_id, (0, 0))


def tacos_de_protocolo(protocolo_id):
    return tacos_por("protocolo_id", protocolo_id).get(protocolo_id, (0, 0))


def ubicar_en_lote(protocolo_id, usuario_id):
    capacidad = REGISTRO["BP"].tacos_por_lote
    with db.bloqueo("lotes"):
        actual = lote_del_protocolo(protocolo_id)
        if not actual or actual["cerrado"] or actual["tipo_lote"] not in REGISTRO["BP"].lotes:
            return None
        propios = tacos_de_protocolo(protocolo_id)[0]
        ocupados = tacos_de_lote(actual["id"])[0] - propios
        if not propios or not ocupados or ocupados + propios <= capacidad:
            return None
        destino = next((l for l in db.q("SELECT * FROM lotes WHERE tipo_lote=? AND fecha=? AND cerrado=0 AND id<>? ORDER BY numero",
                                        (actual["tipo_lote"], hoy(), actual["id"])) if tacos_de_lote(l["id"])[0] + propios <= capacidad), None)
        destino = destino or crear_lote(actual["tipo_lote"], usuario_id)
        asignar_lote(protocolo_id, destino, usuario_id)
        db.auditar(usuario_id, protocolo_id, "lote_lleno", f"{actual['codigo']} llegó a {ocupados}/{capacidad} tacos: pasó a {destino['codigo']}")
        return {"desde": actual["codigo"], "hacia": destino["codigo"], "ocupados": ocupados, "capacidad": capacidad}


def avisar_lote_lleno(resultado):
    if resultado:
        flash(f"El lote {resultado['desde']} se llenó ({resultado['ocupados']}/{resultado['capacidad']} tacos): el protocolo pasó al lote {resultado['hacia']}.", "ok")


def cargar_estudios(where="1=1", params=(), borradores=False):
    consultas = consultas_estudios(where, params, borradores)
    db.precargar(consultas)
    filas = db.q(*consultas[0])
    hechas, fechas = {}, {}
    for r in db.q(SQL_ETAPAS):
        hechas.setdefault(r["estudio_id"], set()).add(r["etapa"])
        fechas.setdefault(r["estudio_id"], {})[r["etapa"]] = r["fecha_hora"]
    con_ihq = {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_CON_IHQ)}
    out, fer, ahora_ = [], db.feriados(), datetime.now()
    flujos = flujos_de() if filas else {}
    for f in filas:
        d = dict(f)
        d["flujos"] = flujos.get(f["protocolo_id"], "")
        tipo = REGISTRO[f["tipo"]]
        d["solicita_ihq"] = (f["protocolo_id"], f["tipo"]) in con_ihq
        d["estado"], prox = tipo.estado(hechas.get(f["id"], set()), d["solicita_ihq"], bool(f["anulado"]))
        if f["borrador"]:
            d["estado"] = "A completar"
        d["proxima"] = prox
        d["vence"] = trazabilidad.limite(f["tipo"], prox[0], f["fecha_recoleccion"] or f["creado_en"], fer) if prox else None
        d["semaforo"] = (trazabilidad.semaforo_acumulado(f["tipo"], f["fecha_recoleccion"] or f["creado_en"], {"ingreso": f["creado_en"], **fechas.get(f["id"], {})},
                                                         d["vence"], ahora_, fer) if d["vence"] and not f["borrador"] else "")
        d["etiqueta"] = etiqueta(f)
        d["tacos"] = tacos_del_estudio(f)
        out.append(d)
    return out


def etiqueta(e):
    if e["tipo"] == "PAP" or not e["sitio"]:
        return TIPOS[e["tipo"]]
    return f"{TIPOS[e['tipo']]} · {e['sitio']}"


def etiqueta_flujos(tipos, con_ihq):
    t = [k for k in ("BP", "CT", "PAP") if k in tipos]
    if not t:
        return ""
    return t[0] + (" c/ " + " y ".join(t[1:]) if len(t) > 1 else "") + (" + IHQ" if con_ihq else "")


def flujos_de(protocolo_ids=None):
    tipos = {}
    for r in db.q(SQL_TIPOS):
        tipos.setdefault(r["protocolo_id"], set()).add(r["tipo"])
    ihq = {r["protocolo_id"] for r in db.q(SQL_CON_IHQ)}
    todos = {pid: etiqueta_flujos(ts, pid in ihq) for pid, ts in tipos.items()}
    return todos if not protocolo_ids else {pid: todos[pid] for pid in protocolo_ids if pid in todos}


def miembros_flujo(e):
    return db.q("SELECT * FROM estudios WHERE protocolo_id=? AND tipo=? AND anulado=0 ORDER BY id", (e["protocolo_id"], e["tipo"]))


def pide_ihq(protocolo_id, tipo):
    return bool(db.uno(SQL_PIDE_IHQ, (protocolo_id, tipo)))


def flujo_avanzado(protocolo_id, tipo):
    r = db.uno("""SELECT x.etapa FROM etapas x JOIN estudios e ON e.id=x.estudio_id
                  WHERE e.protocolo_id=? AND e.tipo=? AND e.anulado=0 ORDER BY x.fecha_hora DESC, x.id DESC LIMIT 1""", (protocolo_id, tipo))
    return NOMBRE_ETAPA.get(r["etapa"], r["etapa"]) if r else None


def protocolo_cerrado(pid):
    activos = [x for x in cargar_estudios("e.protocolo_id=?", (pid,), borradores=True) if not x["anulado"]]
    return bool(activos) and not any(x["borrador"] or x["proxima"] for x in activos)


def tipos_lote_fijos():
    fijos = listas().get("tipo_lote", [])
    return fijos + [t for e in REGISTRO.values() for t in e.lotes if t not in fijos]


@app.route("/")
@requiere_login
def tablero():
    yo = usuario_actual()
    f = {k: request.args.get(k, "") for k in ("q", "tipo", "ver", "sector", "etapa", "semaforo")}
    f["ver"] = f["ver"] or "pendientes"
    todos = cargar_estudios()
    conteo = {"pendientes": 0, "informados": 0, "sin_cargar": 0}
    for e in todos:
        if e["anulado"]:
            continue
        if e["proxima"]:
            conteo["pendientes"] += 1
        else:
            conteo["informados"] += 1
            if not e["cargado_sistema"]:
                conteo["sin_cargar"] += 1
    mis = set((yo["sectores"] or "").split(","))

    def pasa(e):
        if f["tipo"] and e["tipo"] != f["tipo"]:
            return False
        if f["ver"] == "pendientes" and (e["anulado"] or not e["proxima"]):
            return False
        if f["ver"] == "mios" and (e["anulado"] or not e["proxima"] or e["proxima"][2] not in mis):
            return False
        if f["ver"] == "informados" and (e["anulado"] or e["proxima"]):
            return False
        if f["ver"] == "sin_cargar" and (e["anulado"] or e["proxima"] or e["cargado_sistema"]):
            return False
        if f["ver"] == "anulados" and not e["anulado"]:
            return False
        if f["sector"] and not (e["proxima"] and e["proxima"][2] == f["sector"]):
            return False
        if f["etapa"] and not (e["proxima"] and e["proxima"][0] == f["etapa"]):
            return False
        if f["q"]:
            texto = " ".join(str(e[k] or "") for k in ("numero", "apellido", "nombre", "dni", "lote", "sitio")).lower()
            return f["q"].lower() in texto
        return True

    visibles = [e for e in todos if pasa(e)]
    por_semaforo = {k: sum(1 for e in visibles if e["semaforo"] == k) for k in SEMAFOROS}
    if f["semaforo"]:
        visibles = [e for e in visibles if e["semaforo"] == f["semaforo"]]
    return render_template("tablero.html", estudios=visibles, f=f, conteo=conteo, por_semaforo=por_semaforo,
                           etapas=[(k, n) for k, n in NOMBRE_ETAPA.items() if k != "ingreso"])


def tipos_lote(tipo=None):
    fijos = tipos_lote_fijos()
    cito = [u["iniciales"] for u in responsables("PAP")]
    if tipo:
        return REGISTRO[tipo].tipos_lote(fijos, cito)
    return fijos + [i for i in cito if i not in fijos]


def hoy():
    return datetime.now().strftime("%Y-%m-%d")


def crear_lote(tipo_lote, usuario_id):
    f = hoy()
    for _ in range(5):
        n = (db.uno("SELECT MAX(numero) AS m FROM lotes WHERE tipo_lote=? AND fecha=?", (tipo_lote, f))["m"] or 0) + 1
        codigo = f"{tipo_lote}-{f[5:7]}{f[8:10]}.{n}"
        try:
            lid = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_por, creado_en) VALUES (?,?,?,?,?,?)",
                        (codigo, tipo_lote, f, n, usuario_id, db.ahora()))
            break
        except db.IntegrityError:
            continue
    else:
        raise RuntimeError("No se pudo crear el lote, probá de nuevo.")
    db.auditar(usuario_id, None, "nuevo_lote", codigo)
    return db.uno("SELECT * FROM lotes WHERE id=?", (lid,))


def validar_lote(seleccion, tipo, actual_id=None):
    if not seleccion:
        return None, None
    if seleccion.startswith("nuevo:"):
        if seleccion[6:] not in tipos_lote(tipo):
            return None, f"Tipo de lote inválido para {TIPOS[tipo]}."
        return seleccion, None
    lote = db.uno("SELECT * FROM lotes WHERE id=?", (int(seleccion),)) if seleccion.isdigit() else None
    if not lote:
        return None, "El lote elegido no existe."
    if lote["id"] != actual_id:
        if lote["cerrado"]:
            return None, f"El lote {lote['codigo']} está cerrado."
        if lote["tipo_lote"] not in tipos_lote(tipo):
            return None, f"El lote {lote['codigo']} no corresponde a {TIPOS[tipo]}."
    return lote, None


def concretar_lote(valor, usuario_id):
    if isinstance(valor, str):
        return crear_lote(valor[6:], usuario_id)
    return valor


def lotes_para_formulario(tipo, actual_id=None):
    validos = tipos_lote(tipo)
    lotes = [l for l in db.q("SELECT * FROM lotes WHERE fecha=? AND cerrado=0 ORDER BY tipo_lote, numero", (hoy(),))
             if l["tipo_lote"] in validos]
    if actual_id and actual_id not in [l["id"] for l in lotes]:
        actual = db.uno("SELECT * FROM lotes WHERE id=?", (actual_id,))
        if actual:
            lotes.insert(0, actual)
    return lotes


def primer_estudio(protocolo_id):
    return db.uno("SELECT * FROM estudios WHERE protocolo_id=? AND anulado=0 ORDER BY id LIMIT 1", (protocolo_id,))


def lote_del_protocolo(protocolo_id):
    primero = primer_estudio(protocolo_id)
    return db.uno("SELECT * FROM lotes WHERE id=?", (primero["lote_id"],)) if primero and primero["lote_id"] else None


def asignar_lote(protocolo_id, lote, usuario_id):
    anterior = lote_del_protocolo(protocolo_id)
    db.ex("UPDATE estudios SET lote_id=? WHERE protocolo_id=? AND anulado=0", (lote["id"] if lote else None, protocolo_id))
    antes, despues = (anterior["codigo"] if anterior else None), (lote["codigo"] if lote else None)
    if antes != despues:
        db.auditar(usuario_id, protocolo_id, "lote", f"{antes or '—'} → {despues or '—'}")


CAMPOS_PROTOCOLO = ["fecha_recoleccion", "dni", "cobertura", "n_afiliado", "nombre", "apellido", "sexo", "exento",
                    "fecha_nacimiento", "email", "telefono", "medico", "lugar_recoleccion", "lugar_entrega", "observaciones"]
CAMPOS_ESTUDIO = ["categoria", "subcategoria", "sitio", "tipo_muestra", "cantidad", "citologia_hormonal", "observaciones",
                  "responsable_id"]


def leer_protocolo():
    d = {k: request.form.get(k, "").strip() for k in CAMPOS_PROTOCOLO}
    d["numero"] = request.form.get("numero", "").strip()
    return d


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


@app.route("/protocolo/nuevo", methods=["GET", "POST"])
@requiere_permiso("protocolo_crear")
def protocolo_nuevo():
    yo = usuario_actual()
    p, lista = {}, []
    if request.method == "POST":
        p, lista = leer_protocolo(), estudios_del_formulario()
        lote_valor, error = validar_estudios(lista)
        if not p["numero"]:
            error = "Falta el N° de protocolo."
        elif (dup := db.uno("SELECT id, borrador FROM protocolos WHERE numero=?", (p["numero"],))) and dup["borrador"]:
            flash(f"El protocolo {p['numero']} ya fue generado desde Recepción y falta completarlo: cargá los datos acá.", "ok")
            return redirect(url_for("protocolo_editar", pid=dup["id"]))
        elif dup:
            error = f"El protocolo {p['numero']} ya existe: para sumarle un estudio usá «+ Agregar estudio» en su ficha."
        elif not lista:
            error = "Agregá al menos un estudio (PAP, Biopsia o Citología)."
        if error:
            flash(error, "error")
        else:
            cols = ["numero"] + CAMPOS_PROTOCOLO
            pid = db.ex(f"INSERT INTO protocolos (creado_por, creado_en, {', '.join(cols)}) VALUES (?,?,{','.join('?' * len(cols))})",
                        [yo["id"], db.ahora()] + [p[c] for c in cols])
            db.auditar(yo["id"], pid, "ingreso", p["numero"])
            lote = concretar_lote(lote_valor, yo["id"])
            for e in lista:
                crear_estudio(pid, e, lote, yo["id"])
            avisar_lote_lleno(ubicar_en_lote(pid, yo["id"]))
            flash(f"Protocolo {p['numero']} ingresado con {len(lista)} estudio(s).", "ok")
            if not numero_emitido(p["numero"]):
                flash(f"Atención: {p['numero']} no figura en ningún lote de etiquetas confirmado (menú Etiquetas).", "error")
            return redirect(url_for("protocolo", pid=pid))
    elif request.args.get("tipo") in REGISTRO:
        lista = [{"tipo": request.args["tipo"]}]
    ultimos = [r["numero"] for r in db.q("SELECT numero FROM protocolos ORDER BY id DESC LIMIT 5")]
    return render_template("protocolo_form.html", p=p, estudios=lista, nuevo=True, ultimos=ultimos, **contexto_formulario())


def completo(p, estudios):
    return bool(p["apellido"] and p["nombre"] and estudios and all(e["cantidad"] for e in estudios if not e["anulado"]))


@app.route("/protocolo/<int:pid>/editar", methods=["GET", "POST"])
@requiere_permiso("protocolo_crear", "protocolo_editar")
def protocolo_editar(pid):
    yo = usuario_actual()
    p = protocolo_o_404(pid)
    borrador = bool(p["borrador"])
    if not borrador and not puede("protocolo_editar"):
        flash("No tenés permiso para editar protocolos. Pedíselo a un administrador.", "error")
        return redirect(url_for("protocolo", pid=pid))
    actuales = {e["id"]: e for e in db.q("SELECT * FROM estudios WHERE protocolo_id=? ORDER BY id", (pid,))}
    lista = [{**dict(e), "lote_sel": str(e["lote_id"] or "")} for e in actuales.values() if not e["anulado"]] if borrador else []
    if request.method == "POST":
        d = leer_protocolo()
        error = None
        if borrador:
            lista = [e for e in estudios_del_formulario() if e["id"] is None or e["id"] in actuales]
            error = validar_combinacion(lista) if lista else "El protocolo tiene que tener al menos un estudio."
            lote_valor = None
            if not error:
                actual = lote_del_protocolo(pid)
                lote_valor, error = validar_lote(lista[0]["lote_sel"], lista[0]["tipo"], actual["id"] if actual else None)
        if not d["numero"]:
            error = "Falta el N° de protocolo."
        elif db.uno("SELECT 1 FROM protocolos WHERE numero=? AND id<>?", (d["numero"], pid)):
            error = f"Ya existe otro protocolo {d['numero']}."
        if error:
            flash(error, "error")
        else:
            cols = ["numero"] + CAMPOS_PROTOCOLO
            db.ex(f"UPDATE protocolos SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [d[c] for c in cols] + [pid])
            db.auditar(yo["id"], pid, "editar_protocolo")
            if not borrador:
                flash("Datos del protocolo actualizados.", "ok")
                return redirect(url_for("protocolo", pid=pid))
            lote = concretar_lote(lote_valor, yo["id"])
            for e in lista:
                if e["id"]:
                    db.ex(f"UPDATE estudios SET {', '.join(k + '=?' for k in CAMPOS_ESTUDIO)} WHERE id=?",
                          [e[k] for k in CAMPOS_ESTUDIO] + [e["id"]])
                else:
                    crear_estudio(pid, e, lote, yo["id"])
            asignar_lote(pid, lote, yo["id"])
            quitados = [k for k, e in actuales.items() if k not in {x["id"] for x in lista} and not e["anulado"]]
            for k in quitados:
                db.ex("UPDATE estudios SET anulado=1, motivo_anulacion=? WHERE id=?", ("Quitado al completar el protocolo", k))
                db.auditar(yo["id"], pid, "anular", "Quitado al completar el protocolo", k)
            if completo(d, [dict(x) for x in db.q("SELECT cantidad, anulado FROM estudios WHERE protocolo_id=?", (pid,))]):
                db.ex("UPDATE protocolos SET borrador=0 WHERE id=?", (pid,))
                db.auditar(yo["id"], pid, "completar", d["numero"])
                avisar_lote_lleno(ubicar_en_lote(pid, yo["id"]))
                flash(f"Protocolo {d['numero']} completo.", "ok")
                return redirect(url_for("protocolo", pid=pid))
            flash("Datos guardados. Para completar el protocolo faltan apellido, nombre y la cantidad de cada estudio.", "ok")
            return redirect(url_for("protocolo_editar", pid=pid))
        p = {**dict(p), **d}
    ctx = contexto_formulario()
    for e in actuales.values():
        if e["lote_id"] and all(l["id"] != e["lote_id"] for l in ctx["lotes_abiertos"][e["tipo"]]):
            ctx["lotes_abiertos"][e["tipo"]].insert(0, db.uno("SELECT * FROM lotes WHERE id=?", (e["lote_id"],)))
    return render_template("protocolo_form.html", p=p, estudios=lista, nuevo=False, completar=borrador, ultimos=[], **ctx)


SQL_COMENTARIOS = """SELECT c.*, u.iniciales, u.nombre AS autor FROM comentarios c LEFT JOIN usuarios u ON u.id=c.usuario_id
                     WHERE c.protocolo_id=? ORDER BY c.id DESC"""


def comentarios_de(pid):
    return db.q(SQL_COMENTARIOS, (pid,))


def volver_a_comentarios(pid):
    destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for("protocolo", pid=pid)
    return redirect(destino.split("#")[0] + "#comentarios")


@app.route("/protocolo/<int:pid>")
@requiere_login
def protocolo(pid):
    db.precargar([(SQL_PROTOCOLO, (pid,)), (SQL_HISTORIAL_PROTOCOLO, (pid,)), (SQL_INFORME_EMITIDO, (pid,)),
                   (SQL_COMENTARIOS, (pid,))] + consultas_estudios("e.protocolo_id=?", (pid,), True))
    p = protocolo_o_404(pid)
    historial = db.q(SQL_HISTORIAL_PROTOCOLO, (pid,))
    estudios = cargar_estudios("e.protocolo_id=?", (pid,), borradores=True)
    pendientes = []
    for x in estudios:
        if not x["anulado"] and x["proxima"] and (x["tipo"], x["proxima"][1]) not in [(q[0], q[1]) for q in pendientes]:
            pendientes.append((x["tipo"], x["proxima"][1], TIPOS[x["tipo"]]))
    return render_template("protocolo.html", p=p, estudios=estudios, historial=historial, comentarios=comentarios_de(pid),
                           emitido=informe_emitido(pid),
                           flujos=flujos_de([pid]).get(pid, ""),
                           informe_listo=bool(estudios) and not p["borrador"] and not pendientes and any(not x["anulado"] for x in estudios),
                           pendientes=pendientes, informe_vigente=informe_vigente(pid, informe_emitido(pid)))


@app.route("/protocolo/<int:pid>/comentario", methods=["POST"])
@requiere_login
def comentario_nuevo(pid):
    protocolo_o_404(pid)
    texto = request.form.get("texto", "").strip()
    if not texto:
        flash("Escribí el comentario.", "error")
    elif len(texto) > 2000:
        flash("El comentario es demasiado largo (máximo 2000 caracteres).", "error")
    else:
        db.ex("INSERT INTO comentarios (protocolo_id, usuario_id, fecha_hora, texto) VALUES (?,?,?,?)",
              (pid, usuario_actual()["id"], db.ahora(), texto))
        db.auditar(usuario_actual()["id"], pid, "comentario", texto[:60] + ("…" if len(texto) > 60 else ""))
        flash("Comentario agregado.", "ok")
    return volver_a_comentarios(pid)


@app.route("/comentario/<int:cid>/borrar", methods=["POST"])
@requiere_login
def comentario_borrar(cid):
    yo = usuario_actual()
    c = db.uno("SELECT * FROM comentarios WHERE id=?", (cid,)) or abort(404)
    if c["usuario_id"] != yo["id"] and not yo["admin"]:
        flash("Solo podés borrar tus propios comentarios.", "error")
    else:
        db.ex("DELETE FROM comentarios WHERE id=?", (cid,))
        db.auditar(yo["id"], c["protocolo_id"], "comentario_borrado", c["texto"][:60] + ("…" if len(c["texto"]) > 60 else ""))
        flash("Comentario borrado.", "ok")
    return volver_a_comentarios(c["protocolo_id"])


@app.route("/protocolo/<int:pid>/estudio/nuevo", methods=["GET", "POST"])
@requiere_permiso("protocolo_editar")
def estudio_nuevo(pid):
    yo = usuario_actual()
    p = protocolo_o_404(pid)
    existentes = [dict(e) for e in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=?", (pid,))]
    lista = [{"tipo": request.args["tipo"]}] if request.args.get("tipo") in REGISTRO else []
    if request.method == "POST":
        lista = estudios_del_formulario()
        lote_del_prot = lote_del_protocolo(pid)
        lote_valor, error = validar_estudios(lista, existentes, con_lote=not primer_estudio(pid))
        if not lista:
            error = "Elegí qué estudio agregar."
        for e in lista:
            if not error and (avance := flujo_avanzado(pid, e["tipo"])):
                error = (f"Ya hay {REGISTRO[e['tipo']].nombre.lower()} de este protocolo en proceso (llegó a {avance}) y comparten el mismo flujo: "
                         "para sumar otra hay que deshacer las etapas antes.")
        if error:
            flash(error, "error")
        else:
            lote = lote_del_prot if primer_estudio(pid) else concretar_lote(lote_valor, yo["id"])
            for e in lista:
                crear_estudio(pid, e, lote, yo["id"])
            avisar_lote_lleno(ubicar_en_lote(pid, yo["id"]))
            flash(f"Se agregó {', '.join(etiqueta(e) for e in lista)} al protocolo {p['numero']}.", "ok")
            return redirect(url_for("protocolo", pid=pid))
    lote_fijo = lote_del_protocolo(pid)
    return render_template("estudio_form.html", p=p, estudios=lista, editando=None, lote_editable=not primer_estudio(pid),
                           lote_fijo=lote_fijo["codigo"] if lote_fijo else None, **contexto_formulario())


@app.route("/estudio/<int:eid>/editar", methods=["GET", "POST"])
@requiere_permiso("protocolo_editar")
def estudio_editar(eid):
    yo = usuario_actual()
    actual = db.uno("SELECT * FROM estudios WHERE id=?", (eid,)) or abort(404)
    p = protocolo_o_404(actual["protocolo_id"])
    e = dict(actual)
    primero = primer_estudio(p["id"])
    es_primero = bool(primero and primero["id"] == eid)
    if request.method == "POST":
        e = {**leer_estudio("e-0-", actual["tipo"]), "id": eid}
        otros = [dict(x) for x in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=? AND id<>?",
                                       (p["id"], eid))]
        lote_valor, error = validar_estudios([{**e, "anulado": actual["anulado"]}], otros, actual["lote_id"], con_lote=es_primero)
        if error:
            flash(error, "error")
        else:
            db.ex(f"UPDATE estudios SET {', '.join(k + '=?' for k in CAMPOS_ESTUDIO)} WHERE id=?",
                  [e[k] for k in CAMPOS_ESTUDIO] + [eid])
            db.auditar(yo["id"], p["id"], "editar_estudio", etiqueta(e), eid)
            if es_primero:
                asignar_lote(p["id"], concretar_lote(lote_valor, yo["id"]), yo["id"])
            avisar_lote_lleno(ubicar_en_lote(p["id"], yo["id"]))
            flash("Datos del estudio actualizados.", "ok")
            return redirect(url_for("estudio", eid=eid))
    else:
        e["lote_sel"] = str(actual["lote_id"] or "")
    ctx = contexto_formulario()
    ctx["lotes_abiertos"][actual["tipo"]] = lotes_para_formulario(actual["tipo"], actual["lote_id"])
    lote_fijo = lote_del_protocolo(p["id"])
    return render_template("estudio_form.html", p=p, estudios=[e], editando=eid, lote_editable=es_primero,
                           lote_fijo=lote_fijo["codigo"] if lote_fijo else None, **ctx)


SQL_FICHA = """SELECT e.*, p.numero, p.borrador, p.fecha_recoleccion, p.apellido, p.nombre, p.dni, p.medico, p.cobertura,
                         u.iniciales AS responsable, u2.iniciales AS creador, l.codigo AS lote
                  FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                  LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN usuarios u2 ON u2.id=e.creado_por
                  LEFT JOIN lotes l ON l.id=e.lote_id WHERE e.id=?"""
SQL_ETAPAS_FICHA = """SELECT x.*, u.iniciales, u.nombre FROM etapas x
                                            JOIN usuarios u ON u.id=x.usuario_id WHERE estudio_id=?"""
SQL_ULTIMA_ETAPA = "SELECT * FROM etapas WHERE estudio_id=? ORDER BY fecha_hora DESC, id DESC LIMIT 1"
SQL_HISTORIAL_ESTUDIO = """SELECT a.*, u.iniciales FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id
                        WHERE estudio_id=? ORDER BY a.id DESC"""
SQL_TEMPLATES = "SELECT id, titulo FROM templates WHERE clase=? ORDER BY titulo"
SQL_LISTAS = "SELECT nombre, valor FROM listas ORDER BY nombre, orden"
SQL_PIDE_IHQ = ("SELECT 1 FROM micro m JOIN estudios e ON e.id=m.estudio_id "
                "WHERE e.protocolo_id=? AND e.tipo=? AND e.anulado=0 AND m.solicita_ihq=1")


def consultas_ficha(eid):
    return [(SQL_FICHA, (eid,)), ("SELECT * FROM macro WHERE estudio_id=?", (eid,)), ("SELECT * FROM micro WHERE estudio_id=?", (eid,)),
            ("SELECT * FROM ihq WHERE estudio_id=?", (eid,)), (SQL_ETAPAS_FICHA, (eid,))]


def ficha(eid):
    db.precargar(consultas_ficha(eid))
    e = db.uno(SQL_FICHA, (eid,))
    if not e:
        abort(404)
    macro = db.uno("SELECT * FROM macro WHERE estudio_id=?", (eid,))
    micro = db.uno("SELECT * FROM micro WHERE estudio_id=?", (eid,))
    ihq = db.uno("SELECT * FROM ihq WHERE estudio_id=?", (eid,))
    etapas = {x["etapa"]: x for x in db.q(SQL_ETAPAS_FICHA, (eid,))}
    solicita = bool(micro and micro["solicita_ihq"]) if e["anulado"] else pide_ihq(e["protocolo_id"], e["tipo"])
    return e, macro, micro, ihq, etapas, solicita


def con_permiso(permiso, estado):
    return estado if puede(permiso) or not estado[0] else (False, "No tenés permiso para cargar esta sección.")


def habilitada(e, etapas, solicita, etapa):
    if e["anulado"]:
        return False, "El estudio está anulado."
    _, prox = REGISTRO[e["tipo"]].estado(set(etapas), solicita)
    if prox and prox[0] == etapa:
        return True, ""
    if etapa in etapas:
        x = etapas[etapa]
        return False, (f"{NOMBRE_ETAPA[etapa]} ya fue completada por {x['iniciales']} el {fecha_hora(x['fecha_hora'])}. "
                       "Para corregirla hay que deshacer las etapas hasta esa.")
    return False, (f"Se habilita cuando el estudio llegue a {NOMBRE_ETAPA[etapa]}"
                   + (f" (ahora está en {prox[1]})." if prox else "."))


@app.route("/estudio/<int:eid>")
@requiere_login
def estudio(eid):
    db.precargar(consultas_ficha(eid) + [(SQL_ULTIMA_ETAPA, (eid,)), (SQL_HISTORIAL_ESTUDIO, (eid,)), (SQL_TEMPLATES, ("macro",)),
                                         (SQL_TEMPLATES, ("micro",)), (SQL_LISTAS, ()), ("SELECT fecha FROM feriados", ())])
    primero = db.uno(SQL_FICHA, (eid,))
    if primero:
        db.precargar([(SQL_PIDE_IHQ, (primero["protocolo_id"], primero["tipo"])), (SQL_COMENTARIOS, (primero["protocolo_id"],))] + consultas_estudios("e.protocolo_id=?", (primero["protocolo_id"],), True))
    e, macro, micro, ihq, etapas, solicita = ficha(eid)
    tipo = REGISTRO[e["tipo"]]
    est, prox = tipo.estado(set(etapas), solicita, bool(e["anulado"]))
    ultima = db.uno(SQL_ULTIMA_ETAPA, (eid,))
    historial = db.q(SQL_HISTORIAL_ESTUDIO, (eid,))
    tpl = lambda clase: db.q(SQL_TEMPLATES, (clase,))
    pasos = tipo.flujo(solicita)
    traza_enc, traza = trazabilidad.calcular(e, pasos, etapas, db.feriados())
    hermanos = cargar_estudios("e.protocolo_id=?", (e["protocolo_id"],), borradores=True)
    activos = [h for h in hermanos if not h["anulado"]]
    comparte = [h for h in activos if h["tipo"] == e["tipo"] and h["id"] != e["id"]]
    limite_etapa = trazabilidad.limite(e["tipo"], prox[0], e["fecha_recoleccion"] or e["creado_en"], db.feriados()) if prox and not e["anulado"] and not e["borrador"] else None
    semaforo = (trazabilidad.semaforo_acumulado(e["tipo"], e["fecha_recoleccion"] or e["creado_en"],
                                                {"ingreso": e["creado_en"], **{k: v["fecha_hora"] for k, v in etapas.items()}}, limite_etapa, datetime.now(), db.feriados())
                if limite_etapa else "")
    cierra_protocolo = bool(prox and not e["anulado"] and prox[0] == tipo.ultima_etapa(solicita)
                            and all(not h["proxima"] and not h["borrador"] for h in activos if h["tipo"] != e["tipo"]))
    return render_template("estudio.html", e=e, comparte=comparte, comentarios=comentarios_de(e["protocolo_id"]), cierra_protocolo=cierra_protocolo, semaforo=semaforo,
                           flujos=flujos_de([e["protocolo_id"]]).get(e["protocolo_id"], ""), tipo=tipo, macro=macro, micro=micro, ihq=ihq, etapas=etapas, estado=est,
                           prox=prox, ultima=ultima, historial=historial, traza=traza, traza_enc=traza_enc,
                           hermanos=hermanos, etiqueta=etiqueta(e),
                           tpl_macro=tpl("macro"), tpl_micro=tpl("micro"), bethesda=listas().get("bethesda", []),
                           ihq_hecha=any(k in etapas for k in PASOS_IHQ),
                           edita_macro=con_permiso("macro", habilitada(e, etapas, solicita, "macroscopia")),
                           edita_micro=con_permiso("micro", habilitada(e, etapas, solicita, "microscopia")))


def guardar_seccion(tabla, eid, valores):
    if db.uno(f"SELECT 1 FROM {tabla} WHERE estudio_id=?", (eid,)):
        db.ex(f"UPDATE {tabla} SET {', '.join(k + '=?' for k in valores)} WHERE estudio_id=?", list(valores.values()) + [eid])
    else:
        db.ex(f"INSERT INTO {tabla} (estudio_id, {', '.join(valores)}) VALUES (?,{','.join('?' * len(valores))})",
              [eid] + list(valores.values()))


@app.route("/estudio/<int:eid>/macro", methods=["POST"])
@requiere_permiso("macro")
def guardar_macro(eid):
    e, _, _, _, etapas, solicita = ficha(eid)
    ok, motivo = habilitada(e, etapas, solicita, "macroscopia")
    if "macro" not in REGISTRO[e["tipo"]].secciones or not ok:
        flash(f"No se guardó: {motivo or 'este estudio no tiene macroscopía.'}", "error")
        return redirect(url_for("estudio", eid=eid) + "#macro")
    cas = request.form.get("cassettes", "")
    guardar_seccion("macro", eid, {"template": request.form.get("template", "").strip(),
                                   "descripcion": request.form.get("descripcion", "").strip(),
                                   "cassettes": int(cas) if cas.isdigit() else None})
    db.auditar(usuario_actual()["id"], e["protocolo_id"], "guardar_macro", "", eid)
    flash("Macroscopía guardada.", "ok")
    if request.form.get("y_listo"):
        return marcar_listo(eid, "macroscopia")
    return redirect(url_for("estudio", eid=eid) + "#macro")


@app.route("/estudio/<int:eid>/micro", methods=["POST"])
@requiere_permiso("micro")
def guardar_micro(eid):
    e, _, micro, _, etapas, solicita = ficha(eid)
    ok, motivo = habilitada(e, etapas, solicita, "microscopia")
    if not ok:
        flash(f"No se guardó: {motivo}", "error")
        return redirect(url_for("estudio", eid=eid) + "#micro")
    con_ihq = "ihq" in REGISTRO[e["tipo"]].secciones
    pide_ihq = 1 if con_ihq and request.form.get("solicita_ihq") == "1" else 0
    guardar_seccion("micro", eid, {"template": request.form.get("template", "").strip(),
                                   "descripcion": request.form.get("descripcion", "").strip(),
                                   "conclusion": request.form.get("conclusion", "").strip(),
                                   "bethesda": request.form.get("bethesda", "").strip(),
                                   "tecnicas_especiales": request.form.get("tecnicas_especiales", "").strip(),
                                   "solicita_ihq": pide_ihq})
    db.auditar(usuario_actual()["id"], e["protocolo_id"], "guardar_micro", "solicita IHQ" if pide_ihq else "", eid)
    flash("Microscopía guardada.", "ok")
    if request.form.get("y_listo"):
        return marcar_listo(eid, "microscopia")
    return redirect(url_for("estudio", eid=eid) + "#micro")


@app.route("/estudio/<int:eid>/ihq", methods=["POST"])
@requiere_permiso("micro")
def guardar_ihq(eid):
    e = ficha(eid)[0]
    guardar_seccion("ihq", eid, {"marcadores": request.form.get("marcadores", "").strip(),
                                 "resultado": request.form.get("resultado", "").strip()})
    db.auditar(usuario_actual()["id"], e["protocolo_id"], "guardar_ihq", "", eid)
    flash("IHQ guardada.", "ok")
    if request.form.get("y_listo"):
        return marcar_listo(eid, "interp_ihq")
    return redirect(url_for("estudio", eid=eid) + "#ihq")


@app.route("/estudio/<int:eid>/listo/<etapa>", methods=["POST"])
@requiere_permiso("etapas")
def marcar_listo(eid, etapa):
    yo = usuario_actual()
    e, macro, micro, ihq, etapas, solicita = ficha(eid)
    if e["borrador"]:
        flash("Primero completá los datos del paciente de este protocolo.", "error")
        return redirect(url_for("protocolo_editar", pid=e["protocolo_id"]))
    tipo = REGISTRO[e["tipo"]]
    _, prox = tipo.estado(set(etapas), solicita, bool(e["anulado"]))
    miembros = miembros_flujo(e)
    falta = None
    for m in miembros:
        if etapa in PASOS_IHQ and not db.uno("SELECT 1 FROM micro WHERE estudio_id=? AND solicita_ihq=1", (m["id"],)):
            continue
        problema = tipo.requisito(etapa, db.uno("SELECT * FROM macro WHERE estudio_id=?", (m["id"],)),
                                  db.uno("SELECT * FROM micro WHERE estudio_id=?", (m["id"],)), db.uno("SELECT * FROM ihq WHERE estudio_id=?", (m["id"],)))
        if problema:
            falta = f"{etiqueta(m)}: {problema}" if len(miembros) > 1 else problema
            break
    if not prox or prox[0] != etapa:
        flash("Esa etapa no es la próxima pendiente de este estudio.", "error")
    elif not yo["admin"] and prox[2] not in (yo["sectores"] or "").split(","):
        flash(f"La etapa {prox[1]} la marca el sector {SECTORES[prox[2]]}.", "error")
    elif falta:
        flash(falta, "error")
    else:
        ahora_ = db.ahora()
        for m in miembros:
            if not db.uno("SELECT 1 FROM etapas WHERE estudio_id=? AND etapa=?", (m["id"], etapa)):
                db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (m["id"], etapa, yo["id"], ahora_))
        db.auditar(yo["id"], e["protocolo_id"], "listo", NOMBRE_ETAPA[etapa] + (f" (en {len(miembros)} estudios {tipo.nombre.lower()})" if len(miembros) > 1 else ""), eid)
        flash(f"✔ {NOMBRE_ETAPA[etapa]} registrada por {yo['iniciales']}"
              + (f" en los {len(miembros)} estudios de {tipo.nombre.lower()} del protocolo." if len(miembros) > 1 else "."), "ok")
        if request.form.get("firmar_yo") == "1" and protocolo_cerrado(e["protocolo_id"]):
            db.ex("UPDATE protocolos SET firmante_id=? WHERE id=?", (yo["id"], e["protocolo_id"]))
            db.auditar(yo["id"], e["protocolo_id"], "firmante", f"{yo['iniciales']} firmará el informe", eid)
            flash("Vas a figurar como firmante del informe.", "ok")
    return redirect(request.form.get("volver") or url_for("estudio", eid=eid))


SQL_INFORME_EMITIDO = """SELECT i.id, i.version, i.creado_en, i.comentario, i.estudios, u.iniciales, u.nombre AS generado_por, f.nombre AS firmante
                     FROM informes_emitidos i LEFT JOIN usuarios u ON u.id=i.usuario_id LEFT JOIN usuarios f ON f.id=i.firmante_id
                     WHERE i.protocolo_id=?"""


def informe_emitido(pid):
    return db.uno(SQL_INFORME_EMITIDO, (pid,))


def informe_vigente(pid, emitido):
    if not emitido or not protocolo_cerrado(pid):
        return False
    if not emitido["estudios"]:
        return True
    activos = {str(x["id"]) for x in cargar_estudios("e.protocolo_id=?", (pid,), borradores=True) if not x["anulado"]}
    return set(emitido["estudios"].split(",")) == activos


@app.route("/estudio/<int:eid>/informe")
@requiere_permiso("informe")
def informe_de_estudio(eid):
    return redirect(url_for("informe", pid=ficha(eid)[0]["protocolo_id"]))


@app.route("/protocolo/<int:pid>/informe")
@requiere_permiso("informe")
def informe(pid):
    p = protocolo_o_404(pid)
    if informes is None:
        flash(SIN_INFORMES, "error")
        return redirect(url_for("protocolo", pid=pid))
    try:
        d = informes.armar(pid)
    except informes.InformeError as err:
        flash(str(err), "error")
        return redirect(url_for("protocolo", pid=pid))
    emitido = informe_emitido(pid)
    return render_template("informe.html", d=d, p=p, emitido=emitido, informe_vigente=informe_vigente(pid, emitido))


@app.route("/protocolo/<int:pid>/informe.pdf", methods=["POST"])
@requiere_permiso("informe")
def informe_pdf(pid):
    protocolo_o_404(pid)
    if informes is None:
        flash(SIN_INFORMES, "error")
        return redirect(url_for("protocolo", pid=pid))
    yo = usuario_actual()
    try:
        d = informes.armar(pid, request.form.get("comentario", ""))
    except informes.InformeError as err:
        flash(str(err), "error")
        return redirect(url_for("protocolo", pid=pid))
    pdf = informes.generar_pdf(d)
    previo = db.uno("SELECT i.id, i.version, i.creado_en, u.iniciales FROM informes_emitidos i LEFT JOIN usuarios u ON u.id=i.usuario_id WHERE i.protocolo_id=?", (pid,))
    campos = (yo["id"], d["medico"]["id"], db.ahora(), d["comentario"], informes.nombre_archivo(d), pdf, ",".join(str(s["eid"]) for s in d["estudios"]))
    try:
        if previo:
            db.ex("UPDATE informes_emitidos SET usuario_id=?, firmante_id=?, creado_en=?, comentario=?, archivo=?, pdf=?, estudios=?, version=version+1 WHERE id=?",
                  campos + (previo["id"],))
            iid, version = previo["id"], previo["version"] + 1
        else:
            iid, version = db.ex("INSERT INTO informes_emitidos (usuario_id, firmante_id, creado_en, comentario, archivo, pdf, estudios, protocolo_id, version) "
                                 "VALUES (?,?,?,?,?,?,?,?,1)", campos + (pid,)), 1
    except db.IntegrityError:
        flash("Alguien más generó el informe al mismo tiempo, revisalo y generalo de nuevo si hace falta.", "error")
        return redirect(url_for("informe", pid=pid))
    reemplaza = f" · reemplaza el de {previo['iniciales'] or '—'} del {fecha_hora(previo['creado_en'])}" if previo else ""
    db.auditar(yo["id"], pid, "informe_pdf",
               f"{d['titulo'].title()} generado por {yo['iniciales']} · firma de {d['medico']['nombre']}" + (f" (emisión {version}{reemplaza})" if previo else ""))
    return redirect(url_for("informe_ver", iid=iid))


@app.route("/informe/<int:iid>.pdf")
@requiere_permiso("informe")
def informe_ver(iid):
    r = db.uno("SELECT protocolo_id, estudios, archivo, pdf FROM informes_emitidos WHERE id=?", (iid,))
    if not r:
        abort(404)
    if not informe_vigente(r["protocolo_id"], r):
        flash("Ese informe ya no se puede entregar: el protocolo tiene estudios pendientes o cambió desde que se generó. Hay que generarlo de nuevo.", "error")
        return redirect(url_for("protocolo", pid=r["protocolo_id"]))
    return send_file(io.BytesIO(bytes(r["pdf"])), mimetype="application/pdf", download_name=r["archivo"], max_age=0)


@app.route("/usuarios/<int:uid>/firma")
@requiere_admin
def usuario_firma(uid):
    f = db.uno("SELECT imagen FROM firmas WHERE usuario_id=?", (uid,))
    if not f:
        abort(404)
    return send_file(io.BytesIO(bytes(f["imagen"])), mimetype="image/png", max_age=0)


@app.route("/estudio/<int:eid>/deshacer", methods=["POST"])
@requiere_permiso("etapas")
def deshacer(eid):
    yo = usuario_actual()
    e = ficha(eid)[0]
    ultima = db.uno("SELECT * FROM etapas WHERE estudio_id=? ORDER BY fecha_hora DESC, id DESC LIMIT 1", (eid,))
    if not ultima:
        flash("No hay etapas para deshacer.", "error")
    elif ultima["usuario_id"] != yo["id"] and not puede("etapas_deshacer"):
        flash("Solo quien la registró o alguien con permiso puede deshacer la etapa.", "error")
    else:
        miembros = miembros_flujo(e)
        for m in miembros or [e]:
            db.ex("DELETE FROM etapas WHERE estudio_id=? AND etapa=?", (m["id"], ultima["etapa"]))
        db.ex("UPDATE protocolos SET firmante_id=NULL WHERE id=?", (e["protocolo_id"],))
        db.auditar(yo["id"], e["protocolo_id"], "deshacer", NOMBRE_ETAPA.get(ultima["etapa"], ultima["etapa"]), eid)
        flash(f"Se deshizo {NOMBRE_ETAPA.get(ultima['etapa'])}.", "ok")
    return redirect(url_for("estudio", eid=eid))


@app.route("/estudio/<int:eid>/anular", methods=["POST"])
@requiere_permiso("estudio_anular")
def anular(eid):
    e = ficha(eid)[0]
    motivo = request.form.get("motivo", "").strip()
    nuevo = 0 if e["anulado"] else 1
    otros = [dict(x) for x in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=? AND id<>?",
                                   (e["protocolo_id"], eid))]
    if nuevo and not motivo:
        flash("Indicá el motivo de la anulación.", "error")
    elif not nuevo and (error := validar_combinacion(otros + [{"tipo": e["tipo"], "subcategoria": e["subcategoria"]}])):
        flash(f"No se puede reactivar: {error}", "error")
    elif not nuevo and (avance := flujo_avanzado(e["protocolo_id"], e["tipo"])):
        flash(f"No se puede reactivar: hay {REGISTRO[e['tipo']].nombre.lower()} de este protocolo en proceso (llegó a {avance}) y comparten el mismo "
              "flujo. Primero hay que deshacer las etapas.", "error")
    else:
        db.ex("UPDATE estudios SET anulado=?, motivo_anulacion=? WHERE id=?", (nuevo, motivo if nuevo else None, eid))
        db.auditar(usuario_actual()["id"], e["protocolo_id"], "anular" if nuevo else "reactivar", motivo, eid)
        flash("Estudio anulado." if nuevo else "Estudio reactivado.", "ok")
        if not nuevo:
            avisar_lote_lleno(ubicar_en_lote(e["protocolo_id"], usuario_actual()["id"]))
    return redirect(url_for("estudio", eid=eid))


@app.route("/protocolo/<int:pid>/sistema", methods=["POST"])
@requiere_permiso("sistema")
def cargado_sistema(pid):
    protocolo_o_404(pid)
    cargado = 1 if request.form.get("cargado_sistema") == "1" else 0
    db.ex("UPDATE protocolos SET protocolo_sistema=?, cargado_sistema=? WHERE id=?",
          (request.form.get("protocolo_sistema", "").strip(), cargado, pid))
    db.auditar(usuario_actual()["id"], pid, "sistema", "cargado" if cargado else "no cargado")
    flash("Datos de carga en el sistema actualizados.", "ok")
    return redirect(url_for("protocolo", pid=pid))


@app.route("/lotes")
@requiere_login
def lotes():
    fecha_sel = request.args.get("fecha") or hoy()
    filas = db.q("""SELECT l.*, u.iniciales AS creador, COUNT(e.id) AS cantidad
                    FROM lotes l LEFT JOIN usuarios u ON u.id=l.creado_por
                    LEFT JOIN estudios e ON e.lote_id=l.id AND e.anulado=0
                    WHERE l.fecha=? GROUP BY l.id ORDER BY l.cerrado, l.tipo_lote, l.numero""", (fecha_sel,))
    dias = db.q("SELECT fecha, COUNT(*) AS n FROM lotes GROUP BY fecha ORDER BY fecha DESC LIMIT 15")
    return render_template("lotes.html", lotes=filas, fecha_sel=fecha_sel, es_hoy=fecha_sel == hoy(), dias=dias,
                           tacos=tacos_por("lote_id"), lotes_bp=REGISTRO["BP"].lotes, capacidad=REGISTRO["BP"].tacos_por_lote,
                           grupos_lote=[("Biopsias", tipos_lote("BP")), ("Citologías", tipos_lote("CT")),
                                        ("PAP · citotécnico", tipos_lote("PAP"))])


@app.route("/lotes/nuevo", methods=["POST"])
@requiere_permiso("lotes_armar")
def nuevo_lote():
    tipo_lote = request.form.get("tipo_lote", "")
    if tipo_lote not in tipos_lote():
        flash("Elegí el tipo de lote.", "error")
        return redirect(url_for("lotes"))
    lote = crear_lote(tipo_lote, usuario_actual()["id"])
    flash(f"Lote {lote['codigo']} creado.", "ok")
    return redirect(url_for("lote", lote_id=lote["id"]))


def lote_o_404(lote_id):
    l = db.uno("""SELECT l.*, u.iniciales AS creador, u2.iniciales AS cerrador FROM lotes l
                  LEFT JOIN usuarios u ON u.id=l.creado_por LEFT JOIN usuarios u2 ON u2.id=l.cerrado_por
                  WHERE l.id=?""", (lote_id,))
    if not l:
        abort(404)
    return l


def orden_numero(numero):
    m = re.fullmatch(r"(\D*)(\d+)(.*)", numero or "")
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (numero or "", 0, "")


@app.route("/lotes/<int:lote_id>")
@requiere_login
def lote(lote_id):
    l = lote_o_404(lote_id)
    del_lote = cargar_estudios("e.lote_id=?", (lote_id,), borradores=True)
    del_lote.sort(key=lambda x: (orden_numero(x["numero"]), x["id"]))
    primeros = {r["id"] for r in db.q("SELECT MIN(id) AS id FROM estudios WHERE anulado=0 GROUP BY protocolo_id")}
    sin_lote = [x for x in cargar_estudios("e.lote_id IS NULL AND e.anulado=0")
                if x["id"] in primeros and l["tipo_lote"] in tipos_lote(x["tipo"])][:300]
    en_bp = l["tipo_lote"] in REGISTRO["BP"].lotes
    tacos_total, sin_dato = tacos_de_lote(lote_id) if en_bp else (0, 0)
    return render_template("lote.html", l=l, estudios=del_lote, sin_lote=sin_lote, capacidad=REGISTRO["BP"].tacos_por_lote if en_bp else None,
                           tacos_total=tacos_total, sin_dato=sin_dato,
                           etiquetas_lab=(l["tipo_lote"] in tipos_lote("BP") or l["tipo_lote"] in tipos_lote("PAP"))
                           and any(not x["anulado"] and not x["borrador"] for x in del_lote))


@app.route("/lotes/<int:lote_id>/agregar", methods=["POST"])
@requiere_permiso("lotes_armar")
def lote_agregar(lote_id):
    yo = usuario_actual()
    l = lote_o_404(lote_id)
    elegido = request.form.get("estudio_id", "")
    numero = request.form.get("protocolo", "").strip()
    if elegido.isdigit():
        p = db.uno("SELECT p.* FROM protocolos p JOIN estudios e ON e.protocolo_id=p.id WHERE e.id=?", (int(elegido),))
    else:
        p = db.uno("SELECT * FROM protocolos WHERE numero=?", (numero,)) if numero else None
    primero = primer_estudio(p["id"]) if p else None
    if l["cerrado"]:
        flash("El lote está cerrado.", "error")
    elif not elegido and not numero:
        flash("Elegí un protocolo de la lista o escribí su N°.", "error")
    elif not p:
        flash(f"No existe el protocolo {numero}. Primero hay que ingresarlo.", "error")
    elif not primero:
        flash(f"El protocolo {p['numero']} no tiene estudios activos.", "error")
    elif l["tipo_lote"] not in tipos_lote(primero["tipo"]):
        flash(f"El protocolo {p['numero']} empieza con {etiqueta(primero)} y el lote lo marca su primer flujo: no va en un lote {l['tipo_lote']}.", "error")
    elif primero["lote_id"] == lote_id:
        flash(f"{p['numero']} ya está en este lote.", "error")
    else:
        previo = lote_del_protocolo(p["id"])
        asignar_lote(p["id"], l, yo["id"])
        flash(f"{p['numero']} agregado al lote" + (f" (estaba en {previo['codigo']})." if previo else "."), "ok")
        capacidad = REGISTRO["BP"].tacos_por_lote
        total = tacos_de_lote(lote_id)[0] if l["tipo_lote"] in REGISTRO["BP"].lotes else 0
        if total > capacidad:
            flash(f"Atención: el lote {l['codigo']} queda en {total}/{capacidad} tacos.", "error")
    return redirect(url_for("lote", lote_id=lote_id))


@app.route("/lotes/<int:lote_id>/quitar/<int:eid>", methods=["POST"])
@requiere_permiso("lotes_armar")
def lote_quitar(lote_id, eid):
    l = lote_o_404(lote_id)
    e = db.uno("SELECT protocolo_id FROM estudios WHERE id=? AND lote_id=?", (eid, lote_id))
    if l["cerrado"]:
        flash("El lote está cerrado.", "error")
    elif e:
        asignar_lote(e["protocolo_id"], None, usuario_actual()["id"])
        flash("Protocolo quitado del lote.", "ok")
    return redirect(url_for("lote", lote_id=lote_id))


@app.route("/lotes/<int:lote_id>/cerrar", methods=["POST"])
@requiere_permiso("lotes_cerrar")
def lote_cerrar(lote_id):
    yo = usuario_actual()
    l = lote_o_404(lote_id)
    if l["cerrado"]:
        db.ex("UPDATE lotes SET cerrado=0, cerrado_por=NULL, cerrado_en=NULL WHERE id=?", (lote_id,))
        db.auditar(yo["id"], None, "reabrir_lote", l["codigo"])
        flash(f"Lote {l['codigo']} reabierto.", "ok")
    else:
        db.ex("UPDATE lotes SET cerrado=1, cerrado_por=?, cerrado_en=? WHERE id=?", (yo["id"], db.ahora(), lote_id))
        db.auditar(yo["id"], None, "cerrar_lote", l["codigo"])
        flash(f"Lote {l['codigo']} cerrado.", "ok")
    return redirect(url_for("lote", lote_id=lote_id))


@app.route("/lotes/<int:lote_id>/observaciones", methods=["POST"])
@requiere_permiso("lotes_armar")
def lote_observaciones(lote_id):
    lote_o_404(lote_id)
    db.ex("UPDATE lotes SET observaciones=? WHERE id=?", (request.form.get("observaciones", "").strip(), lote_id))
    flash("Observaciones guardadas.", "ok")
    return redirect(url_for("lote", lote_id=lote_id))


@app.route("/lotes/<int:lote_id>/eliminar", methods=["POST"])
@requiere_permiso("lotes_cerrar")
def lote_eliminar(lote_id):
    l = lote_o_404(lote_id)
    if db.uno("SELECT 1 FROM estudios WHERE lote_id=?", (lote_id,)):
        flash("Solo se puede eliminar un lote vacío.", "error")
        return redirect(url_for("lote", lote_id=lote_id))
    db.ex("DELETE FROM lotes WHERE id=?", (lote_id,))
    db.auditar(usuario_actual()["id"], None, "eliminar_lote", l["codigo"])
    flash(f"Lote {l['codigo']} eliminado.", "ok")
    return redirect(url_for("lotes", fecha=l["fecha"]))


@app.route("/api/catalogo/<tipo>")
@requiere_login
def api_catalogo(tipo):
    arbol = {}
    for r in db.q("SELECT subcategoria, sitio, tipo_muestra FROM catalogo WHERE tipo=?", (tipo,)):
        arbol.setdefault(r["subcategoria"], {}).setdefault(r["sitio"], []).append(r["tipo_muestra"])
    return jsonify(arbol)


@app.route("/api/template/<int:tid>")
@requiere_login
def api_template(tid):
    t = db.uno("SELECT titulo, texto, conclusion FROM templates WHERE id=?", (tid,))
    return jsonify(dict(t)) if t else (jsonify({}), 404)


@app.route("/api/medicos")
@requiere_login
def api_medicos():
    r = jsonify([m["nombre"] for m in db.q("SELECT nombre FROM medicos ORDER BY nombre")])
    r.headers["Cache-Control"] = "private, max-age=3600"
    return r


@app.route("/usuarios")
@requiere_admin
def usuarios():
    filas = db.q("""SELECT u.*, p.nombre AS perfil FROM usuarios u LEFT JOIN perfiles p ON p.id=u.perfil_id
                    ORDER BY u.activo DESC, u.iniciales""")
    return render_template("usuarios.html", usuarios=filas)


@app.route("/usuarios/nuevo", methods=["GET", "POST"])
@app.route("/usuarios/<int:uid>", methods=["GET", "POST"])
@requiere_admin
def usuario(uid=None):
    yo = usuario_actual()
    u = db.uno("SELECT * FROM usuarios WHERE id=?", (uid,)) if uid else None
    if request.method == "POST":
        ini = request.form["iniciales"].strip().upper()
        sectores = ",".join(s for s in SECTORES if request.form.get("s_" + s))
        perfil_id = int(request.form["perfil_id"]) if request.form.get("perfil_id", "").isdigit() else None
        ajuste = {k: request.form.get("p_" + k, "") for k in permisos.PERMISOS}
        titulo = request.form.get("titulo", "") if request.form.get("titulo") in ("Dr.", "Dra.") else ""
        mn, mp = request.form.get("mn", "").strip()[:20], request.form.get("mp", "").strip()[:20]
        firma_png, firma_error = None, None
        archivo = request.files.get("firma")
        if archivo and archivo.filename and informes is None:
            firma_error = SIN_INFORMES
        elif archivo and archivo.filename:
            try:
                firma_png = informes.procesar_firma(archivo.read())
            except ValueError as err:
                firma_error = str(err)
        vals = (ini, request.form.get("nombre", "").strip() or ini, sectores,
                1 if request.form.get("admin") else 0, 1 if request.form.get("activo") else 0, perfil_id,
                permisos.texto({k for k, v in ajuste.items() if v == "mas"}),
                permisos.texto({k for k, v in ajuste.items() if v == "menos"}))
        dup = db.uno("SELECT id FROM usuarios WHERE iniciales=? AND id<>?", (ini, uid or 0))
        clave = request.form.get("clave", "")
        if not ini or dup:
            flash("Iniciales vacías o ya usadas por otra persona.", "error")
        elif clave and len(clave) < 8:
            flash("La clave temporal debe tener al menos 8 caracteres.", "error")
        elif perfil_id and not db.uno("SELECT 1 FROM perfiles WHERE id=?", (perfil_id,)):
            flash("El perfil elegido no existe.", "error")
        elif uid == yo["id"] and not (vals[3] and vals[4]):
            flash("No podés quitarte el rol de administrador ni desactivarte a vos mismo.", "error")
        elif firma_error:
            flash(f"Firma: {firma_error}", "error")
        else:
            if u:
                db.ex("UPDATE usuarios SET iniciales=?, nombre=?, sectores=?, admin=?, activo=?, perfil_id=?, permisos_mas=?, "
                      "permisos_menos=? WHERE id=?", vals + (uid,))
            else:
                uid = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, perfil_id, permisos_mas, "
                            "permisos_menos) VALUES (?,?,?,?,?,?,?,?)", vals)
            if clave:
                db.ex("UPDATE usuarios SET clave_hash=?, debe_cambiar_clave=1 WHERE id=?", (generate_password_hash(clave), uid))
            db.ex("UPDATE usuarios SET titulo=?, mn=?, mp=? WHERE id=?", (titulo, mn, mp, uid))
            if firma_png:
                db.ex("DELETE FROM firmas WHERE usuario_id=?", (uid,))
                db.ex("INSERT INTO firmas (usuario_id, imagen, actualizada_en) VALUES (?,?,?)", (uid, firma_png, db.ahora()))
                db.auditar(yo["id"], None, "firma", f"{ini}: firma cargada")
            elif request.form.get("quitar_firma"):
                db.ex("DELETE FROM firmas WHERE usuario_id=?", (uid,))
                db.auditar(yo["id"], None, "firma", f"{ini}: firma quitada")
            detalle = (f"perfil {db.uno('SELECT nombre FROM perfiles WHERE id=?', (perfil_id,))['nombre'] if perfil_id else '—'}"
                       + (f", +{vals[6]}" if vals[6] else "") + (f", -{vals[7]}" if vals[7] else ""))
            db.auditar(yo["id"], None, "usuario", f"{ini}: {detalle}{' (clave temporal)' if clave else ''}")
            flash(f"Usuario {ini} guardado." + (" Al ingresar va a tener que cambiar la clave." if clave else ""), "ok")
            return redirect(url_for("usuarios"))
        u = {**(dict(u) if u else {}), "iniciales": ini, "nombre": vals[1], "sectores": sectores, "admin": vals[3],
             "activo": vals[4], "perfil_id": perfil_id, "permisos_mas": vals[6], "permisos_menos": vals[7],
             "clave_hash": u["clave_hash"] if u else None, "titulo": titulo, "mn": mn, "mp": mp}
    lista_perfiles = perfiles_con_permisos()
    tiene_firma = bool(uid and db.uno("SELECT 1 FROM firmas WHERE usuario_id=?", (uid,)))
    return render_template("usuario.html", u=u, perfiles=lista_perfiles, tiene_firma=tiene_firma, PERMISOS=permisos.PERMISOS,
                           GRUPOS=permisos.GRUPOS, lista_permisos=permisos.lista,
                           mapa_perfiles={p["id"]: sorted(p["set"]) for p in lista_perfiles})


def perfiles_con_permisos():
    return [{**dict(f), "set": permisos.lista(f["permisos"])} for f in db.q(
        """SELECT p.*, (SELECT COUNT(*) FROM usuarios u WHERE u.perfil_id=p.id AND u.activo=1) AS usuarios
           FROM perfiles p ORDER BY p.nombre""")]


@app.route("/perfiles")
@requiere_admin
def perfiles():
    return render_template("perfiles.html", perfiles=perfiles_con_permisos(), PERMISOS=permisos.PERMISOS,
                           GRUPOS=permisos.GRUPOS)


@app.route("/perfiles/nuevo", methods=["GET", "POST"])
@app.route("/perfiles/<int:pid>", methods=["GET", "POST"])
@requiere_admin
def perfil(pid=None):
    yo = usuario_actual()
    p = db.uno("SELECT * FROM perfiles WHERE id=?", (pid,)) if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        if request.form.get("eliminar"):
            if db.uno("SELECT 1 FROM usuarios WHERE perfil_id=?", (pid,)):
                flash("No se puede eliminar: hay usuarios con este perfil. Cambiales el perfil primero.", "error")
                return redirect(url_for("perfil", pid=pid))
            db.ex("DELETE FROM perfiles WHERE id=?", (pid,))
            db.auditar(yo["id"], None, "eliminar_perfil", p["nombre"])
            flash(f"Perfil {p['nombre']} eliminado.", "ok")
            return redirect(url_for("perfiles"))
        nombre = request.form.get("nombre", "").strip()
        elegidos = permisos.texto({k for k in permisos.PERMISOS if request.form.get("p_" + k)})
        if not nombre or db.uno("SELECT 1 FROM perfiles WHERE nombre=? AND id<>?", (nombre, pid or 0)):
            flash("El nombre está vacío o ya lo usa otro perfil.", "error")
        else:
            if p:
                db.ex("UPDATE perfiles SET nombre=?, permisos=? WHERE id=?", (nombre, elegidos, pid))
            else:
                pid = db.ex("INSERT INTO perfiles (nombre, permisos) VALUES (?,?)", (nombre, elegidos))
            db.auditar(yo["id"], None, "perfil", f"{nombre}: {elegidos or 'sin permisos'}")
            flash(f"Perfil {nombre} guardado.", "ok")
            return redirect(url_for("perfiles"))
        p = {**(dict(p) if p else {}), "nombre": nombre, "permisos": elegidos}
    usuarios_del = db.q("SELECT iniciales, nombre, activo FROM usuarios WHERE perfil_id=? ORDER BY iniciales", (pid,)) if pid else []
    return render_template("perfil.html", p=p, marcados=permisos.lista(p["permisos"] if p else ""), usuarios=usuarios_del,
                           PERMISOS=permisos.PERMISOS, GRUPOS=permisos.GRUPOS)


@app.route("/feriados", methods=["GET", "POST"])
@requiere_permiso("feriados")
def feriados():
    yo = usuario_actual()
    if request.method == "POST":
        f, desc = request.form.get("fecha", ""), request.form.get("descripcion", "").strip()
        if request.form.get("borrar"):
            db.ex("DELETE FROM feriados WHERE fecha=?", (request.form["borrar"],))
            db.auditar(yo["id"], None, "feriado_borrado", request.form["borrar"])
        elif len(f) == 10:
            db.ex("DELETE FROM feriados WHERE fecha=?", (f,))
            db.ex("INSERT INTO feriados VALUES (?,?)", (f, desc))
            db.auditar(yo["id"], None, "feriado", f"{f} {desc}")
            flash("Feriado guardado.", "ok")
        return redirect(url_for("feriados"))
    return render_template("feriados.html", feriados=db.q("SELECT * FROM feriados ORDER BY fecha"))


TIPOS_ETIQUETA = {"bp": "Recepción", "pap": "PAP-Laboratorio", "lab": "BP-Laboratorio"}
GRUPO_NUMERACION = ("bp", "pap")
ESTUDIO_LAB = {"lab": "BP", "pap": "PAP"}
LOTES_ETIQUETA_EXTRA = ["PAPS"]
MUESTRAS_PAP = ["EXO", "ENDO", "ENDO/EXO", "PAPURG", "CUPULA", "DERRAME"]
CODIGO_MUESTRA_PAP = {"citologia endocervical": "ENDO", "citologia exocervical": "EXO", "cupula vaginal": "CUPULA", "liquido": "DERRAME"}
MAX_PROTOCOLO = 999999
DIAS_ETIQUETADOS = 3


def codigo_muestra_pap(tipo_muestra, cantidad=""):
    if (cantidad or "").strip() == "1/2":
        return "ENDO/EXO"
    normal = unicodedata.normalize("NFD", tipo_muestra or "").encode("ascii", "ignore").decode().strip().lower()
    return CODIGO_MUESTRA_PAP.get(normal, (tipo_muestra or "").strip().upper())


def numero_protocolo(n):
    return f"C{n:06d}"


def estudio_de_lote(tipo_lote):
    return {"PAPS": "PAP", "CT": "CT"}.get(tipo_lote, "BP")


def numero_emitido(protocolo):
    m = re.fullmatch(r"C(\d{6})", protocolo or "")
    if not m:
        return True
    n = int(m.group(1))
    return db.uno("SELECT 1 FROM etiquetas_lotes WHERE tipo IN ('bp','pap') AND desde <= ? AND hasta >= ?", (n, n)) is not None


def personal(sector):
    filas = db.q("SELECT iniciales, nombre, sectores FROM usuarios WHERE activo=1 ORDER BY iniciales")
    return [{"iniciales": u["iniciales"], "nombre": u["nombre"] if (u["nombre"] or u["iniciales"]) != u["iniciales"] else ""}
            for u in filas if sector in (u["sectores"] or "").split(",")]


def tipos_lote_etiqueta():
    return sorted(set(tipos_lote_fijos()) | set(LOTES_ETIQUETA_EXTRA), key=str.casefold)


def listas_etiquetas():
    return {"tiposLote": tipos_lote_etiqueta(), "muestrasPap": MUESTRAS_PAP,
            "citotecnicos": personal("citotecnico"), "patologos": personal("firmante")}


def etiquetas_historial():
    progreso = {r["etiqueta_lote_id"]: r["ok"] for r in db.q(
        "SELECT etiqueta_lote_id, SUM(CASE WHEN borrador=0 THEN 1 ELSE 0 END) AS ok FROM protocolos "
        "WHERE etiqueta_lote_id IS NOT NULL GROUP BY etiqueta_lote_id")}
    out = []
    for f in db.q("""SELECT e.*, u.iniciales AS creador, l.codigo AS lote_codigo FROM etiquetas_lotes e
                     LEFT JOIN usuarios u ON u.id=e.creado_por LEFT JOIN lotes l ON l.id=e.lote_id ORDER BY e.id"""):
        out.append({"id": f["id"], "tipo": f["tipo"], "desde": f["desde"], "hasta": f["hasta"], "loteId": f["lote_id"],
                    "loteCodigo": f["lote_codigo"], "n": f["n"], "porProto": f["por_proto"], "etiquetas": f["etiquetas"],
                    "creadoEn": f["creado_en"], "creador": f["creador"] or "", "params": json.loads(f["params"]),
                    "completados": progreso.get(f["id"]) if f["tipo"] == "bp" else None})
    return out


def etiquetas_cantidad(cantidad):
    return int(cantidad) if (cantidad or "").isdigit() else (1 if cantidad else 0)


def etiquetas_casos():
    limite = (datetime.now() - timedelta(days=DIAS_ETIQUETADOS)).strftime("%Y-%m-%d")
    filas = db.q("""SELECT e.id, e.tipo, p.numero, p.apellido, p.nombre, e.cantidad, e.lote_id, l.codigo AS lote,
                           p.fecha_recoleccion, e.lab_etiquetado_en, e.tipo_muestra, u.iniciales AS resp
                    FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                    LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                    WHERE p.borrador=0 AND e.anulado=0 AND e.tipo IN ('BP','PAP') AND e.cantidad IS NOT NULL AND e.cantidad<>''
                      AND (e.lab_etiquetado_en IS NULL OR e.lab_etiquetado_en >= ?) ORDER BY e.lote_id, e.id""", (limite,))
    return [{"id": f["id"], "estudio": f["tipo"], "protocolo": f["numero"], "apellido": f["apellido"] or "",
             "nombre": f["nombre"] or "", "cantidad": etiquetas_cantidad(f["cantidad"]), "loteId": f["lote_id"],
             "loteCodigo": f["lote"] or "", "fechaRec": f["fecha_recoleccion"] or "", "resp": f["resp"] or "",
             "muestra": codigo_muestra_pap(f["tipo_muestra"], f["cantidad"]) if f["tipo"] == "PAP" else "",
             "etiquetado": bool(f["lab_etiquetado_en"])}
            for f in filas]


def siguiente_libre():
    marcas = ",".join("?" * len(GRUPO_NUMERACION))
    fila = db.uno(f"SELECT MAX(hasta) AS m FROM etiquetas_lotes WHERE tipo IN ({marcas})", GRUPO_NUMERACION)
    return (fila["m"] or 0) + 1


def _entero(valor, minimo, maximo):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return None
    return n if minimo <= n <= maximo else None


def _lista_valida(valor, total, permitidos):
    return isinstance(valor, list) and len(valor) == total and all(v in permitidos for v in valor)


def datos_etiquetas():
    return {"listas": listas_etiquetas(), "historial": etiquetas_historial(), "casos": etiquetas_casos()}


@app.route("/etiquetas")
@requiere_permiso("etiquetas_recepcion", "etiquetas_lab")
def etiquetas():
    preset = None
    if request.args.get("lote"):
        lote = db.uno("SELECT * FROM lotes WHERE id=?", (int(request.args["lote"]),)) if request.args["lote"].isdigit() else None
        if not lote:
            flash("El lote no existe.", "error")
            return redirect(url_for("lotes"))
        if not puede("etiquetas_lab"):
            flash("No tenés permiso para las etiquetas de laboratorio.", "error")
            return redirect(url_for("lote", lote_id=lote["id"]))
        if lote["tipo_lote"] in tipos_lote("BP"):
            preset = {"tab": "lab", "loteId": lote["id"]}
        elif lote["tipo_lote"] in tipos_lote("PAP"):
            preset = {"tab": "pap", "loteId": lote["id"]}
        else:
            flash("Las etiquetas de laboratorio son para lotes de biopsias y de PAP.", "error")
            return redirect(url_for("lote", lote_id=lote["id"]))
    return render_template("etiquetas.html", datos={**datos_etiquetas(), "nombres": TIPOS_ETIQUETA, "preset": preset})


@app.route("/api/etiquetas/estado")
@requiere_permiso("etiquetas_recepcion", "etiquetas_lab")
def api_etiquetas_estado():
    return jsonify({"historial": etiquetas_historial(), "casos": etiquetas_casos()})


@app.route("/api/etiquetas/confirmar", methods=["POST"])
@requiere_permiso("etiquetas_recepcion", "etiquetas_lab")
def api_etiquetas_confirmar():
    yo = usuario_actual()
    d = request.get_json(silent=True) or {}
    p = d.get("params") if isinstance(d.get("params"), dict) else {}
    tipo = d.get("tipo")

    def error(texto, estado=400, **extra):
        return jsonify({"ok": False, "error": texto, **datos_etiquetas(), **extra}), estado

    if tipo not in TIPOS_ETIQUETA:
        return error("Tipo de etiqueta inválido.")
    if not puede("etiquetas_recepcion" if tipo == "bp" else "etiquetas_lab"):
        return error(f"No tenés permiso para etiquetas de {TIPOS_ETIQUETA[tipo]}.", 403)
    citos = {x["iniciales"] for x in personal("citotecnico")}
    desde = hasta = None
    borradores = etiquetados = None

    if tipo == "bp":
        n = _entero(d.get("n"), 1, 1000)
        desde = _entero(d.get("inicio"), 1, MAX_PROTOCOLO)
        if not n or not desde:
            return error("Cargá la cantidad de protocolos (1 a 1000) y el primer número.")
        hasta = desde + n - 1
        if hasta > MAX_PROTOCOLO:
            return error(f"El rango se pasa de {numero_protocolo(MAX_PROTOCOLO)}. Bajá la cantidad o el primer número.")
        try:
            datetime.strptime(str(p.get("fecha", "")), "%Y-%m-%d")
        except ValueError:
            return error("Elegí la fecha de recolección antes de confirmar.")
        if p.get("lote") not in tipos_lote_etiqueta():
            return error("Tipo de lote inválido.")
        paps = p["lote"] == "PAPS"
        if paps and p.get("cito") not in citos:
            return error("Elegí el citotécnico: con lote PAPS va en la segunda línea de cada etiqueta.")
        cito = p["cito"] if paps else ""
        params = {"fecha": p["fecha"], "lote": p["lote"], "cito": cito}
        est = REGISTRO[estudio_de_lote(p["lote"])]
        borradores = {"estudio": est.clave, "categoria": est.categoria, "subcategoria": est.subcategoria_fija,
                      "sitio": est.sitio_fijo, "tipo_lote": cito if paps else p["lote"], "fecha_lote": hoy(),
                      "fecha_rec": p["fecha"], "protocolos": [numero_protocolo(k) for k in range(desde, hasta + 1)],
                      "responsable_id": (db.uno("SELECT id FROM usuarios WHERE iniciales=?", (cito,))["id"] if paps else None)}
        por_proto, total = 2, n * 2
    else:
        ids = d.get("items")
        if not isinstance(ids, list) or not ids or len(ids) > 500 or len(set(ids)) != len(ids) or \
                not all(isinstance(i, int) for i in ids):
            return error("Marcá al menos un protocolo para etiquetar.")
        filas = {f["id"]: f for f in db.q(
            f"""SELECT e.*, p.numero, p.borrador, p.fecha_recoleccion, u.iniciales AS resp, l.codigo AS lote_codigo
                FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                WHERE e.id IN ({','.join('?' * len(ids))})""", ids)}
        items = []
        for i in ids:
            f = filas.get(i)
            if not f or f["anulado"] or f["borrador"] or f["tipo"] != ESTUDIO_LAB[tipo] or not etiquetas_cantidad(f["cantidad"]):
                return error(f"El protocolo {f['numero'] if f else i} no está listo para {TIPOS_ETIQUETA[tipo]}: "
                             "tiene que estar completo (paciente y cantidad) y ser del estudio que corresponde.")
            items.append({"casoId": f["id"], "protocolo": f["numero"], "cantidad": etiquetas_cantidad(f["cantidad"]),
                          "loteCodigo": f["lote_codigo"] or "", "resp": f["resp"] or "", "fechaRec": f["fecha_recoleccion"] or "",
                          "muestra": codigo_muestra_pap(f["tipo_muestra"], f["cantidad"]) if tipo == "pap" else ""})
        n, total, por_proto = len(items), sum(i["cantidad"] for i in items), 1
        params = {"items": items}
        por_etiqueta = lambda campo: [i[campo] for i in items for _ in range(i["cantidad"])]
        if tipo == "lab":
            params["patos"] = por_etiqueta("resp")
        else:
            params["muestras"] = por_etiqueta("muestra")
        etiquetados = ids

    r = db.etiquetas_confirmar(tipo, GRUPO_NUMERACION, desde, hasta, n, por_proto, total,
                               json.dumps(params, ensure_ascii=False), yo["id"], borradores, etiquetados)
    if r.get("error") == "choque":
        f = r["fila"]
        return error(f"Ese rango se pisa con el lote de etiquetas N° {f['id']} ({TIPOS_ETIQUETA[f['tipo']]}), ya confirmado: "
                     f"{numero_protocolo(f['desde'])} a {numero_protocolo(f['hasta'])}. Cambiá el primer número: el siguiente "
                     f"libre es {numero_protocolo(siguiente_libre())}.", 409, conflicto=True)
    if r.get("error") == "existentes":
        ej = ", ".join(r["protocolos"][:3]) + ("…" if len(r["protocolos"]) > 3 else "")
        return error(f"Ya existen protocolos con esos números ({ej}), cargados a mano. "
                     "Elegí otro primer número.", 409)
    if r["lote"]:
        if r["lote"]["nuevo"]:
            db.auditar(yo["id"], None, "nuevo_lote", r["lote"]["codigo"])
        detalle = f"{numero_protocolo(desde)} a {numero_protocolo(hasta)} → lote {r['lote']['codigo']}"
    else:
        detalle = f"{n} protocolos"
    db.auditar(yo["id"], None, "etiquetas", f"{TIPOS_ETIQUETA[tipo]} {detalle} ({total} etiquetas)")
    return jsonify({"ok": True, "id": r["id"], **datos_etiquetas()})


@app.route("/completar")
@requiere_permiso("protocolo_crear")
def completar():
    lote_sel = request.args.get("lote", "")
    filtro = ("e.lote_id=?", (int(lote_sel),)) if lote_sel.isdigit() else ("1=1", ())
    protocolos = {}
    for e in cargar_estudios("p.borrador=1 AND " + filtro[0], filtro[1], borradores=True):
        protocolos.setdefault(e["protocolo_id"], {"id": e["protocolo_id"], "numero": e["numero"],
                                                  "fecha_recoleccion": e["fecha_recoleccion"], "estudios": []})["estudios"].append(e)
    lotes_con = db.q("""SELECT l.id, l.codigo, COUNT(DISTINCT p.id) AS n FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                        JOIN lotes l ON l.id=e.lote_id WHERE p.borrador=1 GROUP BY l.id, l.codigo, l.fecha ORDER BY l.fecha DESC, l.codigo""")
    return render_template("completar.html", protocolos=sorted(protocolos.values(), key=lambda x: x["numero"]),
                           lotes_con=lotes_con, lote_sel=lote_sel)


@app.route("/exportar")
@requiere_permiso("exportar")
def exportar():
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    etapas = {}
    for x in db.q("SELECT x.estudio_id, x.etapa, x.fecha_hora, u.iniciales FROM etapas x JOIN usuarios u ON u.id=x.usuario_id"):
        etapas.setdefault(x["estudio_id"], {})[x["etapa"]] = x
    macro = {r["estudio_id"]: r for r in db.q("SELECT * FROM macro")}
    micro = {r["estudio_id"]: r for r in db.q("SELECT * FROM micro")}
    ihq = {r["estudio_id"]: r for r in db.q("SELECT * FROM ihq")}
    protocolos = {r["id"]: r for r in db.q("SELECT * FROM protocolos")}
    orden_etapas = [k for k in NOMBRE_ETAPA if k != "ingreso"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estudios"
    cab = (["N° Protocolo", "Estudio", "Estado", "Lote", "Anulado", "Protocolo sistema", "Cargado en sistema", "Responsable",
            "Ingresado", "Fecha recolección", "DNI", "Apellido", "Nombre", "Sexo", "Fecha nacimiento", "Cobertura",
            "N° afiliado", "Exento", "E-mail", "Teléfono", "Médico", "Lugar recolección", "Lugar entrega",
            "Observaciones protocolo", "Categoría", "Subcategoría", "Sitio", "Tipo de muestra", "Cantidad",
            "Citología hormonal", "Observaciones estudio",
            "Template macro", "Descripción macro", "Cassettes", "Template micro", "Descripción micro", "Conclusión",
            "Bethesda", "Técnicas especiales", "Solicita IHQ", "Marcadores IHQ", "Resultado IHQ"]
           + [f"{NOMBRE_ETAPA[k]} - {x}" for k in orden_etapas for x in ("usuario", "fecha/hora")])
    ws.append(cab)
    for e in cargar_estudios():
        p = protocolos[e["protocolo_id"]]
        ma, mi, ih, et = macro.get(e["id"]), micro.get(e["id"]), ihq.get(e["id"]), etapas.get(e["id"], {})
        g = lambda r, k: (r[k] if r else "") or ""
        fila = [p["numero"], e["etiqueta"], e["estado"], e["lote"], "Si" if e["anulado"] else "", p["protocolo_sistema"],
                "Si" if p["cargado_sistema"] else "No", e["responsable"], fecha_hora(e["creado_en"]),
                fecha(p["fecha_recoleccion"]), p["dni"], p["apellido"], p["nombre"], p["sexo"], fecha(p["fecha_nacimiento"]),
                p["cobertura"], p["n_afiliado"], p["exento"], p["email"], p["telefono"], p["medico"], p["lugar_recoleccion"],
                p["lugar_entrega"], p["observaciones"], e["categoria"], e["subcategoria"], e["sitio"], e["tipo_muestra"],
                e["cantidad"], e["citologia_hormonal"], e["observaciones"],
                g(ma, "template"), g(ma, "descripcion"), g(ma, "cassettes"),
                g(mi, "template"), g(mi, "descripcion"), g(mi, "conclusion"), g(mi, "bethesda"),
                g(mi, "tecnicas_especiales"), "Si" if mi and mi["solicita_ihq"] else "", g(ih, "marcadores"), g(ih, "resultado")]
        for k in orden_etapas:
            x = et.get(k)
            fila += [x["iniciales"] if x else "", fecha_hora(x["fecha_hora"]) if x else ""]
        ws.append(fila)
    for i, cell in enumerate(ws[1], start=1):
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="5B2C83")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = 16
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    db.auditar(usuario_actual()["id"], None, "exportar")
    return send_file(buf, as_attachment=True, download_name=f"contingencia_{datetime.now():%Y%m%d_%H%M}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def ips_locales():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


if __name__ == "__main__":
    try:
        db.inicializar()
    except (RuntimeError, d1.ErrorD1) as error:
        print(f"No se puede iniciar el sistema: {error}")
        raise SystemExit(1)
    if os.environ.get("CONTINGENCIA_DESARROLLO") == "1":
        app.jinja_env.auto_reload = True
        recarga = os.environ.get("CONTINGENCIA_SIN_RECARGA") != "1"
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not recarga:
            print("=" * 64)
            print(" MODO DESARROLLO — " + ("recarga automática al guardar" if recarga else "con depurador, SIN recarga (reiniciar tras cambiar un .py)"))
            print(f" Abrir:             http://localhost:{PUERTO}")
            print(f" Base de datos:     {db.nombre_base()}")
            print("=" * 64)
        app.run(host="127.0.0.1", port=PUERTO, debug=True, use_reloader=recarga)
        raise SystemExit
    from waitress import serve
    print("=" * 64)
    print(" Sistema de contingencia CAP Vighi")
    print(f" En esta PC:        http://localhost:{PUERTO}")
    for ip in ips_locales():
        print(f" Desde otras PCs:   http://{ip}:{PUERTO}")
    print(f" Base de datos:     {db.nombre_base()}")
    print(" Para detenerlo: cerrar esta ventana.")
    print("=" * 64)
    serve(app, host="0.0.0.0", port=PUERTO, threads=12)
