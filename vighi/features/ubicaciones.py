from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.sesion import requiere_login, requiere_permiso, usuario_actual
from vighi.servicios import mensajeria, ubicaciones_csv
from vighi.servicios.ubicaciones import (CAMPOS_LUGAR, SQL_UBICACIONES, destinos_por_ubicacion, emails_de_informes, sql_protocolos_por_lugar, ubicacion_o_404)

bp = Blueprint("ubicaciones", __name__)


def contexto_ficha():
    return dict(tipos=mensajeria.TIPOS_ESTUDIO, malignidades=mensajeria.MALIGNIDADES, whatsapp_visible=mensajeria.whatsapp_visible, alcance_texto=mensajeria.alcance_texto)


@bp.route("/api/ubicaciones")
@requiere_login
def api_ubicaciones():
    r = jsonify([{"v": u["abreviatura"], "n": u["nombre"] or ""} for u in db.q("SELECT abreviatura, nombre FROM ubicaciones ORDER BY abreviatura")])
    r.headers["Cache-Control"] = "private, max-age=60"
    return r


@bp.route("/ubicaciones")
@requiere_login
def ubicaciones_lista():
    q = request.args.get("q", "").strip()
    db.precargar([(SQL_UBICACIONES, ()), (sql_protocolos_por_lugar("lugar_recoleccion"), ()), (sql_protocolos_por_lugar("lugar_entrega"), ())])
    filas = db.q(SQL_UBICACIONES)
    if q:
        palabras = db.clave_nombre(q).split()
        por_medico = {r["ubicacion_id"] for r in db.q(
            "SELECT DISTINCT m.ubicacion_id FROM ubicacion_medicos m JOIN medicos d ON d.id=m.medico_id WHERE "
            + " AND ".join(["d.nombre LIKE ?"] * len(palabras)), tuple(f"%{p}%" for p in palabras))} if palabras else set()
        filas = [u for u in filas if u["id"] in por_medico or all(p in db.clave_nombre(f"{u['abreviatura']} {u['nombre'] or ''} {u['direccion'] or ''} {u['contactos'] or ''}")
                                                                  for p in palabras)]
    destinos = destinos_por_ubicacion()
    filas = [dict(u, emails=", ".join(emails_de_informes(destinos.get(u["id"], [])))) for u in filas]
    return render_template("ubicaciones/ubicaciones.html", ubicaciones=filas, q=q,
                           recoleccion={r["lugar"]: r["n"] for r in db.q(sql_protocolos_por_lugar("lugar_recoleccion"))},
                           entrega={r["lugar"]: r["n"] for r in db.q(sql_protocolos_por_lugar("lugar_entrega"))})


def leer_ubicacion():
    return {k: request.form.get(k, "").strip() for k in ("abreviatura", "nombre", "direccion", "contactos")}


def error_ubicacion(d, uid=None):
    if not d["abreviatura"]:
        return "Falta la abreviatura de la ubicación."
    if db.uno("SELECT 1 FROM ubicaciones WHERE abreviatura=? AND id<>?", (d["abreviatura"], uid or 0)):
        return f"Ya existe una ubicación llamada «{d['abreviatura']}»."
    return None


@bp.route("/ubicaciones/nueva", methods=["GET", "POST"])
@requiere_permiso("ubicaciones")
def ubicacion_nueva():
    d = {}
    if request.method == "POST":
        d = leer_ubicacion()
        error = error_ubicacion(d)
        if error:
            flash(error, "error")
        else:
            uid = db.ex("INSERT INTO ubicaciones (abreviatura, nombre, direccion, contactos) VALUES (?,?,?,?)",
                        (d["abreviatura"], d["nombre"], d["direccion"], d["contactos"]))
            db.auditar(usuario_actual()["id"], None, "ubicacion", f"Alta: {d['abreviatura']}")
            flash("Ubicación creada. Ahora podés cargar a quién se envían los informes y asociarle médicos.", "ok")
            return redirect(url_for("ubicaciones.ubicacion", uid=uid))
    return render_template("ubicaciones/ubicacion.html", u=d, nueva=True, medicos=[], destinos=[], recoleccion=0, entrega=0, **contexto_ficha())


@bp.route("/ubicaciones/<int:uid>")
@requiere_login
def ubicacion(uid):
    u = ubicacion_o_404(uid)
    medicos = db.q("SELECT d.id, d.nombre FROM ubicacion_medicos m JOIN medicos d ON d.id=m.medico_id WHERE m.ubicacion_id=? ORDER BY d.nombre", (uid,))
    cuenta = lambda campo: db.uno(f"SELECT COUNT(*) AS n FROM protocolos WHERE borrador=0 AND {campo}=?", (u["abreviatura"],))["n"]
    destinos = db.q("SELECT id, canal, destino, informes, alcance FROM ubicacion_destinos WHERE ubicacion_id=? ORDER BY canal, destino", (uid,))
    return render_template("ubicaciones/ubicacion.html", u=u, nueva=False, medicos=medicos, destinos=destinos, recoleccion=cuenta("lugar_recoleccion"), entrega=cuenta("lugar_entrega"),
                           **contexto_ficha())


@bp.route("/ubicaciones/<int:uid>/editar", methods=["POST"])
@requiere_permiso("ubicaciones")
def ubicacion_editar(uid):
    u = ubicacion_o_404(uid)
    d = leer_ubicacion()
    error = error_ubicacion(d, uid)
    if error:
        flash(error, "error")
        return redirect(url_for("ubicaciones.ubicacion", uid=uid))
    sentencias = [("UPDATE ubicaciones SET abreviatura=?, nombre=?, direccion=?, contactos=? WHERE id=?", (d["abreviatura"], d["nombre"], d["direccion"], d["contactos"], uid))]
    if d["abreviatura"] != u["abreviatura"]:
        sentencias += [(f"UPDATE protocolos SET {campo}=? WHERE {campo}=?", (d["abreviatura"], u["abreviatura"])) for campo, _ in CAMPOS_LUGAR]
    db.lote_ex(sentencias)
    detalle = f"{u['abreviatura']} → {d['abreviatura']}" if d["abreviatura"] != u["abreviatura"] else d["abreviatura"]
    db.auditar(usuario_actual()["id"], None, "ubicacion", f"Edición: {detalle}")
    flash("Ubicación actualizada." + (" Se actualizó la abreviatura en sus protocolos." if d["abreviatura"] != u["abreviatura"] else ""), "ok")
    return redirect(url_for("ubicaciones.ubicacion", uid=uid))


@bp.route("/ubicaciones/<int:uid>/eliminar", methods=["POST"])
@requiere_permiso("ubicaciones")
def ubicacion_eliminar(uid):
    u = ubicacion_o_404(uid)
    if db.uno("SELECT 1 FROM protocolos WHERE lugar_recoleccion=? OR lugar_entrega=? LIMIT 1", (u["abreviatura"], u["abreviatura"])):
        flash("No se puede eliminar: hay protocolos con esta ubicación.", "error")
        return redirect(url_for("ubicaciones.ubicacion", uid=uid))
    db.lote_ex([("DELETE FROM ubicacion_medicos WHERE ubicacion_id=?", (uid,)), ("DELETE FROM ubicacion_destinos WHERE ubicacion_id=?", (uid,)), ("DELETE FROM ubicaciones WHERE id=?", (uid,))])
    db.auditar(usuario_actual()["id"], None, "ubicacion", f"Baja: {u['abreviatura']}")
    flash(f"Ubicación «{u['abreviatura']}» eliminada.", "ok")
    return redirect(url_for("ubicaciones.ubicaciones_lista"))


def alcance_del_formulario():
    return mensajeria.alcance_valido(request.form.getlist("alcance"))


@bp.route("/ubicaciones/<int:uid>/destino", methods=["POST"])
@requiere_permiso("ubicaciones")
def ubicacion_destino_agregar(uid):
    u = ubicacion_o_404(uid)
    volver = redirect(url_for("ubicaciones.ubicacion", uid=uid) + "#envio")
    canal = "whatsapp" if request.form.get("canal") == "whatsapp" else "email"
    bruto = request.form.get("destino", "").strip()
    if canal == "email":
        destino = bruto.lower()
        if not mensajeria.email_valido(destino):
            flash("El e-mail no es válido.", "error")
            return volver
    else:
        destino = mensajeria.whatsapp_numero(bruto)
        if not destino:
            flash("El número no es válido: escribilo con el código de área, por ejemplo 11 5015 1099.", "error")
            return volver
    if db.uno("SELECT 1 FROM ubicacion_destinos WHERE ubicacion_id=? AND canal=? AND destino=?", (uid, canal, destino)):
        flash("Ese destino ya está cargado en la ubicación.", "error")
        return volver
    informes = 1 if request.form.get("informes") == "1" else 0
    db.ex("INSERT INTO ubicacion_destinos (ubicacion_id, canal, destino, informes, alcance) VALUES (?,?,?,?,?)", (uid, canal, destino, informes, alcance_del_formulario()))
    db.auditar(usuario_actual()["id"], None, "ubicacion", f"{u['abreviatura']}: se agregó {destino} ({'WhatsApp' if canal == 'whatsapp' else 'e-mail'})")
    flash("Destino agregado.", "ok")
    return volver


@bp.route("/ubicaciones/<int:uid>/destino/<int:did>", methods=["POST"])
@requiere_permiso("ubicaciones")
def ubicacion_destino_editar(uid, did):
    u = ubicacion_o_404(uid)
    d = db.uno("SELECT * FROM ubicacion_destinos WHERE id=? AND ubicacion_id=?", (did, uid)) or abort(404)
    if request.form.get("accion") == "borrar":
        db.ex("DELETE FROM ubicacion_destinos WHERE id=?", (did,))
        db.auditar(usuario_actual()["id"], None, "ubicacion", f"{u['abreviatura']}: se quitó {d['destino']}")
        flash("Destino quitado.", "ok")
    else:
        informes = 1 if request.form.get("informes") == "1" else 0
        alcance = alcance_del_formulario()
        db.ex("UPDATE ubicacion_destinos SET informes=?, alcance=? WHERE id=?", (informes, alcance, did))
        db.auditar(usuario_actual()["id"], None, "ubicacion",
                   f"{u['abreviatura']}: {d['destino']} → {'recibe informes' if informes else 'no recibe informes'} · {mensajeria.alcance_texto(alcance)}")
        flash("Destino actualizado.", "ok")
    return redirect(url_for("ubicaciones.ubicacion", uid=uid) + "#envio")


@bp.route("/ubicaciones/<int:uid>/medico", methods=["POST"])
@requiere_permiso("ubicaciones")
def ubicacion_medico_agregar(uid):
    u = ubicacion_o_404(uid)
    nombre = request.form.get("medico", "").strip()
    clave = db.clave_nombre(nombre)
    hallados = [m for m in db.q("SELECT id, nombre FROM medicos WHERE nombre=?", (nombre,))] if nombre else []
    if not hallados and clave:
        hallados = [m for m in db.q("SELECT id, nombre FROM medicos ORDER BY id") if db.clave_nombre(m["nombre"]) == clave]
    if not hallados:
        flash("No encontré ese médico: elegilo de la lista que se despliega al escribir.", "error")
    elif db.uno("SELECT 1 FROM ubicacion_medicos WHERE ubicacion_id=? AND medico_id=?", (uid, hallados[0]["id"])):
        flash(f"{hallados[0]['nombre']} ya está asociado a esta ubicación.", "error")
    else:
        db.ex("INSERT INTO ubicacion_medicos (ubicacion_id, medico_id) VALUES (?,?)", (uid, hallados[0]["id"]))
        db.auditar(usuario_actual()["id"], None, "ubicacion", f"{u['abreviatura']}: se asoció a {hallados[0]['nombre']}")
        flash(f"{hallados[0]['nombre']} asociado a la ubicación.", "ok")
    return redirect(url_for("ubicaciones.ubicacion", uid=uid) + "#medicos")


@bp.route("/ubicaciones/<int:uid>/medicos/quitar", methods=["POST"])
@requiere_permiso("ubicaciones")
def ubicacion_medico_quitar(uid):
    u = ubicacion_o_404(uid)
    ids = [int(i) for i in request.form.getlist("medico") if i.isdigit()]
    if not ids:
        flash("Marcá los médicos que querés quitar.", "error")
    else:
        db.lote_ex([("DELETE FROM ubicacion_medicos WHERE ubicacion_id=? AND medico_id=?", (uid, i)) for i in ids])
        db.auditar(usuario_actual()["id"], None, "ubicacion", f"{u['abreviatura']}: se quitaron {len(ids)} médico(s)")
        flash(f"Se quitaron {len(ids)} médico(s) de la ubicación.", "ok")
    return redirect(url_for("ubicaciones.ubicacion", uid=uid) + "#medicos")


@bp.route("/ubicaciones/importar", methods=["POST"])
@requiere_permiso("ubicaciones")
def ubicaciones_importar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Elegí el archivo CSV de ubicaciones.", "error")
        return redirect(url_for("ubicaciones.ubicaciones_lista"))
    try:
        filas = ubicaciones_csv.leer_csv(archivo.read())
    except ubicaciones_csv.ErrorArchivo as e:
        flash(str(e), "error")
        return redirect(url_for("ubicaciones.ubicaciones_lista"))
    if not filas:
        flash("El archivo no tiene ubicaciones.", "error")
        return redirect(url_for("ubicaciones.ubicaciones_lista"))
    r = db.ubicaciones_importar(filas)
    db.auditar(usuario_actual()["id"], None, "ubicaciones_importar", f"{r['nuevas']} nuevas, {r['actualizadas']} actualizadas, {r['vinculos']} médicos asociados")
    flash(f"Importación lista: {r['nuevas']} ubicaciones nuevas, {r['actualizadas']} actualizadas, {r['vinculos']} médicos asociados"
          + (f", {r['medicos_nuevos']} médicos agregados a la lista." if r["medicos_nuevos"] else "."), "ok")
    return redirect(url_for("ubicaciones.ubicaciones_lista"))
