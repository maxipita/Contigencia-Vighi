from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from vighi.core import db
from vighi.core.sesion import es_local, requiere_login, usuario_actual
from vighi.dominio.estudios import SECTORES

bp = Blueprint("auth", __name__)


@bp.route("/configurar", methods=["GET", "POST"])
def configurar():
    if db.uno("SELECT 1 FROM usuarios WHERE admin=1 AND clave_hash IS NOT NULL"):
        return redirect(url_for("auth.login"))
    if not es_local():
        abort(403, "La configuración inicial solo se hace desde la PC servidor.")
    if request.method == "POST":
        ini = request.form["iniciales"].strip().upper()
        clave = request.form["clave"]
        if len(clave) < 8 or clave != request.form["clave2"]:
            flash("La clave debe tener al menos 8 caracteres y coincidir en los dos campos.", "error")
        elif not ini:
            flash("Faltan las iniciales.", "error")
        else:
            existente = db.uno("SELECT id FROM usuarios WHERE iniciales=?", (ini,))
            h = generate_password_hash(clave)
            if existente:
                db.ex("UPDATE usuarios SET admin=1, activo=1, clave_hash=?, debe_cambiar_clave=0, nombre=? WHERE id=?",
                      (h, request.form["nombre"].strip() or ini, existente["id"]))
            else:
                db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, clave_hash, debe_cambiar_clave) "
                      "VALUES (?,?,?,1,?,0)", (ini, request.form["nombre"].strip() or ini, ",".join(SECTORES), h))
            flash("Administrador creado. Ya podés ingresar.", "ok")
            return redirect(url_for("auth.login"))
    return render_template("auth/configurar.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not db.uno("SELECT 1 FROM usuarios WHERE admin=1 AND clave_hash IS NOT NULL"):
        return redirect(url_for("auth.configurar"))
    if request.method == "POST":
        u = db.uno("SELECT * FROM usuarios WHERE iniciales=? AND activo=1", (request.form["iniciales"].strip().upper(),))
        if u and u["clave_hash"] and check_password_hash(u["clave_hash"], request.form["clave"]):
            session.clear()
            session["uid"] = u["id"]
            db.auditar(u["id"], None, "login")
            destino = request.args.get("next", "")
            return redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("tablero.tablero"))
        flash("Iniciales o clave incorrectas (o el usuario todavía no tiene clave: pedísela al administrador).", "error")
    return render_template("auth/login.html")


@bp.route("/usuarios/<int:uid>/ver-como", methods=["POST"])
@requiere_login
def ver_como(uid):
    real_id = session.get("real_uid") or session.get("uid")
    real = db.uno("SELECT id, iniciales FROM usuarios WHERE id=? AND activo=1 AND admin=1", (real_id,))
    if not real:
        abort(403)
    objetivo = db.uno("SELECT id, iniciales, nombre FROM usuarios WHERE id=? AND activo=1", (uid,))
    if not objetivo:
        flash("El usuario no existe o está inactivo.", "error")
        return redirect(url_for("usuarios.usuarios"))
    if objetivo["id"] == real["id"]:
        session.pop("real_uid", None)
        session["uid"] = real["id"]
        return redirect(url_for("usuarios.usuarios"))
    session["real_uid"] = real["id"]
    session["uid"] = objetivo["id"]
    db.auditar(real["id"], None, "ver_como", f"{objetivo['iniciales']}")
    return redirect(url_for("tablero.tablero"))


@bp.route("/dejar-de-ver-como", methods=["POST"])
@requiere_login
def dejar_de_ver_como():
    real_id = session.pop("real_uid", None)
    if real_id:
        session["uid"] = real_id
        flash("Volviste a tu usuario.", "ok")
        return redirect(url_for("usuarios.usuarios"))
    return redirect(url_for("tablero.tablero"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/clave", methods=["GET", "POST"])
@requiere_login
def cambiar_clave():
    yo = usuario_actual()
    if request.method == "POST":
        nueva = request.form["nueva"]
        if not check_password_hash(yo["clave_hash"], request.form["actual"]):
            flash("La clave actual no es correcta.", "error")
        elif len(nueva) < 8 or nueva != request.form["nueva2"]:
            flash("La nueva clave debe tener al menos 8 caracteres y coincidir en los dos campos.", "error")
        else:
            db.ex("UPDATE usuarios SET clave_hash=?, debe_cambiar_clave=0 WHERE id=?", (generate_password_hash(nueva), yo["id"]))
            db.auditar(yo["id"], None, "cambio_clave")
            flash("Clave actualizada.", "ok")
            return redirect(url_for("tablero.tablero"))
    return render_template("auth/clave.html")
