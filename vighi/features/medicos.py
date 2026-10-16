from flask import Blueprint, flash, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.sesion import requiere_login, requiere_permiso, usuario_actual
from vighi.servicios.medicos import (SQL_PROTOCOLOS_POR_MEDICO, SQL_UBICACIONES_POR_MEDICO, buscar, error_medico, limpiar_nombre, medico_o_404, protocolos_de,
                                     ubicaciones_de)
from vighi.servicios.ubicaciones import ubicacion_o_404

bp = Blueprint("medicos", __name__)


def leer_medico():
    return limpiar_nombre(request.form.get("nombre")), request.form.get("email", "").strip().lower()[:150]


@bp.route("/medicos")
@requiere_login
def medicos_lista():
    q = request.args.get("q", "").strip()
    db.precargar([(SQL_UBICACIONES_POR_MEDICO, ()), (SQL_PROTOCOLOS_POR_MEDICO, ())])
    filas, total = buscar(q)
    return render_template("medicos/medicos.html", medicos=filas, total=total, q=q,
                           ubicaciones={r["medico_id"]: r["n"] for r in db.q(SQL_UBICACIONES_POR_MEDICO)},
                           protocolos={r["medico"]: r["n"] for r in db.q(SQL_PROTOCOLOS_POR_MEDICO)})


@bp.route("/medicos/nuevo", methods=["GET", "POST"])
@requiere_permiso("ubicaciones")
def medico_nuevo():
    ubicacion = ubicacion_o_404(int(request.values["ubicacion"])) if request.values.get("ubicacion", "").isdigit() else None
    d = {}
    if request.method == "POST":
        nombre, email = leer_medico()
        d = {"nombre": nombre, "email": email}
        error = error_medico(nombre, email)
        if error:
            flash(error, "error")
        else:
            mid = db.ex("INSERT INTO medicos (nombre, email) VALUES (?,?)", (nombre, email or None))
            if ubicacion:
                db.ex("INSERT INTO ubicacion_medicos (ubicacion_id, medico_id) VALUES (?,?)", (ubicacion["id"], mid))
            db.auditar(usuario_actual()["id"], None, "medico", f"Alta: {nombre}" + (f" (asociado a {ubicacion['abreviatura']})" if ubicacion else ""))
            flash(f"Médico «{nombre}» creado" + (f" y asociado a {ubicacion['abreviatura']}." if ubicacion else "."), "ok")
            if ubicacion:
                return redirect(url_for("ubicaciones.ubicacion", uid=ubicacion["id"]) + "#medicos")
            return redirect(url_for("medicos.medico", mid=mid))
    return render_template("medicos/medico.html", m=d, nuevo=True, ubicaciones=[], protocolos=0, ubicacion=ubicacion)


@bp.route("/medicos/<int:mid>")
@requiere_login
def medico(mid):
    m = medico_o_404(mid)
    return render_template("medicos/medico.html", m=m, nuevo=False, ubicaciones=ubicaciones_de(mid), protocolos=protocolos_de(m["nombre"]), ubicacion=None)


@bp.route("/medicos/<int:mid>/editar", methods=["POST"])
@requiere_permiso("ubicaciones")
def medico_editar(mid):
    m = medico_o_404(mid)
    nombre, email = leer_medico()
    error = error_medico(nombre, email, mid)
    if error:
        flash(error, "error")
        return redirect(url_for("medicos.medico", mid=mid))
    sentencias = [("UPDATE medicos SET nombre=?, email=? WHERE id=?", (nombre, email or None, mid))]
    if nombre != m["nombre"]:
        sentencias.append(("UPDATE protocolos SET medico=? WHERE medico=?", (nombre, m["nombre"])))
    db.lote_ex(sentencias)
    db.auditar(usuario_actual()["id"], None, "medico", f"Edición: {m['nombre']} → {nombre}" if nombre != m["nombre"] else f"Edición: {nombre}")
    flash("Médico actualizado." + (" Se actualizó el nombre en sus protocolos." if nombre != m["nombre"] else ""), "ok")
    return redirect(url_for("medicos.medico", mid=mid))


@bp.route("/medicos/<int:mid>/ubicacion", methods=["POST"])
@requiere_permiso("ubicaciones")
def medico_ubicacion_agregar(mid):
    m = medico_o_404(mid)
    abreviatura = request.form.get("ubicacion", "").strip()
    u = db.uno("SELECT id, abreviatura FROM ubicaciones WHERE abreviatura=?", (abreviatura,))
    if not u:
        flash("No encontré esa ubicación: elegila de la lista que se despliega al escribir.", "error")
    elif db.uno("SELECT 1 FROM ubicacion_medicos WHERE ubicacion_id=? AND medico_id=?", (u["id"], mid)):
        flash(f"Ya está asociado a {u['abreviatura']}.", "error")
    else:
        db.ex("INSERT INTO ubicacion_medicos (ubicacion_id, medico_id) VALUES (?,?)", (u["id"], mid))
        db.auditar(usuario_actual()["id"], None, "ubicacion", f"{u['abreviatura']}: se asoció a {m['nombre']}")
        flash(f"Asociado a {u['abreviatura']}.", "ok")
    return redirect(url_for("medicos.medico", mid=mid) + "#ubicaciones")


@bp.route("/medicos/<int:mid>/ubicaciones/quitar", methods=["POST"])
@requiere_permiso("ubicaciones")
def medico_ubicacion_quitar(mid):
    m = medico_o_404(mid)
    ids = [int(i) for i in request.form.getlist("ubicacion") if i.isdigit()]
    if not ids:
        flash("Marcá las ubicaciones que querés quitar.", "error")
    else:
        db.lote_ex([("DELETE FROM ubicacion_medicos WHERE ubicacion_id=? AND medico_id=?", (i, mid)) for i in ids])
        db.auditar(usuario_actual()["id"], None, "ubicacion", f"{m['nombre']}: se quitó de {len(ids)} ubicación(es)")
        flash(f"Quitado de {len(ids)} ubicación(es).", "ok")
    return redirect(url_for("medicos.medico", mid=mid) + "#ubicaciones")


@bp.route("/medicos/<int:mid>/eliminar", methods=["POST"])
@requiere_permiso("ubicaciones")
def medico_eliminar(mid):
    m = medico_o_404(mid)
    if protocolos_de(m["nombre"]):
        flash("No se puede eliminar: hay protocolos con este médico.", "error")
        return redirect(url_for("medicos.medico", mid=mid))
    db.lote_ex([("DELETE FROM ubicacion_medicos WHERE medico_id=?", (mid,)), ("DELETE FROM medicos WHERE id=?", (mid,))])
    db.auditar(usuario_actual()["id"], None, "medico", f"Baja: {m['nombre']}")
    flash(f"Médico «{m['nombre']}» eliminado.", "ok")
    return redirect(url_for("medicos.medicos_lista"))
