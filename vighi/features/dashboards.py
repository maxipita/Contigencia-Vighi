from datetime import date

from flask import Blueprint, abort, render_template, request

from vighi.core.sesion import puede, requiere_login, usuario_actual
from vighi.servicios import dashboards as dash

bp = Blueprint("dashboards", __name__)


def datos_gerencial(f, hoy, yo):
    return dash.gerencial(f, hoy)


def datos_sector(vista):
    return lambda f, hoy, yo: dash.sector(vista, f, hoy)


def datos_patologos(f, hoy, yo):
    propios = not (yo["admin"] or puede("tablero_todos"))
    return {**dash.patologos(f, hoy, yo["iniciales"] if propios else None), "solo_lo_suyo": propios}


def datos_performance(f, hoy, yo):
    return dash.performance(f, hoy)


DATOS = {"gerencial": datos_gerencial, "ingreso": datos_sector("ingreso"), "laboratorio": datos_sector("laboratorio"), "macroscopia": datos_sector("macroscopia"),
         "traslados": datos_sector("traslados"), "citotecnicos": datos_sector("citotecnicos"), "patologos": datos_patologos, "performance": datos_performance}


@bp.route("/dashboards")
@requiere_login
def dashboards():
    visibles = [(k, n) for k, n in dash.VISTAS if puede(dash.PERMISO_DE[k])]
    if not visibles:
        abort(403)
    vista = request.args.get("vista", "")
    if vista not in dict(visibles):
        vista = visibles[0][0]
    f = dash.filtros_de(request.args)
    datos = DATOS[vista](f, date.today(), usuario_actual())
    return render_template("dashboards/dashboards.html", vista=vista, vistas=visibles, f=f, d=datos, o=dash.opciones(), UNIDADES=dash.UNIDADES, MESES=dash.MESES)
