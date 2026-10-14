from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from vighi.core import almacen, db, permisos
from vighi.core.config import SIN_INFORMES
from vighi.core.opcionales import informes
from vighi.core.sesion import requiere_admin, requiere_permiso, usuario_actual
from vighi.dominio.estudios import SECTORES
from vighi.servicios.usuarios import perfiles_con_permisos

bp = Blueprint("usuarios", __name__)


@bp.route("/usuarios")
@requiere_admin
def usuarios():
    filas = db.q("""SELECT u.*, p.nombre AS perfil FROM usuarios u LEFT JOIN perfiles p ON p.id=u.perfil_id
                    ORDER BY u.activo DESC, u.iniciales""")
    return render_template("usuarios/usuarios.html", usuarios=filas)


@bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@bp.route("/usuarios/<int:uid>", methods=["GET", "POST"])
@requiere_admin
def usuario(uid=None):
    yo = usuario_actual()
    u = db.uno("SELECT * FROM usuarios WHERE id=?", (uid,)) if uid else None
    if request.method == "POST":
        ini = request.form["iniciales"].strip().upper()
        sectores = ",".join(s for s in SECTORES if request.form.get("s_" + s))
        perfil_id = int(request.form["perfil_id"]) if request.form.get("perfil_id", "").isdigit() else None
        ajuste = {k: request.form.get("p_" + k, "") for k in permisos.PERMISOS}
        titulo = request.form.get("titulo", "") if request.form.get("titulo") in ("Dr.", "Dra.") else ""
        mn, mp = request.form.get("mn", "").strip()[:20], request.form.get("mp", "").strip()[:20]
        firma_png, firma_error = None, None
        archivo = request.files.get("firma")
        if archivo and archivo.filename and informes is None:
            firma_error = SIN_INFORMES
        elif archivo and archivo.filename:
            try:
                firma_png = informes.procesar_firma(archivo.read())
            except ValueError as err:
                firma_error = str(err)
        vals = (ini, request.form.get("nombre", "").strip() or ini, sectores,
                1 if request.form.get("admin") else 0, 1 if request.form.get("activo") else 0, perfil_id,
                permisos.texto({k for k, v in ajuste.items() if v == "mas"}),
                permisos.texto({k for k, v in ajuste.items() if v == "menos"}))
        dup = db.uno("SELECT id FROM usuarios WHERE iniciales=? AND id<>?", (ini, uid or 0))
        clave = request.form.get("clave", "")
        if not ini or dup:
            flash("Iniciales vacías o ya usadas por otra persona.", "error")
        elif clave and len(clave) < 8:
            flash("La clave temporal debe tener al menos 8 caracteres.", "error")
        elif perfil_id and not db.uno("SELECT 1 FROM perfiles WHERE id=?", (perfil_id,)):
            flash("El perfil elegido no existe.", "error")
        elif uid == yo["id"] and not (vals[3] and vals[4]):
            flash("No podés quitarte el rol de administrador ni desactivarte a vos mismo.", "error")
        elif firma_error:
            flash(f"Firma: {firma_error}", "error")
        else:
            if u:
                db.ex("UPDATE usuarios SET iniciales=?, nombre=?, sectores=?, admin=?, activo=?, perfil_id=?, permisos_mas=?, "
                      "permisos_menos=? WHERE id=?", vals + (uid,))
            else:
                uid = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, perfil_id, permisos_mas, "
                            "permisos_menos) VALUES (?,?,?,?,?,?,?,?)", vals)
            if clave:
                db.ex("UPDATE usuarios SET clave_hash=?, debe_cambiar_clave=1 WHERE id=?", (generate_password_hash(clave), uid))
            db.ex("UPDATE usuarios SET titulo=?, mn=?, mp=? WHERE id=?", (titulo, mn, mp, uid))
            vieja_firma = db.uno("SELECT imagen FROM firmas WHERE usuario_id=?", (uid,)) if almacen.activo() and (firma_png or request.form.get("quitar_firma")) else None
            if firma_png:
                db.ex("DELETE FROM firmas WHERE usuario_id=?", (uid,))
                db.ex("INSERT INTO firmas (usuario_id, imagen, actualizada_en) VALUES (?,?,?)", (uid, almacen.guardar("firmas", firma_png, "image/png"), db.ahora()))
                if vieja_firma:
                    almacen.borrar(vieja_firma["imagen"])
                db.auditar(yo["id"], None, "firma", f"{ini}: firma cargada")
            elif request.form.get("quitar_firma"):
                db.ex("DELETE FROM firmas WHERE usuario_id=?", (uid,))
                if vieja_firma:
                    almacen.borrar(vieja_firma["imagen"])
                db.auditar(yo["id"], None, "firma", f"{ini}: firma quitada")
            detalle = (f"perfil {db.uno('SELECT nombre FROM perfiles WHERE id=?', (perfil_id,))['nombre'] if perfil_id else '—'}"
                       + (f", +{vals[6]}" if vals[6] else "") + (f", -{vals[7]}" if vals[7] else ""))
            db.auditar(yo["id"], None, "usuario", f"{ini}: {detalle}{' (clave temporal)' if clave else ''}")
            flash(f"Usuario {ini} guardado." + (" Al ingresar va a tener que cambiar la clave." if clave else ""), "ok")
            return redirect(url_for("usuarios.usuarios"))
        u = {**(dict(u) if u else {}), "iniciales": ini, "nombre": vals[1], "sectores": sectores, "admin": vals[3],
             "activo": vals[4], "perfil_id": perfil_id, "permisos_mas": vals[6], "permisos_menos": vals[7],
             "clave_hash": u["clave_hash"] if u else None, "titulo": titulo, "mn": mn, "mp": mp}
    lista_perfiles = perfiles_con_permisos()
    tiene_firma = bool(uid and db.uno("SELECT 1 FROM firmas WHERE usuario_id=?", (uid,)))
    return render_template("usuarios/usuario.html", u=u, perfiles=lista_perfiles, tiene_firma=tiene_firma, PERMISOS=permisos.PERMISOS,
                           GRUPOS=permisos.GRUPOS, lista_permisos=permisos.lista,
                           mapa_perfiles={p["id"]: sorted(p["set"]) for p in lista_perfiles})


@bp.route("/perfiles")
@requiere_admin
def perfiles():
    return render_template("usuarios/perfiles.html", perfiles=perfiles_con_permisos(), PERMISOS=permisos.PERMISOS,
                           GRUPOS=permisos.GRUPOS)


@bp.route("/perfiles/nuevo", methods=["GET", "POST"])
@bp.route("/perfiles/<int:pid>", methods=["GET", "POST"])
@requiere_admin
def perfil(pid=None):
    yo = usuario_actual()
    p = db.uno("SELECT * FROM perfiles WHERE id=?", (pid,)) if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        if request.form.get("eliminar"):
            if db.uno("SELECT 1 FROM usuarios WHERE perfil_id=?", (pid,)):
                flash("No se puede eliminar: hay usuarios con este perfil. Cambiales el perfil primero.", "error")
                return redirect(url_for("usuarios.perfil", pid=pid))
            db.ex("DELETE FROM perfiles WHERE id=?", (pid,))
            db.auditar(yo["id"], None, "eliminar_perfil", p["nombre"])
            flash(f"Perfil {p['nombre']} eliminado.", "ok")
            return redirect(url_for("usuarios.perfiles"))
        nombre = request.form.get("nombre", "").strip()
        elegidos = permisos.texto({k for k in permisos.PERMISOS if request.form.get("p_" + k)})
        if not nombre or db.uno("SELECT 1 FROM perfiles WHERE nombre=? AND id<>?", (nombre, pid or 0)):
            flash("El nombre está vacío o ya lo usa otro perfil.", "error")
        else:
            if p:
                db.ex("UPDATE perfiles SET nombre=?, permisos=? WHERE id=?", (nombre, elegidos, pid))
            else:
                pid = db.ex("INSERT INTO perfiles (nombre, permisos) VALUES (?,?)", (nombre, elegidos))
            db.auditar(yo["id"], None, "perfil", f"{nombre}: {elegidos or 'sin permisos'}")
            flash(f"Perfil {nombre} guardado.", "ok")
            return redirect(url_for("usuarios.perfiles"))
        p = {**(dict(p) if p else {}), "nombre": nombre, "permisos": elegidos}
    usuarios_del = db.q("SELECT iniciales, nombre, activo FROM usuarios WHERE perfil_id=? ORDER BY iniciales", (pid,)) if pid else []
    return render_template("usuarios/perfil.html", p=p, marcados=permisos.lista(p["permisos"] if p else ""), usuarios=usuarios_del,
                           PERMISOS=permisos.PERMISOS, GRUPOS=permisos.GRUPOS)


@bp.route("/feriados", methods=["GET", "POST"])
@requiere_permiso("feriados")
def feriados():
    yo = usuario_actual()
    if request.method == "POST":
        f, desc = request.form.get("fecha", ""), request.form.get("descripcion", "").strip()
        if request.form.get("borrar"):
            db.ex("DELETE FROM feriados WHERE fecha=?", (request.form["borrar"],))
            db.auditar(yo["id"], None, "feriado_borrado", request.form["borrar"])
        elif len(f) == 10:
            db.ex("DELETE FROM feriados WHERE fecha=?", (f,))
            db.ex("INSERT INTO feriados VALUES (?,?)", (f, desc))
            db.auditar(yo["id"], None, "feriado", f"{f} {desc}")
            flash("Feriado guardado.", "ok")
        return redirect(url_for("usuarios.feriados"))
    return render_template("usuarios/feriados.html", feriados=db.q("SELECT * FROM feriados ORDER BY fecha"))
