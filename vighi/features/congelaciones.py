from datetime import date, timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for

from vighi.core import db
from vighi.core.sesion import puede, requiere_login, requiere_permiso, usuario_actual
from vighi.servicios import congelaciones as cg
from vighi.servicios.consultas import listas

bp = Blueprint("congelaciones", __name__)
VISTAS = {"agenda": "Agenda", "tablero": "Tablero", "dashboard": "Dashboard", "patologo": "Agenda del patólogo"}
CONTAR = {"confirmadas": "Solo confirmadas", "todas": "Confirmadas y a confirmar"}


def entero(texto, defecto, minimo, maximo):
    return int(texto) if texto and texto.isdigit() and minimo <= int(texto) <= maximo else defecto


def datos_agenda(f):
    hoy = date.today()
    pedida = cg.fecha_de(request.args.get("semana"))
    base = cg.lunes_de(pedida) + timedelta(days=3) if pedida else hoy
    anio, mes = entero(request.args.get("anio"), base.year, 2000, 2100), entero(request.args.get("mes"), base.month, 1, 12)
    semanas = cg.semanas_del_mes(anio, mes)
    lunes = cg.lunes_de(pedida) if pedida and cg.lunes_de(pedida) in semanas else (cg.lunes_de(hoy) if cg.lunes_de(hoy) in semanas else semanas[0])
    dias = cg.agenda_semanal(f, lunes)
    activas = [c for d in dias for c in d["tarjetas"] if c["estado"] != "eliminada"]
    return {"anio": anio, "mes": mes, "semanas": [{"lunes": s, "domingo": s + timedelta(days=6)} for s in semanas], "lunes": lunes, "dias": dias, "hoy": hoy,
            "anios": range(hoy.year - 3, hoy.year + 3), "n_activas": len(activas), "n_confirmadas": sum(1 for c in activas if c["estado"] == "confirmada")}


def datos_tablero(f):
    actividad = request.args.get("actividad") if request.args.get("actividad") in ("todas", *cg.ACTIVIDADES) else "pendientes"
    filas, total = cg.tablero(f, actividad)
    return {"filas": filas, "total": total, "actividad": actividad, "limite": cg.LIMITE_TABLERO}


def datos_dashboard(f):
    anio = entero(request.args.get("anio"), date.today().year, 2000, 2100)
    contar = request.args.get("contar") if request.args.get("contar") in CONTAR else "confirmadas"
    filas, meses, total = cg.dashboard(f, anio, contar)
    return {"anio": anio, "contar": contar, "filas": filas, "totales_meses": meses, "gran_total": total, "anios": range(date.today().year - 3, date.today().year + 2)}


def datos_patologo(f):
    yo = usuario_actual()
    patologo = f["patologo"] if f["patologo"].isdigit() else (str(yo["id"]) if yo["id"] in {u["id"] for u in cg.patologos()} else "")
    pasadas = request.args.get("pasadas") == "1"
    tarjetas, por_estado, por_ubicacion, total = cg.agenda_patologo(int(patologo), f["estado"], f["ubicacion"], pasadas) if patologo else ([], {}, {}, 0)
    return {"patologo_elegido": patologo, "tarjetas": tarjetas, "por_estado": por_estado, "por_ubicacion": por_ubicacion, "total_base": total, "pasadas": pasadas,
            "n_alertas": sum(1 for c in tarjetas if c["alerta"])}


DATOS = {"agenda": datos_agenda, "tablero": datos_tablero, "dashboard": datos_dashboard, "patologo": datos_patologo}


def opciones(actual=None):
    return {"patologos": cg.patologos({actual["patologo_id"]} if actual and actual["patologo_id"] else ()), "coberturas": listas().get("cobertura", []), "horas": cg.HORAS, "tipos": cg.TIPOS,
            "estados_alta": cg.ESTADOS_ALTA, "estados": cg.ESTADOS}


@bp.route("/congelaciones")
@requiere_login
def congelaciones():
    vista = request.args.get("vista") if request.args.get("vista") in VISTAS else "agenda"
    db.precargar(cg.consultas_de_pantalla())
    f = cg.filtros_de(request.args)
    return render_template("congelaciones/congelaciones.html", vista=vista, vistas=VISTAS, f=f, patologos=cg.patologos(cg.patologos_usados()),
                           ubicaciones=[r["ubicacion"] for r in db.q(cg.SQL_UBICACIONES_USADAS)], medicos=cg.medicos_usados(f["ubicacion"]),
                           coberturas=[r["cobertura"] for r in db.q(cg.SQL_COBERTURAS_USADAS)], tipos=cg.TIPOS, estados=cg.ESTADOS, actividades=cg.ACTIVIDADES,
                           contar_opciones=CONTAR, meses=cg.MESES, **DATOS[vista](f))


@bp.route("/congelaciones/descargar")
@requiere_login
def descargar():
    f = cg.filtros_de(request.args)
    desde, hasta = cg.fecha_de(request.args.get("desde")), cg.fecha_de(request.args.get("hasta"))
    filas = cg.listar(f, desde.isoformat() if desde else None, hasta.isoformat() if hasta else None)
    db.auditar(usuario_actual()["id"], None, "exportar", f"Congelaciones ({len(filas)})")
    return send_file(cg.libro_excel(filas), as_attachment=True, download_name=f"congelaciones_{date.today():%Y%m%d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/api/congelaciones/paciente")
@requiere_login
def api_paciente():
    return jsonify(cg.paciente_por_dni(request.args.get("dni", "")) or {})


def volver(cid, ancla=""):
    destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for("congelaciones.congelacion", cid=cid)
    return redirect(destino.split("#")[0] + ancla)


def a_la_semana(fecha):
    dia = cg.fecha_de(fecha) or date.today()
    lunes = cg.lunes_de(dia)
    return redirect(url_for("congelaciones.congelaciones", semana=lunes.isoformat(), anio=(lunes + timedelta(days=3)).year, mes=(lunes + timedelta(days=3)).month))


@bp.route("/congelaciones/nueva", methods=["GET", "POST"])
@requiere_permiso("congelaciones")
def congelacion_nueva():
    form = {"fecha": (cg.fecha_de(request.args.get("fecha")) or date.today()).isoformat(), "hora": "08:00", "estado": "agendada", "tipo": cg.TIPOS[0]}
    if request.method == "POST":
        form = request.form
        d, error = cg.validar(form)
        if not error:
            cid, error = cg.crear(d, usuario_actual()["id"])
        if error:
            flash(error, "error")
        else:
            flash(f"Congelación #{cid} agendada para el {d['fecha']} a las {d['hora']}.", "ok")
            return a_la_semana(d["fecha"])
    return render_template("congelaciones/congelacion.html", c=None, form=form, vinculos=[], historial=[], **opciones())


@bp.route("/congelaciones/<int:cid>")
@requiere_login
def congelacion(cid):
    c = cg.decorar([cg.congelacion_o_404(cid)])[0]
    return render_template("congelaciones/congelacion.html", c=c, form=c, vinculos=cg.protocolos_de_paciente(c["dni"]), historial=cg.historial(cid), **opciones(c))


@bp.route("/congelaciones/<int:cid>/editar", methods=["POST"])
@requiere_permiso("congelaciones")
def congelacion_editar(cid):
    c = cg.decorar([cg.congelacion_o_404(cid)])[0]
    d, error = cg.validar(request.form, c)
    reprogramada = None
    if not error:
        reprogramada, error = cg.editar(c, d, usuario_actual()["id"])
    if error:
        flash(error, "error")
        return render_template("congelaciones/congelacion.html", c=c, form=request.form, vinculos=cg.protocolos_de_paciente(c["dni"]), historial=cg.historial(cid), **opciones(c))
    flash("Congelación actualizada." + (" Cambió la agenda: vuelve a A confirmar." if reprogramada else ""), "ok")
    return redirect(url_for("congelaciones.congelacion", cid=cid))


@bp.route("/congelaciones/<int:cid>/estado", methods=["POST"])
@requiere_login
def congelacion_estado(cid):
    c = cg.congelacion_o_404(cid)
    accion = request.form.get("accion", "")
    if accion not in cg.TRANSICIONES:
        abort(400)
    yo = usuario_actual()
    propia = accion in ("confirmar", "eliminar") and c["patologo_id"] == yo["id"]
    if not (propia or puede("congelaciones") or (accion in ("confirmar", "eliminar") and puede("congelaciones_confirmar"))):
        flash("No tenés permiso para esa acción. Pedíselo a un administrador.", "error")
        return volver(cid)
    error = cg.cambiar_estado(c, accion, yo["id"])
    flash(error or f"Congelación #{cid} {cg.VERBOS[accion]}.", "error" if error else "ok")
    return volver(cid)


@bp.route("/congelaciones/<int:cid>/protocolo", methods=["POST"])
@requiere_permiso("congelaciones")
def congelacion_protocolo(cid):
    c = cg.congelacion_o_404(cid)
    error = cg.vincular(c, request.form.get("numero", ""), usuario_actual()["id"])
    flash(error or ("Protocolo vinculado." if request.form.get("numero", "").strip() else "Protocolo desvinculado."), "error" if error else "ok")
    return volver(cid)
