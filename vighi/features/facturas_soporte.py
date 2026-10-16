import io
import re

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from vighi.core import db
from vighi.core.fechas import hoy
from vighi.core.sesion import requiere_permiso, usuario_actual
from vighi.dominio import facturacion, soporte
from vighi.servicios import factura_soporte as servicio
from vighi.servicios.facturas import coberturas_lista, factura_o_404, items_de_factura

bp = Blueprint("soporte_facturas", __name__)
MAX_BYTES = 15 * 1024 * 1024


def _leer_subida():
    archivo = request.files.get("soporte")
    if not archivo or not archivo.filename:
        return None, None, "Elegí el archivo del soporte (Excel o CSV)."
    contenido = archivo.read()
    if len(contenido) > MAX_BYTES:
        return None, None, "El archivo pesa más de 15 MB."
    leido, errores = soporte.leer_soporte(archivo.filename, contenido)
    if errores:
        return None, None, " ".join(errores)
    return archivo.filename, leido, None


@bp.route("/facturacion/historica", methods=["GET", "POST"])
@requiere_permiso("facturacion")
def historica():
    datos = {k: request.form.get(k, "").strip() for k in ("numero", "cobertura", "fecha_factura", "fecha_estimada_cobro", "fec_tipo")}
    if request.method == "POST":
        nombre, leido, error = _leer_subida()
        numero = datos["numero"][:40]
        cobertura = datos["cobertura"] or (servicio.cobertura_de_lista(leido["cobertura"]) if leido else "") or ""
        if not error and not numero:
            error = "Indicá el número de la factura."
        elif not error and not cobertura:
            error = f"Elegí la cobertura: «{leido['cobertura']}» del soporte no está en la lista de coberturas."
        elif not error and (not facturacion.fecha_valida(datos["fecha_factura"]) or (datos["fecha_estimada_cobro"] and not facturacion.fecha_valida(datos["fecha_estimada_cobro"]))):
            error = "Cargá una fecha de factura válida (y la fecha estimada de cobro, si la ponés)."
        elif not error and db.uno("SELECT 1 FROM facturas WHERE numero=? AND estado<>'anulada'", (numero,)):
            error = f"Ya existe una factura con el número {numero}."
        if error:
            flash(error, "error")
        else:
            yo = usuario_actual()
            tipo = datos["fec_tipo"] if datos["fec_tipo"] in facturacion.TIPOS_FEC else "tentativa"
            fid = servicio.crear_factura(numero, cobertura, datos["fecha_factura"], datos["fecha_estimada_cobro"], tipo, leido["filas"], nombre, yo["id"])
            db.auditar(yo["id"], None, "factura_historica", f"{numero} · {cobertura} · {len(leido['filas'])} filas del soporte {nombre[:60]}")
            flash(f"Factura {numero} cargada desde el soporte: {len(leido['filas'])} filas. Revisá los totales y descargá la planilla.", "ok")
            return redirect(url_for("facturacion.factura", fid=fid))
    return render_template("facturacion/historica.html", d=datos, coberturas=coberturas_lista(), hoy=hoy(), tipos_fec=facturacion.TIPOS_FEC)


def _factura_editable(fid):
    f = factura_o_404(fid)
    if f["estado"] == "anulada" or items_de_factura(fid):
        return f, "Solo las facturas sin detalle de estudios del sistema nuevo (las cargadas del sistema anterior) admiten un soporte."
    return f, None


@bp.route("/facturacion/<int:fid>/soporte", methods=["POST"])
@requiere_permiso("facturacion")
def soporte_subir(fid):
    f, error = _factura_editable(fid)
    if not error:
        nombre, leido, error = _leer_subida()
    if error:
        flash(error, "error")
    else:
        yo = usuario_actual()
        servicio.guardar(fid, nombre, leido["filas"], yo["id"])
        db.auditar(yo["id"], None, "factura_soporte", f"{f['numero'] or fid} · {len(leido['filas'])} filas del soporte {nombre[:60]}")
        flash(f"Soporte cargado: {len(leido['filas'])} filas. Revisá los totales contra la factura y descargá la planilla.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid) + "#soporte")


@bp.route("/facturacion/<int:fid>/soporte/quitar", methods=["POST"])
@requiere_permiso("facturacion")
def soporte_quitar(fid):
    f = factura_o_404(fid)
    servicio.quitar(fid)
    db.auditar(usuario_actual()["id"], None, "factura_soporte_quitado", f["numero"] or str(fid))
    flash("Soporte quitado de la factura.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid) + "#soporte")


@bp.route("/facturacion/<int:fid>/planilla.csv")
@requiere_permiso("facturacion")
def planilla(fid):
    f = factura_o_404(fid)
    if not servicio.cabecera_de(fid):
        flash("Esta factura no tiene un soporte cargado.", "error")
        return redirect(url_for("facturacion.factura", fid=fid))
    datos = facturacion.csv_de_factura(f, servicio.items_de_planilla(fid)).encode("utf-8")
    nombre = re.sub(r"[^A-Za-z0-9_-]+", "_", f["numero"] or f"factura_{fid}")
    return send_file(io.BytesIO(datos), mimetype="text/csv", as_attachment=True, download_name=f"planilla_{nombre}.csv")
