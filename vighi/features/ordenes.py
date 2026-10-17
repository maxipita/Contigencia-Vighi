import io

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for

from vighi.core import almacen, db
from vighi.core.sesion import requiere_login, requiere_permiso, usuario_actual
from vighi.servicios.claves_api import clave_valida
from vighi.servicios.onedrive import estado_onedrive
from vighi.servicios.ordenes import (EXTENSIONES, PERMISOS_ORDENES, SQL_PENDIENTES, SQL_RECIENTES, asignar_orden, borrar_orden, grupo_de, lectores,
                                      procesar_archivo)
from vighi.servicios.protocolos import protocolo_o_404

bp = Blueprint("ordenes", __name__)


def volver(pid=None, ancla=""):
    destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else (
        url_for("protocolos.protocolo", pid=pid) if pid else url_for("ordenes.ordenes"))
    return redirect(destino.split("#")[0] + ancla)


@bp.route("/ordenes")
@requiere_login
def ordenes():
    return render_template("ordenes/ordenes.html", pendientes=db.q(SQL_PENDIENTES), recientes=db.q(SQL_RECIENTES), lectores=lectores(), onedrive=estado_onedrive())


@bp.route("/api/ordenes/subir", methods=["POST"])
@requiere_permiso(*PERMISOS_ORDENES)
def api_ordenes_subir():
    f = request.files.get("archivo")
    if not f or not f.filename:
        return jsonify(ok=False, error="No llegó ningún archivo."), 400
    try:
        paginas = procesar_archivo(f.filename, f.read(), usuario_actual()["id"])
    except ValueError as error:
        return jsonify(ok=False, archivo=f.filename, error=str(error)), 400
    except ImportError:
        return jsonify(ok=False, archivo=f.filename, error="Falta instalar Pillow para leer imágenes (python -m pip install -r requirements.txt)."), 500
    return jsonify(ok=True, archivo=f.filename, paginas=paginas)


@bp.route("/protocolo/<int:pid>/ordenes", methods=["POST"])
@requiere_permiso(*PERMISOS_ORDENES)
def ordenes_subir(pid):
    protocolo_o_404(pid)
    archivos = [f for f in request.files.getlist("archivos") if f and f.filename]
    if not archivos:
        flash("Elegí al menos un archivo.", "error")
        return volver(pid, "#ordenes")
    subidas = 0
    for f in archivos:
        try:
            subidas += sum(1 for r in procesar_archivo(f.filename, f.read(), usuario_actual()["id"], pid) if r["estado"] == "adjunta")
        except ValueError as error:
            flash(f"{f.filename}: {error}", "error")
    if subidas:
        flash(f"{subidas} página(s) de orden adjuntada(s).", "ok")
    return volver(pid, "#ordenes")


def enviar(oid, columna):
    r = db.uno(f"SELECT {columna} AS datos FROM ordenes WHERE id=?", (oid,)) or abort(404)
    respuesta = send_file(io.BytesIO(almacen.leer(r["datos"])), mimetype="image/jpeg", conditional=False)
    respuesta.headers["Cache-Control"] = "private, max-age=86400"
    return respuesta


@bp.route("/orden/<int:oid>")
@requiere_login
def orden_ver(oid):
    return enviar(oid, "imagen")


@bp.route("/orden/<int:oid>/mini")
@requiere_login
def orden_mini(oid):
    return enviar(oid, "miniatura")


@bp.route("/orden/<int:oid>/asignar", methods=["POST"])
@requiere_permiso(*PERMISOS_ORDENES)
def orden_asignar(oid):
    error = asignar_orden(oid, request.form.get("numero", ""), usuario_actual()["id"])
    flash(error or "Orden asignada al protocolo.", "error" if error else "ok")
    return redirect(url_for("ordenes.ordenes"))


@bp.route("/orden/<int:oid>/borrar", methods=["POST"])
@requiere_permiso(*PERMISOS_ORDENES)
def orden_borrar(oid):
    pid = borrar_orden(oid, usuario_actual()["id"])
    flash("Orden borrada.", "ok")
    return volver(pid, "#ordenes" if pid else "")


@bp.route("/api/ordenes/automatico", methods=["POST"])
def api_ordenes_automatico():
    cabecera = request.headers.get("Authorization", "")
    clave = clave_valida(cabecera[7:].strip() if cabecera.startswith("Bearer ") else "")
    if not clave:
        return jsonify(ok=False, error="Clave inválida o revocada."), 401
    f = request.files.get("archivo")
    if f and f.filename:
        nombre, contenido = f.filename, f.read()
    else:
        nombre = (request.args.get("nombre") or request.headers.get("X-Nombre-Archivo") or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        contenido = request.get_data()
    if not nombre or not contenido:
        return jsonify(ok=False, error="No llegó ningún archivo: mandalo como formulario (campo archivo) o como cuerpo del pedido con ?nombre=archivo.pdf."), 400
    if not nombre.lower().endswith(EXTENSIONES):
        return jsonify(ok=True, archivo=nombre, clave=clave["nombre"], ignorado=True, paginas=[])
    try:
        paginas = procesar_archivo(nombre, contenido, None, grupo=grupo_de(request.args.get("ruta") or request.headers.get("X-Ruta-Archivo")))
    except ValueError as error:
        return jsonify(ok=False, archivo=nombre, error=str(error)), 400
    return jsonify(ok=True, archivo=nombre, clave=clave["nombre"], paginas=paginas)
