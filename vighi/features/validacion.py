from flask import Blueprint, flash, redirect, render_template, request, url_for

from vighi.core.sesion import requiere_permiso, usuario_actual
from vighi.servicios.consultas import cargar_estudios, listas
from vighi.servicios.ordenes import ordenes_de
from vighi.servicios.protocolos import protocolo_o_404
from vighi.servicios.validacion import error_validacion, es_provisorio, guardar, leer_formulario, pendientes, siguiente

bp = Blueprint("validacion", __name__)


@bp.route("/validacion")
@requiere_permiso("validacion")
def validacion():
    return render_template("validacion/lista.html", protocolos=pendientes())


@bp.route("/protocolo/<int:pid>/validar", methods=["GET", "POST"])
@requiere_permiso("validacion")
def validar(pid):
    p = protocolo_o_404(pid)
    if not p["pendiente_validacion"]:
        flash(f"El protocolo {p['numero']} no está pendiente de validación.", "ok")
        return redirect(url_for("validacion.validacion"))
    valores = {**dict(p), **({"apellido": "", "nombre": ""} if es_provisorio(p) else {})}
    if request.method == "POST":
        d = leer_formulario(request.form)
        error = error_validacion(d, p)
        if error:
            flash(error, "error")
            valores = {**valores, **d}
        else:
            guardar(pid, d, usuario_actual())
            flash(f"Protocolo {p['numero']} validado.", "ok")
            destino = siguiente(pid) if request.form.get("siguiente") else None
            return redirect(url_for("validacion.validar", pid=destino) if destino else url_for("validacion.validacion"))
    estudios = [e for e in cargar_estudios("e.protocolo_id=?", (pid,)) if not e["anulado"]]
    return render_template("validacion/validar.html", p=valores, protocolo=p, estudios=estudios, ordenes=ordenes_de(pid), listas=listas(),
                           hay_siguiente=siguiente(pid) is not None)
