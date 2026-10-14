from flask import Blueprint, flash, redirect, request, url_for

from vighi.core import d1, db

bp = Blueprint("sistema", __name__)


@bp.route("/salud")
def salud():
    db.uno("SELECT 1 AS ok")
    return "ok", 200, {"Cache-Control": "no-store"}


@bp.app_errorhandler(413)
def demasiado_grande(_):
    flash("Los archivos superan el máximo de 40 MB por envío. Subí menos imágenes a la vez.", "error")
    destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for("tablero.tablero")
    return redirect(destino)


@bp.app_errorhandler(d1.ErrorConexion)
def sin_base(error):
    return ("<!doctype html><meta charset='utf-8'><title>Sin conexión</title>"
            "<body style='font-family:sans-serif;max-width:560px;margin:15vh auto;padding:0 20px'>"
            "<h1>Sin conexión con la base de datos</h1>"
            "<p>No se pudo comunicar con Cloudflare D1. Revisá la conexión a internet y volvé a intentar en unos segundos.</p>"
            f"<p style='color:#666;font-size:13px'>{str(error)[:200]}</p></body>"), 503
