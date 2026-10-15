from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.sesion import requiere_admin, usuario_actual
from vighi.servicios.tareas import CIERRES, tipos_de_tarea, usuarios_para_tareas

bp = Blueprint("tareas", __name__)


@bp.route("/tareas/tipos")
@requiere_admin
def tipos_tarea():
    return render_template("tareas/tipos.html", tipos=tipos_de_tarea())


@bp.route("/tareas/tipos/nuevo", methods=["GET", "POST"])
@bp.route("/tareas/tipos/<int:tid>", methods=["GET", "POST"])
@requiere_admin
def tipo_tarea(tid=None):
    t = db.uno("SELECT * FROM tarea_tipos WHERE id=?", (tid,)) if tid else None
    if tid and not t:
        abort(404)
    usuarios = usuarios_para_tareas()
    if request.method == "POST":
        titulo = " ".join(request.form.get("titulo", "").split())[:80]
        resp = request.form.get("responsable_id", "")
        cierre = request.form.get("cierre", "")
        error = None
        if not titulo:
            error = "Falta el título de la tarea."
        elif db.uno("SELECT 1 FROM tarea_tipos WHERE LOWER(titulo)=LOWER(?) AND id<>?", (titulo, tid or 0)):
            error = f"Ya existe una tarea llamada «{titulo}»."
        elif resp and resp not in {str(u["id"]) for u in usuarios}:
            error = "Elegí un responsable de la lista."
        elif cierre and cierre not in CIERRES:
            error = "Elegí un cierre automático de la lista."
        if error:
            flash(error, "error")
            t = {**(dict(t) if t else {}), "titulo": titulo, "responsable_id": int(resp) if resp.isdigit() else None, "cierre": cierre}
        else:
            valores = (titulo, int(resp) if resp else None, cierre or None)
            if t:
                db.ex("UPDATE tarea_tipos SET titulo=?, responsable_id=?, cierre=? WHERE id=?", valores + (tid,))
            else:
                db.ex("INSERT INTO tarea_tipos (titulo, responsable_id, cierre) VALUES (?,?,?)", valores)
            quien = next((u["iniciales"] for u in usuarios if str(u["id"]) == resp), "sin responsable")
            db.auditar(usuario_actual()["id"], None, "tarea_tipo", f"{titulo}: {quien}, cierre {CIERRES.get(cierre, 'manual')}")
            flash(f"Tarea «{titulo}» guardada.", "ok")
            return redirect(url_for("tareas.tipos_tarea"))
    return render_template("tareas/tipo.html", t=t, usuarios=usuarios, cierres=CIERRES)
