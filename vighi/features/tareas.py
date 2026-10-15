from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.sesion import requiere_admin, requiere_login, usuario_actual
from vighi.dominio.estudios import SECTORES
from vighi.servicios.protocolos import protocolo_o_404
from vighi.servicios.tareas import CIERRES, ESTADOS_LISTA, PRIORIDADES, URGENCIAS, crear_tarea, listar_tareas, responsable_valido, tipos_de_tarea, usuarios_con_sectores, usuarios_para_tareas, validar_tarea

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


def volver_a_tareas(pid):
    destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for("protocolos.protocolo", pid=pid)
    return redirect(destino.split("#")[0] + "#tareas")


@bp.route("/protocolo/<int:pid>/tarea/nueva", methods=["GET", "POST"])
@requiere_login
def tarea_nueva(pid):
    p = protocolo_o_404(pid)
    form = request.form if request.method == "POST" else {"urgencia": "regular", "prioridad": "media"}
    if request.method == "POST":
        t, descripcion, resp, error = validar_tarea(form)
        if error:
            flash(error, "error")
        else:
            crear_tarea(pid, t, descripcion, form["urgencia"], form["prioridad"], resp, usuario_actual()["id"])
            flash(f"Tarea «{t['titulo']}» creada.", "ok")
            return redirect(url_for("protocolos.protocolo", pid=pid) + "#tareas")
    tipos = tipos_de_tarea()
    return render_template("tareas/nueva.html", p=p, form=form, tipos=tipos, usuarios=usuarios_con_sectores(), sectores=SECTORES, urgencias=URGENCIAS, prioridades=PRIORIDADES)


def tarea_o_404(tid):
    return db.uno("SELECT * FROM tareas WHERE id=?", (tid,)) or abort(404)


@bp.route("/tarea/<int:tid>/responsable", methods=["POST"])
@requiere_login
def tarea_responsable(tid):
    t = tarea_o_404(tid)
    resp, error = responsable_valido(request.form.get("responsable_id", ""))
    if error:
        flash(error, "error")
    elif t["estado"] != "abierta":
        flash("La tarea está cerrada: reabrila para cambiar el responsable.", "error")
    elif resp != t["responsable_id"]:
        db.ex("UPDATE tareas SET responsable_id=? WHERE id=?", (resp, tid))
        quien = db.uno("SELECT iniciales FROM usuarios WHERE id=?", (resp,)) if resp else None
        db.auditar(usuario_actual()["id"], t["protocolo_id"], "tarea_responsable", f"{t['titulo']} → {quien['iniciales'] if quien else 'sin asignar'}")
        flash("Responsable actualizado.", "ok")
    return volver_a_tareas(t["protocolo_id"])


@bp.route("/tarea/<int:tid>/cerrar", methods=["POST"])
@requiere_login
def tarea_cerrar(tid):
    t = tarea_o_404(tid)
    if t["estado"] == "abierta":
        yo = usuario_actual()["id"]
        db.ex("UPDATE tareas SET estado='cerrada', cerrada_por=?, cerrada_en=?, cierre_detalle=? WHERE id=?", (yo, db.ahora(), "a mano", tid))
        db.auditar(yo, t["protocolo_id"], "tarea_cerrada", f"{t['titulo']} (a mano)")
        flash(f"Tarea «{t['titulo']}» cerrada.", "ok")
    return volver_a_tareas(t["protocolo_id"])


@bp.route("/tarea/<int:tid>/reabrir", methods=["POST"])
@requiere_login
def tarea_reabrir(tid):
    t = tarea_o_404(tid)
    if t["estado"] == "cerrada":
        db.ex("UPDATE tareas SET estado='abierta', cerrada_por=NULL, cerrada_en=NULL, cierre_detalle=NULL WHERE id=?", (tid,))
        db.auditar(usuario_actual()["id"], t["protocolo_id"], "tarea_reabierta", t["titulo"])
        flash(f"Tarea «{t['titulo']}» reabierta.", "ok")
    return volver_a_tareas(t["protocolo_id"])


@bp.route("/tareas")
@requiere_login
def mis_tareas():
    yo = usuario_actual()
    responsable = request.args.get("resp") or str(yo["id"])
    if responsable not in ("todos", "sin") and not responsable.isdigit():
        responsable = str(yo["id"])
    estado = request.args.get("estado") if request.args.get("estado") in ESTADOS_LISTA else "abiertas"
    return render_template("tareas/lista.html", tareas=listar_tareas(responsable, estado), responsable=responsable, estado=estado, estados=ESTADOS_LISTA,
                           usuarios_tarea=usuarios_con_sectores())
