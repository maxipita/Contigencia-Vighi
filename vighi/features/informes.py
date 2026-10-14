import io

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from vighi.core import almacen, db
from vighi.core.config import SIN_INFORMES
from vighi.core.fechas import fecha_hora
from vighi.core.opcionales import informes
from vighi.core.sesion import requiere_permiso, requiere_permiso_o_403, usuario_actual
from vighi.servicios.fichas import ficha, informe_emitido, informe_vigente
from vighi.servicios.protocolos import protocolo_o_404

bp = Blueprint("informes", __name__)


@bp.route("/estudio/<int:eid>/informe")
@requiere_permiso("informe")
def informe_de_estudio(eid):
    return redirect(url_for("informes.informe", pid=ficha(eid)[0]["protocolo_id"]))


@bp.route("/protocolo/<int:pid>/informe")
@requiere_permiso("informe")
def informe(pid):
    p = protocolo_o_404(pid)
    if informes is None:
        flash(SIN_INFORMES, "error")
        return redirect(url_for("protocolos.protocolo", pid=pid))
    try:
        d = informes.armar(pid)
    except informes.InformeError as err:
        flash(str(err), "error")
        return redirect(url_for("protocolos.protocolo", pid=pid))
    emitido = informe_emitido(pid)
    return render_template("informes/informe.html", d=d, p=p, emitido=emitido, informe_vigente=informe_vigente(pid, emitido))


@bp.route("/protocolo/<int:pid>/informe.pdf", methods=["POST"])
@requiere_permiso("informe")
def informe_pdf(pid):
    protocolo_o_404(pid)
    if informes is None:
        flash(SIN_INFORMES, "error")
        return redirect(url_for("protocolos.protocolo", pid=pid))
    yo = usuario_actual()
    try:
        d = informes.armar(pid, request.form.get("comentario", ""))
    except informes.InformeError as err:
        flash(str(err), "error")
        return redirect(url_for("protocolos.protocolo", pid=pid))
    pdf = informes.generar_pdf(d)
    previo = db.uno("SELECT i.id, i.version, i.creado_en, u.iniciales FROM informes_emitidos i LEFT JOIN usuarios u ON u.id=i.usuario_id WHERE i.protocolo_id=?", (pid,))
    viejo = db.uno("SELECT pdf FROM informes_emitidos WHERE id=?", (previo["id"],)) if previo and almacen.activo() else None
    campos = (yo["id"], d["medico"]["id"], db.ahora(), d["comentario"], informes.nombre_archivo(d), almacen.guardar("informes", pdf, "application/pdf"),
              ",".join(str(i) for s in d["estudios"] for i in s["eids"]))
    try:
        if previo:
            db.ex("UPDATE informes_emitidos SET usuario_id=?, firmante_id=?, creado_en=?, comentario=?, archivo=?, pdf=?, estudios=?, version=version+1 WHERE id=?",
                  campos + (previo["id"],))
            iid, version = previo["id"], previo["version"] + 1
            if viejo:
                almacen.borrar(viejo["pdf"])
        else:
            iid, version = db.ex("INSERT INTO informes_emitidos (usuario_id, firmante_id, creado_en, comentario, archivo, pdf, estudios, protocolo_id, version) "
                                 "VALUES (?,?,?,?,?,?,?,?,1)", campos + (pid,)), 1
    except db.IntegrityError:
        flash("Alguien más generó el informe al mismo tiempo, revisalo y generalo de nuevo si hace falta.", "error")
        return redirect(url_for("informes.informe", pid=pid))
    reemplaza = f" · reemplaza el de {previo['iniciales'] or '—'} del {fecha_hora(previo['creado_en'])}" if previo else ""
    db.auditar(yo["id"], pid, "informe_pdf",
               f"{d['titulo'].title()} generado por {yo['iniciales']} · firma de {d['medico']['nombre']}" + (f" (emisión {version}{reemplaza})" if previo else ""))
    return redirect(url_for("informes.informe_ver", iid=iid))


@bp.route("/informe/<int:iid>.pdf")
@requiere_permiso("informe")
def informe_ver(iid):
    r = db.uno("SELECT protocolo_id, estudios, archivo, pdf FROM informes_emitidos WHERE id=?", (iid,))
    if not r:
        abort(404)
    if not informe_vigente(r["protocolo_id"], r):
        flash("Ese informe ya no se puede entregar: el protocolo tiene estudios pendientes o cambió desde que se generó. Hay que generarlo de nuevo.", "error")
        return redirect(url_for("protocolos.protocolo", pid=r["protocolo_id"]))
    return send_file(io.BytesIO(almacen.leer(r["pdf"])), mimetype="application/pdf", download_name=r["archivo"], max_age=0)


@bp.route("/usuarios/<int:uid>/firma")
@requiere_permiso_o_403("usuarios")
def usuario_firma(uid):
    f = db.uno("SELECT imagen FROM firmas WHERE usuario_id=?", (uid,))
    if not f:
        abort(404)
    return send_file(io.BytesIO(almacen.leer(f["imagen"])), mimetype="image/png", max_age=0)
