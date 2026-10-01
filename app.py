"""Sistema web provisorio de contingencia — CAP Vighi.

Corre en una PC del laboratorio; el resto entra por la red interna con el navegador.
Iniciar:  py app.py   (o "Iniciar contingencia.bat")
"""
import io
import json
import os
import re
import secrets
import socket
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request, send_file,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import trazabilidad
from estudios import NOMBRE_ETAPA, PASOS_IHQ, REGISTRO, SECTORES, TIPOS, validar_combinacion

PUERTO = int(os.environ.get("CONTINGENCIA_PUERTO", "8000"))
# 1 = solo el sector correspondiente puede marcar cada etapa como lista (el admin siempre puede)
ESTRICTO = os.environ.get("CONTINGENCIA_ESTRICTO", "0") == "1"

app = Flask(__name__)


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


# ---------------------------------------------------------------- sesión y seguridad
def usuario_actual():
    uid = session.get("uid")
    return db.uno("SELECT * FROM usuarios WHERE id=? AND activo=1", (uid,)) if uid else None


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
    pendientes = db.uno("SELECT COUNT(*) AS n FROM protocolos WHERE borrador=1")["n"] if u else 0
    return {"yo": u, "csrf": session.get("csrf", ""), "TIPOS": TIPOS, "SECTORES": SECTORES, "REGISTRO": REGISTRO,
            "n_borradores": pendientes,
            "NOMBRE_ETAPA": NOMBRE_ETAPA, "mis_sectores": set((u["sectores"] or "").split(",")) if u else set()}


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


# ---------------------------------------------------------------- login
@app.route("/configurar", methods=["GET", "POST"])
def configurar():
    """Primer arranque: crear la clave del administrador. Solo desde la PC servidor."""
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


# ---------------------------------------------------------------- listas y responsables
def listas():
    out = {}
    for r in db.q("SELECT nombre, valor FROM listas ORDER BY nombre, orden"):
        out.setdefault(r["nombre"], []).append(r["valor"])
    return out


def responsables(tipo):
    sector = REGISTRO[tipo].sector_responsable
    return [u for u in db.q("SELECT id, iniciales, nombre, sectores FROM usuarios WHERE activo=1 ORDER BY iniciales")
            if sector in (u["sectores"] or "").split(",")]


# ---------------------------------------------------------------- estudios (listados)
def cargar_estudios(where="1=1", params=(), borradores=False):
    """Estudios con los datos de su protocolo, estado, próxima etapa y vencimiento. Los de protocolos en borrador
    (generados desde Recepción, sin los datos del paciente) quedan afuera salvo que se pidan."""
    filas = db.q(f"""SELECT e.*, p.numero, p.apellido, p.nombre, p.dni, p.fecha_recoleccion, p.cargado_sistema, p.borrador,
                            u.iniciales AS responsable, l.codigo AS lote, COALESCE(m.solicita_ihq, 0) AS solicita_ihq,
                            (SELECT COUNT(*) FROM estudios x WHERE x.protocolo_id=e.protocolo_id AND x.anulado=0) AS hermanos
                     FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                     LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                     LEFT JOIN micro m ON m.estudio_id=e.id
                     WHERE {where}{'' if borradores else ' AND p.borrador=0'} ORDER BY p.id DESC, e.id""", params)
    hechas = {}
    for r in db.q("SELECT estudio_id, etapa FROM etapas"):
        hechas.setdefault(r["estudio_id"], set()).add(r["etapa"])
    out, fer, ahora_ = [], db.feriados(), datetime.now()
    for f in filas:
        d = dict(f)
        tipo = REGISTRO[f["tipo"]]
        d["estado"], prox = tipo.estado(hechas.get(f["id"], set()), bool(f["solicita_ihq"]), bool(f["anulado"]))
        if f["borrador"]:
            d["estado"] = "A completar"
        d["proxima"] = prox
        d["vence"] = trazabilidad.limite(f["tipo"], prox[0], f["fecha_recoleccion"] or f["creado_en"], fer) if prox else None
        d["atrasado"] = bool(d["vence"] and d["vence"] < ahora_)
        d["etiqueta"] = etiqueta(f)
        out.append(d)
    return out


def etiqueta(e):
    """Cómo se nombra un estudio dentro del protocolo, ej. 'Biopsia · Mama'."""
    if e["tipo"] == "PAP" or not e["sitio"]:
        return TIPOS[e["tipo"]]
    return f"{TIPOS[e['tipo']]} · {e['sitio']}"


def tipos_lote_fijos():
    """Tipos de lote que no son iniciales de citotécnico: los de la base más los que exige cada estudio
    (así una base creada antes de sumar un tipo, como HPM, no necesita migración)."""
    fijos = listas().get("tipo_lote", [])
    return fijos + [t for e in REGISTRO.values() for t in e.lotes if t not in fijos]


@app.route("/")
@requiere_login
def tablero():
    yo = usuario_actual()
    f = {k: request.args.get(k, "") for k in ("q", "tipo", "ver", "sector")}
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
        if f["q"]:
            texto = " ".join(str(e[k] or "") for k in ("numero", "apellido", "nombre", "dni", "lote", "sitio")).lower()
            return f["q"].lower() in texto
        return True

    return render_template("tablero.html", estudios=[e for e in todos if pasa(e)], f=f, conteo=conteo)


# ---------------------------------------------------------------- lotes (asignación)
def tipos_lote(tipo=None):
    """Tipos de lote válidos para un tipo de estudio (o todos si no se indica)."""
    fijos = tipos_lote_fijos()
    cito = [u["iniciales"] for u in responsables("PAP")]
    if tipo:
        return REGISTRO[tipo].tipos_lote(fijos, cito)
    return fijos + [i for i in cito if i not in fijos]


def hoy():
    return datetime.now().strftime("%Y-%m-%d")


def crear_lote(tipo_lote, usuario_id):
    """Crea el próximo lote del día para ese tipo: TIPO-MMDD.N"""
    f = hoy()
    n = (db.uno("SELECT MAX(numero) AS m FROM lotes WHERE tipo_lote=? AND fecha=?", (tipo_lote, f))["m"] or 0) + 1
    codigo = f"{tipo_lote}-{f[5:7]}{f[8:10]}.{n}"
    lid = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_por, creado_en) VALUES (?,?,?,?,?,?)",
                (codigo, tipo_lote, f, n, usuario_id, db.ahora()))
    db.auditar(usuario_id, None, "nuevo_lote", codigo)
    return db.uno("SELECT * FROM lotes WHERE id=?", (lid,))


def validar_lote(seleccion, tipo, actual_id=None):
    """Revisa lo elegido en el formulario sin crear nada. Devuelve (lote | 'nuevo:TIPO' | None, error | None)."""
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
    """Crea el lote si se eligió 'nuevo lote' (después de validar todo el formulario)."""
    if isinstance(valor, str):
        return crear_lote(valor[6:], usuario_id)
    return valor


def lotes_para_formulario(tipo, actual_id=None):
    """Lotes abiertos de hoy que corresponden al tipo de estudio, más el lote actual del estudio si es otro."""
    validos = tipos_lote(tipo)
    lotes = [l for l in db.q("SELECT * FROM lotes WHERE fecha=? AND cerrado=0 ORDER BY tipo_lote, numero", (hoy(),))
             if l["tipo_lote"] in validos]
    if actual_id and actual_id not in [l["id"] for l in lotes]:
        actual = db.uno("SELECT * FROM lotes WHERE id=?", (actual_id,))
        if actual:
            lotes.insert(0, actual)
    return lotes


def asignar_lote(estudio_id, lote, usuario_id):
    e = db.uno("SELECT e.protocolo_id, l.codigo FROM estudios e LEFT JOIN lotes l ON l.id=e.lote_id WHERE e.id=?", (estudio_id,))
    db.ex("UPDATE estudios SET lote_id=? WHERE id=?", (lote["id"] if lote else None, estudio_id))
    nuevo = lote["codigo"] if lote else None
    if e["codigo"] != nuevo:
        db.auditar(usuario_id, e["protocolo_id"], "lote", f"{e['codigo'] or '—'} → {nuevo or '—'}", estudio_id)


# ---------------------------------------------------------------- formularios de protocolo y estudio
CAMPOS_PROTOCOLO = ["fecha_recoleccion", "dni", "cobertura", "n_afiliado", "nombre", "apellido", "sexo", "exento",
                    "fecha_nacimiento", "email", "telefono", "medico", "lugar_recoleccion", "lugar_entrega", "observaciones"]
CAMPOS_ESTUDIO = ["categoria", "subcategoria", "sitio", "tipo_muestra", "cantidad", "citologia_hormonal", "observaciones",
                  "responsable_id"]


def leer_protocolo():
    d = {k: request.form.get(k, "").strip() for k in CAMPOS_PROTOCOLO}
    d["numero"] = request.form.get("numero", "").strip()
    return d


def leer_estudio(prefijo, tipo):
    """Campos de un bloque de estudio del formulario (los nombres llevan el prefijo e-N-)."""
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


def validar_estudios(lista, existentes=(), actual_id=None):
    """Valida lotes y combinación. Devuelve (lotes validados en el mismo orden, error | None)."""
    error = validar_combinacion(list(existentes) + lista)
    if error:
        return [], error
    lotes = []
    for e in lista:
        valor, error = validar_lote(e["lote_sel"], e["tipo"], actual_id)
        if error:
            return [], error
        lotes.append(valor)
    return lotes, None


def crear_estudio(protocolo_id, e, lote, usuario_id):
    eid = db.ex(f"INSERT INTO estudios (protocolo_id, tipo, creado_por, creado_en, {', '.join(CAMPOS_ESTUDIO)}) "
                f"VALUES (?,?,?,?,{','.join('?' * len(CAMPOS_ESTUDIO))})",
                [protocolo_id, e["tipo"], usuario_id, db.ahora()] + [e[k] for k in CAMPOS_ESTUDIO])
    db.auditar(usuario_id, protocolo_id, "nuevo_estudio", etiqueta(e), eid)
    asignar_lote(eid, lote, usuario_id)
    return eid


def contexto_formulario():
    """Lo que necesitan los bloques de estudio del formulario para cada tipo."""
    return {"listas": listas(),
            "resp": {t: responsables(t) for t in REGISTRO},
            "lotes_abiertos": {t: lotes_para_formulario(t) for t in REGISTRO},
            "tipos_lote_de": {t: tipos_lote(t) for t in REGISTRO}}


def protocolo_o_404(pid):
    p = db.uno("SELECT p.*, u.iniciales AS creador FROM protocolos p LEFT JOIN usuarios u ON u.id=p.creado_por WHERE p.id=?", (pid,))
    if not p:
        abort(404)
    return p


@app.route("/protocolo/nuevo", methods=["GET", "POST"])
@requiere_login
def protocolo_nuevo():
    yo = usuario_actual()
    p, lista = {}, []
    if request.method == "POST":
        p, lista = leer_protocolo(), estudios_del_formulario()
        lotes, error = validar_estudios(lista)
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
            for e, valor in zip(lista, lotes):
                crear_estudio(pid, e, concretar_lote(valor, yo["id"]), yo["id"])
            flash(f"Protocolo {p['numero']} ingresado con {len(lista)} estudio(s).", "ok")
            if not numero_emitido(p["numero"]):
                flash(f"Atención: {p['numero']} no figura en ningún lote de etiquetas confirmado (menú Etiquetas).", "error")
            return redirect(url_for("protocolo", pid=pid))
    elif request.args.get("tipo") in REGISTRO:
        lista = [{"tipo": request.args["tipo"]}]
    ultimos = [r["numero"] for r in db.q("SELECT numero FROM protocolos ORDER BY id DESC LIMIT 5")]
    return render_template("protocolo_form.html", p=p, estudios=lista, nuevo=True, ultimos=ultimos, **contexto_formulario())


def completo(p, estudios):
    """Un protocolo generado desde Recepción queda completo con apellido, nombre y la cantidad de cada estudio."""
    return bool(p["apellido"] and p["nombre"] and estudios and all(e["cantidad"] for e in estudios if not e["anulado"]))


@app.route("/protocolo/<int:pid>/editar", methods=["GET", "POST"])
@requiere_login
def protocolo_editar(pid):
    """Datos del protocolo. Si está en borrador (generado desde Recepción) también se completan sus estudios."""
    yo = usuario_actual()
    p = protocolo_o_404(pid)
    borrador = bool(p["borrador"])
    actuales = {e["id"]: e for e in db.q("SELECT * FROM estudios WHERE protocolo_id=? ORDER BY id", (pid,))}
    lista = [{**dict(e), "lote_sel": str(e["lote_id"] or "")} for e in actuales.values() if not e["anulado"]] if borrador else []
    if request.method == "POST":
        d = leer_protocolo()
        error = None
        if borrador:
            lista = [e for e in estudios_del_formulario() if e["id"] is None or e["id"] in actuales]
            error = validar_combinacion(lista) if lista else "El protocolo tiene que tener al menos un estudio."
            lotes = []
            for e in lista:
                if error:
                    break
                valor, error = validar_lote(e["lote_sel"], e["tipo"], actuales[e["id"]]["lote_id"] if e["id"] else None)
                lotes.append(valor)
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
            for e, valor in zip(lista, lotes):
                lote = concretar_lote(valor, yo["id"])
                if e["id"]:
                    db.ex(f"UPDATE estudios SET {', '.join(k + '=?' for k in CAMPOS_ESTUDIO)} WHERE id=?",
                          [e[k] for k in CAMPOS_ESTUDIO] + [e["id"]])
                    asignar_lote(e["id"], lote, yo["id"])
                else:
                    crear_estudio(pid, e, lote, yo["id"])
            quitados = [k for k, e in actuales.items() if k not in {x["id"] for x in lista} and not e["anulado"]]
            for k in quitados:          # un bloque quitado se anula (no se borra: queda en el historial)
                db.ex("UPDATE estudios SET anulado=1, motivo_anulacion=? WHERE id=?", ("Quitado al completar el protocolo", k))
                db.auditar(yo["id"], pid, "anular", "Quitado al completar el protocolo", k)
            if completo(d, [dict(x) for x in db.q("SELECT cantidad, anulado FROM estudios WHERE protocolo_id=?", (pid,))]):
                db.ex("UPDATE protocolos SET borrador=0 WHERE id=?", (pid,))
                db.auditar(yo["id"], pid, "completar", d["numero"])
                flash(f"Protocolo {d['numero']} completo.", "ok")
                return redirect(url_for("protocolo", pid=pid))
            flash("Datos guardados. Para completar el protocolo faltan apellido, nombre y la cantidad de cada estudio.", "ok")
            return redirect(url_for("protocolo_editar", pid=pid))
        p = {**dict(p), **d}
    ctx = contexto_formulario()
    for e in actuales.values():             # que el lote actual de cada estudio figure aunque no sea de hoy
        if e["lote_id"] and all(l["id"] != e["lote_id"] for l in ctx["lotes_abiertos"][e["tipo"]]):
            ctx["lotes_abiertos"][e["tipo"]].insert(0, db.uno("SELECT * FROM lotes WHERE id=?", (e["lote_id"],)))
    return render_template("protocolo_form.html", p=p, estudios=lista, nuevo=False, completar=borrador, ultimos=[], **ctx)


@app.route("/protocolo/<int:pid>")
@requiere_login
def protocolo(pid):
    p = protocolo_o_404(pid)
    historial = db.q("""SELECT a.*, u.iniciales FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id
                        WHERE protocolo_id=? ORDER BY a.id DESC""", (pid,))
    return render_template("protocolo.html", p=p, estudios=cargar_estudios("e.protocolo_id=?", (pid,), borradores=True), historial=historial)


@app.route("/protocolo/<int:pid>/estudio/nuevo", methods=["GET", "POST"])
@requiere_login
def estudio_nuevo(pid):
    yo = usuario_actual()
    p = protocolo_o_404(pid)
    existentes = [dict(e) for e in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=?", (pid,))]
    lista = [{"tipo": request.args["tipo"]}] if request.args.get("tipo") in REGISTRO else []
    if request.method == "POST":
        lista = estudios_del_formulario()
        lotes, error = validar_estudios(lista, existentes)
        if not lista:
            error = "Elegí qué estudio agregar."
        if error:
            flash(error, "error")
        else:
            for e, valor in zip(lista, lotes):
                crear_estudio(pid, e, concretar_lote(valor, yo["id"]), yo["id"])
            flash(f"Se agregó {', '.join(etiqueta(e) for e in lista)} al protocolo {p['numero']}.", "ok")
            return redirect(url_for("protocolo", pid=pid))
    return render_template("estudio_form.html", p=p, estudios=lista, editando=None, **contexto_formulario())


@app.route("/estudio/<int:eid>/editar", methods=["GET", "POST"])
@requiere_login
def estudio_editar(eid):
    yo = usuario_actual()
    actual = db.uno("SELECT * FROM estudios WHERE id=?", (eid,)) or abort(404)
    p = protocolo_o_404(actual["protocolo_id"])
    e = dict(actual)
    if request.method == "POST":
        e = {**leer_estudio("e-0-", actual["tipo"]), "id": eid}
        otros = [dict(x) for x in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=? AND id<>?",
                                       (p["id"], eid))]
        lotes, error = validar_estudios([{**e, "anulado": actual["anulado"]}], otros, actual["lote_id"])
        if error:
            flash(error, "error")
        else:
            db.ex(f"UPDATE estudios SET {', '.join(k + '=?' for k in CAMPOS_ESTUDIO)} WHERE id=?",
                  [e[k] for k in CAMPOS_ESTUDIO] + [eid])
            db.auditar(yo["id"], p["id"], "editar_estudio", etiqueta(e), eid)
            asignar_lote(eid, concretar_lote(lotes[0], yo["id"]), yo["id"])
            flash("Datos del estudio actualizados.", "ok")
            return redirect(url_for("estudio", eid=eid))
    else:
        e["lote_sel"] = str(actual["lote_id"] or "")
    ctx = contexto_formulario()
    ctx["lotes_abiertos"][actual["tipo"]] = lotes_para_formulario(actual["tipo"], actual["lote_id"])
    return render_template("estudio_form.html", p=p, estudios=[e], editando=eid, **ctx)


# ---------------------------------------------------------------- ficha del estudio (trazabilidad y carga)
def ficha(eid):
    e = db.uno("""SELECT e.*, p.numero, p.borrador, p.fecha_recoleccion, p.apellido, p.nombre, p.dni, p.medico, p.cobertura,
                         u.iniciales AS responsable, u2.iniciales AS creador, l.codigo AS lote
                  FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                  LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN usuarios u2 ON u2.id=e.creado_por
                  LEFT JOIN lotes l ON l.id=e.lote_id WHERE e.id=?""", (eid,))
    if not e:
        abort(404)
    macro = db.uno("SELECT * FROM macro WHERE estudio_id=?", (eid,))
    micro = db.uno("SELECT * FROM micro WHERE estudio_id=?", (eid,))
    ihq = db.uno("SELECT * FROM ihq WHERE estudio_id=?", (eid,))
    etapas = {x["etapa"]: x for x in db.q("""SELECT x.*, u.iniciales, u.nombre FROM etapas x
                                            JOIN usuarios u ON u.id=x.usuario_id WHERE estudio_id=?""", (eid,))}
    solicita = bool(micro and micro["solicita_ihq"])
    return e, macro, micro, ihq, etapas, solicita


def habilitada(e, etapas, solicita, etapa):
    """La carga de macro / micro solo se puede editar mientras el estudio está en esa etapa.
    Devuelve (True, "") o (False, motivo)."""
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
    e, macro, micro, ihq, etapas, solicita = ficha(eid)
    tipo = REGISTRO[e["tipo"]]
    est, prox = tipo.estado(set(etapas), solicita, bool(e["anulado"]))
    ultima = db.uno("SELECT * FROM etapas WHERE estudio_id=? ORDER BY fecha_hora DESC, id DESC LIMIT 1", (eid,))
    historial = db.q("""SELECT a.*, u.iniciales FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id
                        WHERE estudio_id=? ORDER BY a.id DESC""", (eid,))
    tpl = lambda clase: db.q("SELECT id, titulo FROM templates WHERE clase=? ORDER BY titulo", (clase,))
    pasos = tipo.flujo(solicita)
    traza_enc, traza = trazabilidad.calcular(e, pasos, etapas, db.feriados())
    hermanos = cargar_estudios("e.protocolo_id=?", (e["protocolo_id"],), borradores=True)
    return render_template("estudio.html", e=e, tipo=tipo, macro=macro, micro=micro, ihq=ihq, etapas=etapas, estado=est,
                           prox=prox, ultima=ultima, historial=historial, traza=traza, traza_enc=traza_enc,
                           hermanos=hermanos, etiqueta=etiqueta(e),
                           tpl_macro=tpl("macro"), tpl_micro=tpl("micro"), bethesda=listas().get("bethesda", []),
                           ihq_hecha=any(k in etapas for k in PASOS_IHQ),
                           edita_macro=habilitada(e, etapas, solicita, "macroscopia"),
                           edita_micro=habilitada(e, etapas, solicita, "microscopia"))


def guardar_seccion(tabla, eid, valores):
    if db.uno(f"SELECT 1 FROM {tabla} WHERE estudio_id=?", (eid,)):
        db.ex(f"UPDATE {tabla} SET {', '.join(k + '=?' for k in valores)} WHERE estudio_id=?", list(valores.values()) + [eid])
    else:
        db.ex(f"INSERT INTO {tabla} (estudio_id, {', '.join(valores)}) VALUES (?,{','.join('?' * len(valores))})",
              [eid] + list(valores.values()))


@app.route("/estudio/<int:eid>/macro", methods=["POST"])
@requiere_login
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
@requiere_login
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
@requiere_login
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
@requiere_login
def marcar_listo(eid, etapa):
    yo = usuario_actual()
    e, macro, micro, ihq, etapas, solicita = ficha(eid)
    if e["borrador"]:
        flash("Primero completá los datos del paciente de este protocolo.", "error")
        return redirect(url_for("protocolo_editar", pid=e["protocolo_id"]))
    tipo = REGISTRO[e["tipo"]]
    _, prox = tipo.estado(set(etapas), solicita, bool(e["anulado"]))
    if not prox or prox[0] != etapa:
        flash("Esa etapa no es la próxima pendiente de este estudio.", "error")
    elif ESTRICTO and not yo["admin"] and prox[2] not in (yo["sectores"] or "").split(","):
        flash(f"La etapa {prox[1]} la marca el sector {SECTORES[prox[2]]}.", "error")
    elif (falta := tipo.requisito(etapa, macro, micro, ihq)):
        flash(falta, "error")
    else:
        db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (eid, etapa, yo["id"], db.ahora()))
        db.auditar(yo["id"], e["protocolo_id"], "listo", NOMBRE_ETAPA[etapa], eid)
        flash(f"✔ {NOMBRE_ETAPA[etapa]} registrada por {yo['iniciales']}.", "ok")
    return redirect(request.form.get("volver") or url_for("estudio", eid=eid))


@app.route("/estudio/<int:eid>/deshacer", methods=["POST"])
@requiere_login
def deshacer(eid):
    yo = usuario_actual()
    e = ficha(eid)[0]
    ultima = db.uno("SELECT * FROM etapas WHERE estudio_id=? ORDER BY fecha_hora DESC, id DESC LIMIT 1", (eid,))
    if not ultima:
        flash("No hay etapas para deshacer.", "error")
    elif ultima["usuario_id"] != yo["id"] and not yo["admin"]:
        flash("Solo quien la registró o un administrador puede deshacer la etapa.", "error")
    else:
        db.ex("DELETE FROM etapas WHERE id=?", (ultima["id"],))
        db.auditar(yo["id"], e["protocolo_id"], "deshacer", NOMBRE_ETAPA.get(ultima["etapa"], ultima["etapa"]), eid)
        flash(f"Se deshizo {NOMBRE_ETAPA.get(ultima['etapa'])}.", "ok")
    return redirect(url_for("estudio", eid=eid))


@app.route("/estudio/<int:eid>/anular", methods=["POST"])
@requiere_login
def anular(eid):
    """Se anula solo ese estudio; el protocolo y sus otros estudios siguen."""
    e = ficha(eid)[0]
    motivo = request.form.get("motivo", "").strip()
    nuevo = 0 if e["anulado"] else 1
    otros = [dict(x) for x in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=? AND id<>?",
                                   (e["protocolo_id"], eid))]
    if nuevo and not motivo:
        flash("Indicá el motivo de la anulación.", "error")
    elif not nuevo and (error := validar_combinacion(otros + [{"tipo": e["tipo"], "subcategoria": e["subcategoria"]}])):
        flash(f"No se puede reactivar: {error}", "error")
    else:
        db.ex("UPDATE estudios SET anulado=?, motivo_anulacion=? WHERE id=?", (nuevo, motivo if nuevo else None, eid))
        db.auditar(usuario_actual()["id"], e["protocolo_id"], "anular" if nuevo else "reactivar", motivo, eid)
        flash("Estudio anulado." if nuevo else "Estudio reactivado.", "ok")
    return redirect(url_for("estudio", eid=eid))


@app.route("/protocolo/<int:pid>/sistema", methods=["POST"])
@requiere_login
def cargado_sistema(pid):
    protocolo_o_404(pid)
    cargado = 1 if request.form.get("cargado_sistema") == "1" else 0
    db.ex("UPDATE protocolos SET protocolo_sistema=?, cargado_sistema=? WHERE id=?",
          (request.form.get("protocolo_sistema", "").strip(), cargado, pid))
    db.auditar(usuario_actual()["id"], pid, "sistema", "cargado" if cargado else "no cargado")
    flash("Datos de carga en el sistema actualizados.", "ok")
    return redirect(url_for("protocolo", pid=pid))


# ---------------------------------------------------------------- sección lotes
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
                           grupos_lote=[("Biopsias", tipos_lote("BP")), ("Citologías", tipos_lote("CT")),
                                        ("PAP · citotécnico", tipos_lote("PAP"))])


@app.route("/lotes/nuevo", methods=["POST"])
@requiere_login
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


@app.route("/lotes/<int:lote_id>")
@requiere_login
def lote(lote_id):
    l = lote_o_404(lote_id)
    del_lote = cargar_estudios("e.lote_id=?", (lote_id,), borradores=True)
    del_lote.sort(key=lambda x: x["id"])                      # en orden de ingreso
    sin_lote = [x for x in cargar_estudios("e.lote_id IS NULL AND e.anulado=0")
                if l["tipo_lote"] in tipos_lote(x["tipo"])][:300]
    return render_template("lote.html", l=l, estudios=del_lote, sin_lote=sin_lote,
                           etiquetas_lab=(l["tipo_lote"] in tipos_lote("BP") or l["tipo_lote"] in tipos_lote("PAP"))
                           and any(not x["anulado"] and not x["borrador"] for x in del_lote))


@app.route("/lotes/<int:lote_id>/agregar", methods=["POST"])
@requiere_login
def lote_agregar(lote_id):
    yo = usuario_actual()
    l = lote_o_404(lote_id)
    elegido = request.form.get("estudio_id", "")
    numero = request.form.get("protocolo", "").strip()
    base = "SELECT e.id, e.tipo, e.sitio, e.lote_id, p.numero FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id "
    if elegido.isdigit():
        todos = db.q(base + "WHERE e.id=? AND e.anulado=0", (int(elegido),))
    else:
        todos = db.q(base + "WHERE p.numero=? AND e.anulado=0", (numero,))
    candidatos = [c for c in todos if l["tipo_lote"] in tipos_lote(c["tipo"])]
    if l["cerrado"]:
        flash("El lote está cerrado.", "error")
    elif not elegido and not numero:
        flash("Elegí un estudio de la lista o escribí el N° de protocolo.", "error")
    elif not todos:
        flash(f"No existe el protocolo {numero}. Primero hay que ingresarlo.", "error")
    elif not candidatos:
        flash(f"El protocolo {todos[0]['numero']} no tiene estudios que vayan en un lote {l['tipo_lote']} "
              f"({', '.join(etiqueta(c) for c in todos)}).", "error")
    elif len(candidatos) > 1:
        flash(f"El protocolo {numero} tiene {len(candidatos)} estudios que pueden ir en este lote: elegí cuál de la lista.", "error")
    else:
        c = candidatos[0]
        if c["lote_id"] == lote_id:
            flash(f"{c['numero']} ({etiqueta(c)}) ya está en este lote.", "error")
        else:
            previo = db.uno("SELECT codigo FROM lotes WHERE id=?", (c["lote_id"],)) if c["lote_id"] else None
            asignar_lote(c["id"], l, yo["id"])
            flash(f"{c['numero']} · {etiqueta(c)} agregado al lote" + (f" (estaba en {previo['codigo']})." if previo else "."), "ok")
    return redirect(url_for("lote", lote_id=lote_id))


@app.route("/lotes/<int:lote_id>/quitar/<int:eid>", methods=["POST"])
@requiere_login
def lote_quitar(lote_id, eid):
    l = lote_o_404(lote_id)
    if l["cerrado"]:
        flash("El lote está cerrado.", "error")
    elif db.uno("SELECT 1 FROM estudios WHERE id=? AND lote_id=?", (eid, lote_id)):
        asignar_lote(eid, None, usuario_actual()["id"])
        flash("Estudio quitado del lote.", "ok")
    return redirect(url_for("lote", lote_id=lote_id))


@app.route("/lotes/<int:lote_id>/cerrar", methods=["POST"])
@requiere_login
def lote_cerrar(lote_id):
    yo = usuario_actual()
    l = lote_o_404(lote_id)
    if l["cerrado"]:
        if not yo["admin"]:
            flash("Solo un administrador puede reabrir un lote.", "error")
        else:
            db.ex("UPDATE lotes SET cerrado=0, cerrado_por=NULL, cerrado_en=NULL WHERE id=?", (lote_id,))
            db.auditar(yo["id"], None, "reabrir_lote", l["codigo"])
            flash(f"Lote {l['codigo']} reabierto.", "ok")
    else:
        db.ex("UPDATE lotes SET cerrado=1, cerrado_por=?, cerrado_en=? WHERE id=?", (yo["id"], db.ahora(), lote_id))
        db.auditar(yo["id"], None, "cerrar_lote", l["codigo"])
        flash(f"Lote {l['codigo']} cerrado.", "ok")
    return redirect(url_for("lote", lote_id=lote_id))


@app.route("/lotes/<int:lote_id>/observaciones", methods=["POST"])
@requiere_login
def lote_observaciones(lote_id):
    lote_o_404(lote_id)
    db.ex("UPDATE lotes SET observaciones=? WHERE id=?", (request.form.get("observaciones", "").strip(), lote_id))
    flash("Observaciones guardadas.", "ok")
    return redirect(url_for("lote", lote_id=lote_id))


@app.route("/lotes/<int:lote_id>/eliminar", methods=["POST"])
@requiere_login
def lote_eliminar(lote_id):
    l = lote_o_404(lote_id)
    if db.uno("SELECT 1 FROM estudios WHERE lote_id=?", (lote_id,)):
        flash("Solo se puede eliminar un lote vacío.", "error")
        return redirect(url_for("lote", lote_id=lote_id))
    db.ex("DELETE FROM lotes WHERE id=?", (lote_id,))
    db.auditar(usuario_actual()["id"], None, "eliminar_lote", l["codigo"])
    flash(f"Lote {l['codigo']} eliminado.", "ok")
    return redirect(url_for("lotes", fecha=l["fecha"]))


# ---------------------------------------------------------------- APIs para los formularios
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


# ---------------------------------------------------------------- usuarios
@app.route("/usuarios")
@requiere_admin
def usuarios():
    return render_template("usuarios.html", usuarios=db.q("SELECT * FROM usuarios ORDER BY activo DESC, iniciales"))


@app.route("/usuarios/nuevo", methods=["GET", "POST"])
@app.route("/usuarios/<int:uid>", methods=["GET", "POST"])
@requiere_admin
def usuario(uid=None):
    yo = usuario_actual()
    u = db.uno("SELECT * FROM usuarios WHERE id=?", (uid,)) if uid else None
    if request.method == "POST":
        ini = request.form["iniciales"].strip().upper()
        sectores = ",".join(s for s in SECTORES if request.form.get("s_" + s))
        vals = (ini, request.form.get("nombre", "").strip() or ini, sectores,
                1 if request.form.get("admin") else 0, 1 if request.form.get("activo") else 0)
        dup = db.uno("SELECT id FROM usuarios WHERE iniciales=? AND id<>?", (ini, uid or 0))
        clave = request.form.get("clave", "")
        if not ini or dup:
            flash("Iniciales vacías o ya usadas por otra persona.", "error")
        elif clave and len(clave) < 8:
            flash("La clave temporal debe tener al menos 8 caracteres.", "error")
        elif uid == yo["id"] and not (vals[3] and vals[4]):
            flash("No podés quitarte el rol de administrador ni desactivarte a vos mismo.", "error")
        else:
            if u:
                db.ex("UPDATE usuarios SET iniciales=?, nombre=?, sectores=?, admin=?, activo=? WHERE id=?", vals + (uid,))
            else:
                uid = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo) VALUES (?,?,?,?,?)", vals)
            if clave:
                db.ex("UPDATE usuarios SET clave_hash=?, debe_cambiar_clave=1 WHERE id=?", (generate_password_hash(clave), uid))
            db.auditar(yo["id"], None, "usuario", f"{ini}{' (clave temporal)' if clave else ''}")
            flash(f"Usuario {ini} guardado." + (" Al ingresar va a tener que cambiar la clave." if clave else ""), "ok")
            return redirect(url_for("usuarios"))
    return render_template("usuario.html", u=u)


# ---------------------------------------------------------------- feriados (para las fechas límite)
@app.route("/feriados", methods=["GET", "POST"])
@requiere_admin
def feriados():
    yo = usuario_actual()
    if request.method == "POST":
        f, desc = request.form.get("fecha", ""), request.form.get("descripcion", "").strip()
        if request.form.get("borrar"):
            db.ex("DELETE FROM feriados WHERE fecha=?", (request.form["borrar"],))
            db.auditar(yo["id"], None, "feriado_borrado", request.form["borrar"])
        elif len(f) == 10:
            db.ex("DELETE FROM feriados WHERE fecha=?", (f,))           # SQL estándar (sin INSERT OR REPLACE)
            db.ex("INSERT INTO feriados VALUES (?,?)", (f, desc))
            db.auditar(yo["id"], None, "feriado", f"{f} {desc}")
            flash("Feriado guardado.", "ok")
        return redirect(url_for("feriados"))
    return render_template("feriados.html", feriados=db.q("SELECT * FROM feriados ORDER BY fecha"))


# ---------------------------------------------------------------- etiquetas
# Flujo de contingencia:
#   1) Recepción: se generan las etiquetas (números C000001…). Al confirmar, el servidor crea los protocolos "a completar"
#      (protocolos en borrador, con un estudio según el tipo de lote) dentro del lote abierto del día.
#   2) "Por completar": se cargan el paciente y la cantidad de cada protocolo.
#   3) Laboratorio (PAP-Laboratorio / BP-Laboratorio): se imprimen las etiquetas de los protocolos ya completos, con
#      tantas etiquetas como indique su cantidad. No consumen numeración.
# El servidor es el dueño de la numeración (una sola para todas las PCs) y del historial de lotes de etiquetas.
TIPOS_ETIQUETA = {"bp": "Recepción", "pap": "PAP-Laboratorio", "lab": "BP-Laboratorio"}
GRUPO_NUMERACION = ("bp", "pap")          # ('pap' por los lotes de la versión anterior, que también numeraban)
ESTUDIO_LAB = {"lab": "BP", "pap": "PAP"}  # estudio de los protocolos que rotula cada pestaña de laboratorio
# Tipos que trae el desplegable "Tipo" de southernbits y que no son un tipo de lote de este sistema
LOTES_ETIQUETA_EXTRA = ["PAPS"]
# Códigos que lleva la etiqueta PAP (no coinciden con los tipos de muestra del catálogo, que son más descriptivos)
MUESTRAS_PAP = ["EXO", "ENDO", "ENDO/EXO", "PAPURG", "CUPULA", "DERRAME"]
MAX_PROTOCOLO = 999999
DIAS_ETIQUETADOS = 3                       # cuánto tiempo siguen apareciendo los ya etiquetados (por si hay que reimprimir)


def numero_protocolo(n):
    return f"C{n:06d}"


def estudio_de_lote(tipo_lote):
    """Estudio de los protocolos que genera Recepción según el tipo de lote: PAPS = PAP, CT = citologías y el resto
    (ENDO, ONCO, NO ONCO, PAPURG, TACOS, HPM) biopsias."""
    return {"PAPS": "PAP", "CT": "CT"}.get(tipo_lote, "BP")


def numero_emitido(protocolo):
    """True si el protocolo no es de contingencia (C + 6 dígitos) o si figura en un lote de etiquetas confirmado."""
    m = re.fullmatch(r"C(\d{6})", protocolo or "")
    if not m:
        return True
    n = int(m.group(1))
    return db.uno("SELECT 1 FROM etiquetas_lotes WHERE tipo IN ('bp','pap') AND desde <= ? AND hasta >= ?", (n, n)) is not None


def personal(sector):
    """Usuarios activos de un sector, para los desplegables (el nombre solo si es distinto de las iniciales)."""
    filas = db.q("SELECT iniciales, nombre, sectores FROM usuarios WHERE activo=1 ORDER BY iniciales")
    return [{"iniciales": u["iniciales"], "nombre": u["nombre"] if (u["nombre"] or u["iniciales"]) != u["iniciales"] else ""}
            for u in filas if sector in (u["sectores"] or "").split(",")]


def tipos_lote_etiqueta():
    return sorted(set(tipos_lote_fijos()) | set(LOTES_ETIQUETA_EXTRA), key=str.casefold)


def listas_etiquetas():
    return {"tiposLote": tipos_lote_etiqueta(), "muestrasPap": MUESTRAS_PAP,
            "citotecnicos": personal("citotecnico"), "patologos": personal("firmante")}


def etiquetas_historial():
    """Lotes de etiquetas confirmados, del más viejo al más nuevo. Para los de Recepción, 'completados' = cuántos de los
    protocolos que generó ya tienen los datos del paciente."""
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
    """Cuántas etiquetas de laboratorio lleva un estudio según su cantidad ("1/2" de PAP = 1)."""
    return int(cantidad) if (cantidad or "").isdigit() else (1 if cantidad else 0)


def etiquetas_casos():
    """Estudios (BP y PAP) de protocolos con los datos del paciente y la cantidad ya cargados, candidatos a etiquetas de
    laboratorio. Los ya etiquetados se ofrecen unos días más por si hay que reimprimir."""
    limite = (datetime.now() - timedelta(days=DIAS_ETIQUETADOS)).strftime("%Y-%m-%d")
    filas = db.q("""SELECT e.id, e.tipo, p.numero, p.apellido, p.nombre, e.cantidad, e.lote_id, l.codigo AS lote,
                           p.fecha_recoleccion, e.lab_etiquetado_en, u.iniciales AS resp
                    FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                    LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                    WHERE p.borrador=0 AND e.anulado=0 AND e.tipo IN ('BP','PAP') AND e.cantidad IS NOT NULL AND e.cantidad<>''
                      AND (e.lab_etiquetado_en IS NULL OR e.lab_etiquetado_en >= ?) ORDER BY e.lote_id, e.id""", (limite,))
    return [{"id": f["id"], "estudio": f["tipo"], "protocolo": f["numero"], "apellido": f["apellido"] or "",
             "nombre": f["nombre"] or "", "cantidad": etiquetas_cantidad(f["cantidad"]), "loteId": f["lote_id"],
             "loteCodigo": f["lote"] or "", "fechaRec": f["fecha_recoleccion"] or "", "resp": f["resp"] or "",
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
@requiere_login
def etiquetas():
    """Generador de etiquetas de contingencia. Pantalla aparte, sin la barra del sistema, para que imprima con
    las medidas exactas de las etiquetas. Con ?lote=<id> abre la pestaña de laboratorio con ese lote elegido."""
    preset = None
    if request.args.get("lote"):
        lote = db.uno("SELECT * FROM lotes WHERE id=?", (int(request.args["lote"]),)) if request.args["lote"].isdigit() else None
        if not lote:
            flash("El lote no existe.", "error")
            return redirect(url_for("lotes"))
        if lote["tipo_lote"] in tipos_lote("BP"):
            preset = {"tab": "lab", "loteId": lote["id"]}
        elif lote["tipo_lote"] in tipos_lote("PAP"):
            preset = {"tab": "pap", "loteId": lote["id"]}
        else:
            flash("Las etiquetas de laboratorio son para lotes de biopsias y de PAP.", "error")
            return redirect(url_for("lote", lote_id=lote["id"]))
    return render_template("etiquetas.html", datos={**datos_etiquetas(), "nombres": TIPOS_ETIQUETA, "preset": preset})


@app.route("/api/etiquetas/estado")
@requiere_login
def api_etiquetas_estado():
    return jsonify({"historial": etiquetas_historial(), "casos": etiquetas_casos()})


@app.route("/api/etiquetas/confirmar", methods=["POST"])
@requiere_login
def api_etiquetas_confirmar():
    """Valida y registra un lote de etiquetas. El servidor decide si el rango está libre (es lo que evita que dos PCs
    impriman los mismos números) y, en Recepción, crea los protocolos a completar."""
    yo = usuario_actual()
    d = request.get_json(silent=True) or {}
    p = d.get("params") if isinstance(d.get("params"), dict) else {}
    tipo = d.get("tipo")

    def error(texto, estado=400, **extra):
        return jsonify({"ok": False, "error": texto, **datos_etiquetas(), **extra}), estado

    if tipo not in TIPOS_ETIQUETA:
        return error("Tipo de etiqueta inválido.")
    firmantes = {x["iniciales"] for x in personal("firmante")}
    citos = {x["iniciales"] for x in personal("citotecnico")}
    desde = hasta = None
    borradores = etiquetados = None

    if tipo == "bp":
        # ---- Recepción: reserva números y genera los protocolos a completar
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
        # ---- Laboratorio: protocolos ya completos; la cantidad de etiquetas de cada uno es su "cantidad"
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
                          "loteCodigo": f["lote_codigo"] or "", "resp": f["resp"] or "", "fechaRec": f["fecha_recoleccion"] or ""})
        n, total, por_proto = len(items), sum(i["cantidad"] for i in items), 1
        params = {"items": items}
        if tipo == "lab":
            if not _lista_valida(p.get("patos"), total, firmantes | {""}):
                return error("Patólogo inválido en alguna etiqueta.")
            params.update(patos=p["patos"], pato=p.get("pato") if p.get("pato") in firmantes else "")
        else:
            if not _lista_valida(p.get("muestras"), total, MUESTRAS_PAP):
                return error("Falta elegir el tipo de muestra de cada etiqueta.")
            params.update(muestras=p["muestras"], lotePap=p.get("lotePap") if p.get("lotePap") in MUESTRAS_PAP else "")
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


# ---------------------------------------------------------------- protocolos a completar
@app.route("/completar")
@requiere_login
def completar():
    """Protocolos generados desde Recepción a los que les faltan los datos. Cada uno se completa con el formulario
    del protocolo (paciente + estudios); con apellido, nombre y la cantidad de cada estudio deja de ser borrador."""
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


# ---------------------------------------------------------------- exportar
@app.route("/exportar")
@requiere_login
def exportar():
    """Excel con una fila por estudio (con los datos de su protocolo) y sus etapas, para volver a cargarlos en el sistema."""
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


# ---------------------------------------------------------------- arranque
def ips_locales():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


if __name__ == "__main__":
    from waitress import serve
    db.inicializar()
    db.iniciar_respaldos(minutos=10)
    print("=" * 64)
    print(" Sistema de contingencia CAP Vighi")
    print(f" En esta PC:        http://localhost:{PUERTO}")
    for ip in ips_locales():
        print(f" Desde otras PCs:   http://{ip}:{PUERTO}")
    print(f" Base de datos:     {db.DB_PATH}")
    print(" Para detenerlo: cerrar esta ventana.")
    print("=" * 64)
    serve(app, host="0.0.0.0", port=PUERTO, threads=12)
