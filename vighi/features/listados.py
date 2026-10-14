from flask import Blueprint, flash, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.sesion import requiere_admin, usuario_actual
from vighi.servicios.consultas import listas
from vighi.servicios.listados import LISTADOS, limpiar_listado

bp = Blueprint("listados", __name__)


@bp.route("/listados", methods=["GET", "POST"])
@requiere_admin
def listados():
    yo = usuario_actual()
    if request.method == "POST":
        clave = request.form.get("lista", "")
        if clave in LISTADOS:
            items = limpiar_listado(request.form.get("valores", ""))
            db.lote_ex([("DELETE FROM listas WHERE nombre=?", (clave,))]
                       + [("INSERT INTO listas (nombre, orden, valor) VALUES (?,?,?)", (clave, i, v)) for i, v in enumerate(items)])
            db.auditar(yo["id"], None, "listado", f"{LISTADOS[clave][0]}: {len(items)} valores")
            flash(f"{LISTADOS[clave][0]}: {len(items)} valores guardados.", "ok")
        return redirect(url_for("listados.listados") + f"#{clave}")
    actuales = listas()
    return render_template("listados/listados.html", listados=[(k, t, d, actuales.get(k, [])) for k, (t, d) in LISTADOS.items()])
