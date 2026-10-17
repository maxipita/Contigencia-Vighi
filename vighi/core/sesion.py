import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import abort, flash, g, jsonify, redirect, request, session, url_for

from vighi.core import db, permisos
from vighi.core.config import CONGELACION_ALERTA_HORAS, SEMAFOROS
from vighi.core.opcionales import informes
from vighi.dominio.estudios import NOMBRE_ETAPA, REGISTRO, SECTORES, TIPOS, sector_marca


SQL_USUARIO = """SELECT u.*, p.nombre AS perfil, p.permisos AS perfil_permisos FROM usuarios u
                      LEFT JOIN perfiles p ON p.id=u.perfil_id WHERE u.id=? AND u.activo=1"""
SQL_BORRADORES = "SELECT COUNT(*) AS n FROM protocolos WHERE borrador=1"
SQL_MIS_ALERTAS = "SELECT COUNT(*) AS n FROM congelaciones WHERE estado='agendada' AND patologo_id=? AND (fecha || ' ' || hora)<?"
SQL_MIS_TAREAS = "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN urgencia='urgente' THEN 1 ELSE 0 END), 0) AS urgentes FROM tareas WHERE estado='abierta' AND responsable_id=?"


RUTAS_CON_CLAVE = ("/api/ordenes/automatico",)


def limite_de_alerta():
    return (datetime.now() + timedelta(hours=CONGELACION_ALERTA_HORAS)).strftime("%Y-%m-%d %H:%M")


def adelantar_lecturas():
    if session.get("uid") and request.endpoint != "static":
        g.limite_alerta = limite_de_alerta()
        db.precargar([(SQL_USUARIO, (session["uid"],)), (SQL_BORRADORES, ()), (SQL_MIS_TAREAS, (session["uid"],)), (SQL_MIS_ALERTAS, (session["uid"], g.limite_alerta))])


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
            return redirect(url_for("auth.login", next=request.path))
        if u["debe_cambiar_clave"] and not session.get("real_uid") and request.endpoint not in ("auth.cambiar_clave", "auth.logout"):
            return redirect(url_for("auth.cambiar_clave"))
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
                return redirect(destino or url_for("tablero.tablero"))
            return f(*a, **k)
        return envuelta
    return decorador


def requiere_permiso_o_403(*claves):
    def decorador(f):
        @wraps(f)
        @requiere_login
        def envuelta(*a, **k):
            if not any(puede(c) for c in claves):
                abort(403)
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


def verificar_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST" and request.path not in RUTAS_CON_CLAVE:
        token = request.form.get("_csrf") or request.headers.get("X-CSRF")
        if token != session["csrf"]:
            abort(400, "Formulario vencido: recargá la página e intentá de nuevo.")


def modo_vista():
    if session.get("real_uid") and request.method == "POST" and request.endpoint not in ("auth.ver_como", "auth.dejar_de_ver_como", "auth.logout"):
        mensaje = "Estás viendo el sistema como otro usuario: es solo para mirar, no se registran cambios. Volvé a tu usuario para trabajar."
        if request.path.startswith("/api/"):
            return jsonify({"error": mensaje}), 403
        flash(mensaje, "error")
        destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else None
        return redirect(destino or url_for("tablero.tablero"))


def globales():
    u = usuario_actual()
    pendientes = db.uno(SQL_BORRADORES)["n"] if u else 0
    mis_tareas = db.uno(SQL_MIS_TAREAS, (u["id"],)) if u else None
    mis_alertas = db.uno(SQL_MIS_ALERTAS, (u["id"], g.get("limite_alerta") or limite_de_alerta()))["n"] if u else 0
    vista = None
    if u and session.get("real_uid"):
        real = db.uno("SELECT id, iniciales, nombre FROM usuarios WHERE id=? AND activo=1 AND admin=1", (session["real_uid"],))
        if real:
            vista = {"admin": real, "otros": db.q("SELECT id, iniciales, nombre FROM usuarios WHERE activo=1 AND id<>? ORDER BY iniciales", (real["id"],))}
    return {"vista_como": vista, "yo": u, "csrf": session.get("csrf", ""), "TIPOS": TIPOS, "SECTORES": SECTORES, "REGISTRO": REGISTRO,
            "planes_por_cobertura": db.planes_por_cobertura, "n_borradores": pendientes, "mis_tareas": mis_tareas, "mis_alertas": mis_alertas, "ve_dashboards": bool(u and any(p.startswith("dashboard_") for p in u["permisos"])), "informes_ok": informes is not None, "SEMAFOROS": SEMAFOROS,
            "NOMBRE_ETAPA": NOMBRE_ETAPA, "puede": puede, "sector_marca": sector_marca, "mis_sectores": set((u["sectores"] or "").split(",")) if u else set()}


def es_local():
    return request.remote_addr in ("127.0.0.1", "::1")
