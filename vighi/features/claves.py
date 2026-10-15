from flask import Blueprint, flash, redirect, render_template, request, url_for

from vighi.core.sesion import requiere_admin, usuario_actual
from vighi.servicios.claves_api import claves, crear_clave, revocar_clave

bp = Blueprint("claves", __name__)


@bp.route("/claves", methods=["GET", "POST"])
@requiere_admin
def claves_api():
    nueva = None
    if request.method == "POST":
        nombre = " ".join(request.form.get("nombre", "").split())[:60]
        if not nombre:
            flash("Escribí un nombre para la clave, por ejemplo «PC del escáner».", "error")
        else:
            nueva = {"nombre": nombre, "token": crear_clave(nombre, usuario_actual()["id"])}
    return render_template("claves/claves.html", claves=claves(), nueva=nueva, url=request.host_url.rstrip("/"))


@bp.route("/claves/<int:kid>/revocar", methods=["POST"])
@requiere_admin
def clave_revocar(kid):
    k = revocar_clave(kid, usuario_actual()["id"])
    flash(f"Clave «{k['nombre']}» revocada: el programa que la usa deja de funcionar." if k else "La clave no existe o ya estaba revocada.", "ok" if k else "error")
    return redirect(url_for("claves.claves_api"))
