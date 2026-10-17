from flask import Blueprint, abort, flash, request

from vighi.core import almacen, db
from vighi.core.sesion import requiere_login, requiere_permiso, usuario_actual
from vighi.servicios.consultas import listas
from vighi.servicios.imagenes import MAX_IMAGENES, PERMISOS_IMAGENES, enviar_imagen, procesar_imagen, volver_a_imagenes
from vighi.servicios.protocolos import protocolo_o_404

bp = Blueprint("imagenes", __name__)


@bp.route("/protocolo/<int:pid>/imagenes", methods=["POST"])
@requiere_permiso(*PERMISOS_IMAGENES)
def imagenes_subir(pid):
    protocolo_o_404(pid)
    archivos = [f for f in (request.files.getlist("imagenes") + request.files.getlist("archivos")) if f and f.filename]
    if not archivos:
        flash("Elegí al menos una imagen.", "error")
        return volver_a_imagenes(pid)
    cupo = MAX_IMAGENES - db.uno("SELECT COUNT(*) AS n FROM imagenes WHERE protocolo_id=?", (pid,))["n"]
    descripcion = request.form.get("descripcion", "").strip()[:200]
    tipo = request.form.get("tipo", "").strip()
    tipo = tipo if tipo in listas().get("tipos_imagen", []) else ""
    yo = usuario_actual()
    subidas, fallas = 0, []
    for f in archivos:
        if subidas >= cupo:
            fallas.append(f"{f.filename}: el protocolo ya tiene el máximo de {MAX_IMAGENES} imágenes")
            continue
        try:
            grande, mini = procesar_imagen(f.read())
        except ValueError as error:
            fallas.append(f"{f.filename}: {error}")
            continue
        except ImportError:
            flash("Falta instalar Pillow para subir imágenes (python -m pip install -r requirements.txt) y reiniciar el sistema.", "error")
            return volver_a_imagenes(pid)
        db.ex("INSERT INTO imagenes (protocolo_id, usuario_id, creado_en, nombre, descripcion, tipo, imagen, miniatura) VALUES (?,?,?,?,?,?,?,?)",
              (pid, yo["id"], db.ahora(), (f.filename or "")[:120], descripcion, tipo,
               almacen.guardar("imagenes", grande, "image/jpeg"), almacen.guardar("imagenes", mini, "image/jpeg")))
        subidas += 1
    if subidas:
        db.auditar(yo["id"], pid, "imagenes", f"{subidas} imagen(es)")
        flash(f"{subidas} imagen(es) subida(s).", "ok")
    for falla in fallas:
        flash(falla, "error")
    return volver_a_imagenes(pid)


@bp.route("/imagen/<int:iid>")
@requiere_login
def imagen_ver(iid):
    return enviar_imagen(iid, "imagen")


@bp.route("/imagen/<int:iid>/mini")
@requiere_login
def imagen_mini(iid):
    return enviar_imagen(iid, "miniatura")


@bp.route("/imagen/<int:iid>/borrar", methods=["POST"])
@requiere_permiso(*PERMISOS_IMAGENES)
def imagen_borrar(iid):
    r = db.uno("SELECT id, protocolo_id, nombre FROM imagenes WHERE id=?", (iid,)) or abort(404)
    objetos = db.uno("SELECT imagen, miniatura FROM imagenes WHERE id=?", (iid,)) if almacen.activo() else None
    db.ex("DELETE FROM imagenes WHERE id=?", (iid,))
    if objetos:
        almacen.borrar(objetos["imagen"])
        almacen.borrar(objetos["miniatura"])
    db.auditar(usuario_actual()["id"], r["protocolo_id"], "imagen_borrada", r["nombre"] or "")
    flash("Imagen borrada.", "ok")
    return volver_a_imagenes(r["protocolo_id"])
