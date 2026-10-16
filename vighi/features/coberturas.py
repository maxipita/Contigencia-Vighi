from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.sesion import requiere_permiso, usuario_actual
from vighi.dominio import facturacion
from vighi.servicios import coberturas as srv

bp = Blueprint("coberturas", __name__)


@bp.route("/coberturas")
@requiere_permiso("facturacion")
def coberturas():
    q = request.args.get("q", "").strip().lower()
    filas = [d for d in srv.datos_de_coberturas() if not q or q in d["nombre"].lower()]
    return render_template("coberturas/coberturas.html", filas=filas, q=q, tipos_iva=facturacion.TIPOS_IVA)


@bp.route("/coberturas/nueva", methods=["POST"])
@requiere_permiso("facturacion")
def cobertura_nueva():
    nombre = srv.limpiar_cobertura(request.form.get("nombre"))
    error = srv.error_cobertura(nombre)
    if error:
        flash(error, "error")
        return redirect(url_for("coberturas.coberturas"))
    srv.crear_cobertura(nombre)
    db.auditar(usuario_actual()["id"], None, "cobertura", f"Alta: {nombre}")
    flash(f"Cobertura «{nombre}» creada: completá su IVA, plazo de cobro y tarifa.", "ok")
    return redirect(url_for("coberturas.cobertura", c=nombre))


@bp.route("/cobertura", methods=["GET", "POST"])
@requiere_permiso("facturacion")
def cobertura():
    yo = usuario_actual()
    nombre = request.values.get("c", "")
    if nombre not in srv.lista_coberturas():
        abort(404)
    destino = url_for("coberturas.cobertura", c=nombre)
    destino_planes = url_for("coberturas.cobertura", c=nombre, pestana="planes")
    if request.method == "POST":
        accion = request.form.get("accion", "")
        if accion == "guardar":
            dias_texto = request.form.get("dias", "").strip()
            tarifa = request.form.get("tarifa", "")
            if dias_texto and (not dias_texto.isdigit() or int(dias_texto) > 365):
                flash("El plazo de cobro son días, entre 0 y 365.", "error")
            else:
                mensajes = srv.guardar_cobertura(nombre, request.form.get("iva", ""), int(dias_texto) if dias_texto else None,
                                                 int(tarifa) if tarifa.isdigit() else None)
                db.auditar(yo["id"], None, "cobertura", f"{nombre}: IVA {request.form.get('iva', '')}, plazo {dias_texto or 'sin plazo'}")
                flash(" ".join(mensajes) or "Cobertura guardada.", "ok")
        elif accion == "plan_agregar":
            tid, plan = srv.agregar_plan(nombre, request.form.get("plan", ""))
            if tid is None:
                flash(plan, "error")
            else:
                db.auditar(yo["id"], None, "cobertura_plan", f"{nombre} · {plan}")
                flash(f"Plan {plan} agregado: cargale los importes en su tarifa.", "ok")
            return redirect(destino_planes)
        elif accion == "plan_quitar":
            error = srv.quitar_plan(nombre, request.form.get("plan", ""))
            if error:
                flash(error, "error")
            else:
                db.auditar(yo["id"], None, "cobertura_plan_quitado", f"{nombre} · {request.form.get('plan', '')}")
                flash("Plan quitado.", "ok")
            return redirect(destino_planes)
        return redirect(destino)
    pestana = "planes" if request.args.get("pestana") == "planes" else "datos"
    tarifas = db.q("SELECT id, nombre FROM tarifarios ORDER BY nombre")
    protocolos = db.uno("SELECT COUNT(*) AS n FROM protocolos WHERE cobertura=?", (nombre,))["n"]
    return render_template("coberturas/cobertura.html", c=srv.contexto_cobertura(nombre), pestana=pestana, tarifas=tarifas, general=srv.tarifa_general(),
                           tipos_iva=facturacion.TIPOS_IVA, protocolos=protocolos)
