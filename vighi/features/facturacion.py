import io
import re
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from vighi.core import almacen, db
from vighi.core.fechas import MESES, MESES_CORTOS, hoy
from vighi.core.sesion import requiere_permiso, usuario_actual
from vighi.core.texto import sin_acentos
from vighi.dominio import facturacion
from vighi.servicios.catalogo import tipos_de_muestra, tipos_de_muestra_bp
from vighi.servicios.consultas import cargar_estudios
from vighi.servicios import factura_archivos as adjuntos
from vighi.servicios.factura_soporte import soporte_de
from vighi.servicios.coberturas import contexto_cobertura
from vighi.servicios.facturas import (coberturas_lista, dos_decimales, factura_o_404, facturacion_buscar, items_de_factura,
                                     planilla_de_tarifa, sentencias_asignacion, tarifa_elegida)

bp = Blueprint("facturacion", __name__)


@bp.route("/facturacion")
@requiere_permiso("facturacion")
def facturacion_lista():
    f = {k: request.args.get(k, "") for k in ("cobertura", "anio", "mes", "estado")}
    todas = db.q("SELECT f.*, u.iniciales AS creador FROM facturas f LEFT JOIN usuarios u ON u.id=f.creado_por ORDER BY f.id DESC")
    visibles = []
    for r in todas:
        referencia = (r["fecha_factura"] or r["creado_en"] or "")[:10]
        if f["cobertura"] and r["cobertura"] != f["cobertura"]:
            continue
        if f["anio"] and referencia[:4] != f["anio"]:
            continue
        if f["mes"] and referencia[5:7] != f["mes"].zfill(2):
            continue
        if f["estado"] == "sincobrar":
            if r["estado"] != "emitida":
                continue
        elif f["estado"]:
            if r["estado"] != f["estado"]:
                continue
        elif r["estado"] == "anulada":
            continue
        visibles.append(r)
    acumulado = {k: round(sum(r[k] or 0 for r in visibles if r["estado"] != "anulada"), 2) for k in ("exento", "gravado", "iva", "total")}
    anios = sorted({(r["fecha_factura"] or r["creado_en"] or "")[:4] for r in todas if (r["fecha_factura"] or r["creado_en"])} | {hoy()[:4]}, reverse=True)
    return render_template("facturacion/facturacion.html", facturas=visibles, f=f, acumulado=acumulado, anios=anios, coberturas=coberturas_lista(),
                           estados=facturacion.ESTADOS, clases=facturacion.CLASES_ESTADO)


@bp.route("/administracion")
@requiere_permiso("facturacion")
def administracion():
    hoy_d = datetime.now().date()
    actual = (hoy_d.year, hoy_d.month)
    siguiente = (hoy_d.year + (hoy_d.month == 12), hoy_d.month % 12 + 1)
    pendientes = db.q("SELECT id, numero, cobertura, total, fecha_estimada_cobro, fec_tipo FROM facturas WHERE estado='emitida' ORDER BY fecha_estimada_cobro, id")
    columnas = {actual: [], siguiente: []}
    sin_fecha = 0
    for r in pendientes:
        if not r["fecha_estimada_cobro"]:
            sin_fecha += 1
            continue
        d = datetime.strptime(r["fecha_estimada_cobro"], "%Y-%m-%d").date()
        atraso = (hoy_d - d).days
        color = "atr5" if atraso > 5 else ("atr" if atraso > 0 else "ok")
        simbolo = "tent" if r["fec_tipo"] == "tentativa" else "conf"
        titulo = {"ok": "En fecha", "atr": "Cobro atrasado", "atr5": "Cobro atrasado más de 5 días"}[color] + " · " + \
                 ("fecha tentativa" if simbolo == "tent" else "fecha confirmada" if r["fec_tipo"] == "confirmada" else "fecha de cobro cargada")
        clave = max(actual, (d.year, d.month))
        columnas.setdefault(clave, []).append({"id": r["id"], "numero": r["numero"], "cobertura": r["cobertura"], "total": r["total"], "color": color,
                                               "simbolo": simbolo, "titulo": titulo, "fecha": f"{d.day:02d} {MESES_CORTOS[d.month - 1]}.", "orden": d})
    meses = []
    for clave in sorted(columnas):
        filas = sorted(columnas[clave], key=lambda x: (x["orden"], x["cobertura"]))
        nombre = MESES[clave[1] - 1].capitalize() + (f" {clave[0]}" if clave[0] != hoy_d.year else "")
        meses.append({"nombre": nombre, "total": round(sum(x["total"] or 0 for x in filas), 2), "filas": filas, "actual": clave == actual})
    return render_template("facturacion/administracion.html", meses=meses, sin_fecha=sin_fecha, cantidad=sum(len(m["filas"]) for m in meses))


@bp.route("/facturar", methods=["GET", "POST"])
@requiere_permiso("facturacion")
def facturar():
    yo = usuario_actual()
    if request.method == "POST":
        ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
        volver = url_for("facturacion.facturar", **{k: v for k, v in request.form.items() if k in ("desde", "hasta", "cobertura", "plan", "procedencia", "iva", "flujo", "zona", "clase", "informados", "facturados", "prioridad", "q")})
        if not ids:
            flash("Marcá al menos un estudio para facturar.", "error")
            return redirect(volver)
        with db.bloqueo("facturas"):
            proto = {r["id"]: r for r in db.q("SELECT id, cobertura, plan, n_afiliado, exento, lugar_recoleccion, pendiente_validacion FROM protocolos")}
            ya = facturacion.ids_facturados()
            ctx = facturacion.contexto()
            elegidos = [e for e in cargar_estudios() if e["id"] in set(ids)]
            problemas, items, coberturas = [], [], set()
            if len(elegidos) != len(set(ids)):
                problemas.append("Algún estudio elegido ya no existe.")
            for e in elegidos:
                p = proto[e["protocolo_id"]]
                if e["anulado"]:
                    problemas.append(f"{e['numero']} · {e['etiqueta']}: el estudio está anulado.")
                    continue
                if e["id"] in ya:
                    problemas.append(f"{e['numero']} · {e['etiqueta']}: ya está en la factura N° {ya[e['id']]}.")
                    continue
                if p["pendiente_validacion"]:
                    problemas.append(f"{e['numero']}: los datos del paciente están sin validar.")
                    continue
                if not (p["cobertura"] or "").strip():
                    problemas.append(f"{e['numero']}: el protocolo no tiene cobertura.")
                    continue
                fecha_e = facturacion.fecha_de_estudio(e)
                tarifa = facturacion.resolver(ctx, p["cobertura"], e["tipo"], e["sitio"], e["tipo_muestra"], fecha_e or hoy(), p["plan"] or "")
                if not tarifa["ok"]:
                    problemas.append(f"{e['numero']} · {e['etiqueta']}: {tarifa['motivo']}.")
                    continue
                coberturas.add(sin_acentos(p["cobertura"]))
                cantidad = facturacion.cantidad_de(e["cantidad"])
                items.append({"estudio_id": e["id"], "protocolo_id": e["protocolo_id"], "numero_protocolo": e["numero"],
                              "paciente": ((e["apellido"] or "") + (", " + e["nombre"] if e["nombre"] else ""))[:160], "afiliado": p["n_afiliado"] or "",
                              "fecha": fecha_e, "estudio": e["etiqueta"], "codigo": tarifa["codigo"], "descripcion": tarifa["descripcion"],
                              "cantidad": cantidad, "unitario": tarifa["importe"], "iva": facturacion.iva_de(tarifa, p["exento"]),
                              "importe": facturacion.importe_linea(cantidad, tarifa["importe"]), "cobertura": p["cobertura"]})
            if len(coberturas) > 1:
                problemas.append("Los estudios elegidos son de coberturas distintas: una factura es de una sola cobertura.")
            if problemas or not items:
                flash("No se generó la factura: " + " · ".join(problemas[:6] or ["no hay estudios válidos."]), "error")
                return redirect(volver)
            fid = db.ex("INSERT INTO facturas (estado, cobertura, alicuota, creado_por, creado_en) VALUES ('borrador',?,?,?,?)",
                        (items[0]["cobertura"], facturacion.ALICUOTA_IVA, yo["id"], db.ahora()))
            try:
                db.lote_ex(facturacion.sentencias_items(fid, items))
            except Exception:
                db.ex("DELETE FROM facturas WHERE id=?", (fid,))
                raise
            facturacion.recalcular(fid)
        db.auditar(yo["id"], None, "factura_nueva", f"Borrador {fid} · {items[0]['cobertura']} · {len(items)} ítems")
        flash(f"Se generó el borrador de factura con {len(items)} ítems.", "ok")
        return redirect(url_for("facturacion.factura", fid=fid))
    claves = ("desde", "hasta", "cobertura", "plan", "procedencia", "iva", "flujo", "zona", "clase", "prioridad", "q")
    f = {k: request.args.get(k, "") for k in claves}
    f["tipo"] = ""
    buscado = "buscar" in request.args
    hoy_d = datetime.now()
    if not buscado:
        f["desde"] = hoy_d.replace(day=1).strftime("%Y-%m-%d")
        f["hasta"] = ((hoy_d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d")
    f["informados"] = request.args.get("informados", "si")
    f["facturados"] = request.args.get("facturados", "no")
    filas = facturacion_buscar(f) if buscado else []
    procedencias = sorted({(r["lugar_recoleccion"] or "").strip() for r in db.q("SELECT DISTINCT lugar_recoleccion FROM protocolos")} - {""})
    zonas = sorted({r["subcategoria"] for r in db.q("SELECT DISTINCT subcategoria FROM estudios WHERE subcategoria IS NOT NULL AND subcategoria<>''")})
    return render_template("facturacion/facturar.html", f=f, filas=filas[:500], total=len(filas), buscado=buscado, coberturas=coberturas_lista(),
                           tipos_iva=facturacion.TIPOS_IVA, procedencias=procedencias, zonas=zonas,
                           planes=sorted({p for v in db.planes_por_cobertura().values() for p in v}))


@bp.route("/facturacion/<int:fid>")
@requiere_permiso("facturacion")
def factura(fid):
    return render_template("facturacion/factura.html", f=factura_o_404(fid), items=items_de_factura(fid), estados=facturacion.ESTADOS,
                           clases=facturacion.CLASES_ESTADO, tipos_iva=facturacion.TIPOS_IVA, hoy=hoy(), tipos_fec=facturacion.TIPOS_FEC, dos=dos_decimales,
                           archivos=adjuntos.archivos_de(fid), tamano=adjuntos.tamano_legible, visibles=adjuntos.VISIBLES, soporte=soporte_de(fid))


@bp.route("/facturacion/<int:fid>/guardar", methods=["POST"])
@requiere_permiso("facturacion")
def factura_guardar(fid):
    f = factura_o_404(fid)
    if f["estado"] != "borrador":
        flash("Solo se puede editar una factura en borrador.", "error")
        return redirect(url_for("facturacion.factura", fid=fid))
    errores, sentencias = [], []
    for it in items_de_factura(fid):
        cantidad = facturacion.numero(request.form.get(f"c_{it['id']}"), None)
        unitario = facturacion.numero(request.form.get(f"u_{it['id']}"), None)
        iva = request.form.get(f"i_{it['id']}", it["iva"])
        if cantidad is None or cantidad < 1 or cantidad != int(cantidad) or unitario is None or unitario < 0 or iva not in facturacion.TIPOS_IVA:
            errores.append(it["numero_protocolo"])
            continue
        sentencias.append(("UPDATE factura_items SET codigo=?, cantidad=?, unitario=?, iva=?, importe=? WHERE id=?",
                           (request.form.get(f"k_{it['id']}", it["codigo"]).strip()[:20], int(cantidad), unitario, iva,
                            facturacion.importe_linea(int(cantidad), unitario), it["id"])))
    if errores:
        flash("No se guardó: revisá cantidad e importe de " + ", ".join(dict.fromkeys(errores)) + ".", "error")
        return redirect(url_for("facturacion.factura", fid=fid))
    if sentencias:
        db.lote_ex(sentencias)
    db.ex("UPDATE facturas SET observaciones=? WHERE id=?", (request.form.get("observaciones", "").strip()[:500] or None, fid))
    facturacion.recalcular(fid)
    flash("Factura guardada.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid))


@bp.route("/facturacion/<int:fid>/quitar/<int:iid>", methods=["POST"])
@requiere_permiso("facturacion")
def factura_quitar(fid, iid):
    f = factura_o_404(fid)
    if f["estado"] != "borrador":
        flash("Solo se pueden quitar ítems de una factura en borrador.", "error")
    else:
        db.ex("DELETE FROM factura_items WHERE id=? AND factura_id=?", (iid, fid))
        facturacion.recalcular(fid)
        flash("Ítem quitado de la factura.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid))


def dias_de_pago(cobertura):
    clave = sin_acentos(cobertura)
    fila = next((r for r in db.q("SELECT cobertura, dias FROM cobertura_pago") if sin_acentos(r["cobertura"]) == clave), None)
    return fila["dias"] if fila else None


@bp.route("/facturacion/<int:fid>/emitir", methods=["POST"])
@requiere_permiso("facturacion")
def factura_emitir(fid):
    yo = usuario_actual()
    f = factura_o_404(fid)
    numero_factura = request.form.get("numero", "").strip()[:40]
    fecha_factura = request.form.get("fecha_factura", "") or hoy()
    fecha_estimada = request.form.get("fecha_estimada_cobro", "").strip()
    fec_tipo = request.form.get("fec_tipo", "tentativa")
    if fec_tipo not in facturacion.TIPOS_FEC:
        fec_tipo = "tentativa"
    dias = dias_de_pago(f["cobertura"])
    if not fecha_estimada and dias is not None and facturacion.fecha_valida(fecha_factura):
        fecha_estimada = (datetime.strptime(fecha_factura, "%Y-%m-%d") + timedelta(days=dias)).strftime("%Y-%m-%d")
        fec_tipo = "tentativa"
    if f["estado"] != "borrador":
        flash("La factura ya no está en borrador.", "error")
    elif not items_de_factura(fid):
        flash("La factura no tiene ítems.", "error")
    elif not numero_factura:
        flash("Indicá el número de factura para emitirla.", "error")
    elif not facturacion.fecha_valida(fecha_factura) or (fecha_estimada and not facturacion.fecha_valida(fecha_estimada)):
        flash("La fecha de factura o la fecha estimada de cobro no es válida.", "error")
    elif db.uno("SELECT 1 FROM facturas WHERE numero=? AND id<>? AND estado<>'anulada'", (numero_factura, fid)):
        flash(f"Ya existe otra factura con el número {numero_factura}.", "error")
    else:
        db.ex("UPDATE facturas SET estado='emitida', numero=?, fecha_factura=?, fecha_estimada_cobro=?, fec_tipo=?, emitida_por=?, emitida_en=? WHERE id=?",
              (numero_factura, fecha_factura, fecha_estimada or None, fec_tipo, yo["id"], db.ahora(), fid))
        db.auditar(yo["id"], None, "factura_emitida", f"{numero_factura} · {f['cobertura']} · {fecha_factura}")
        flash(f"Factura {numero_factura} emitida.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid))


@bp.route("/facturacion/<int:fid>/fec", methods=["POST"])
@requiere_permiso("facturacion")
def factura_fec(fid):
    yo = usuario_actual()
    f = factura_o_404(fid)
    fecha_estimada = request.form.get("fecha_estimada_cobro", "").strip()
    fec_tipo = request.form.get("fec_tipo", "tentativa")
    if f["estado"] != "emitida":
        flash("La fecha estimada de cobro se cambia solo en una factura emitida.", "error")
    elif fecha_estimada and not facturacion.fecha_valida(fecha_estimada):
        flash("La fecha estimada de cobro no es válida.", "error")
    elif fec_tipo not in facturacion.TIPOS_FEC:
        flash("Elegí el tipo de fecha.", "error")
    else:
        db.ex("UPDATE facturas SET fecha_estimada_cobro=?, fec_tipo=? WHERE id=?", (fecha_estimada or None, fec_tipo, fid))
        db.auditar(yo["id"], None, "factura_fec", f"{f['numero']} · {fecha_estimada or 'sin fecha'} · {fec_tipo}")
        flash("Fecha estimada de cobro actualizada.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid))


@bp.route("/facturacion/<int:fid>/cobrar", methods=["POST"])
@requiere_permiso("facturacion")
def factura_cobrar(fid):
    yo = usuario_actual()
    f = factura_o_404(fid)
    fecha_cobro = request.form.get("fecha_cobro", "") or hoy()
    texto = request.form.get("monto", "").strip()
    monto = facturacion.numero(texto, None) if texto else f["total"]
    if f["estado"] not in ("emitida", "cobrada"):
        flash("Solo se puede registrar el cobro de una factura emitida.", "error")
    elif not facturacion.fecha_valida(fecha_cobro):
        flash("La fecha de cobro no es válida.", "error")
    elif monto is None or monto <= 0:
        flash("Indicá cuánto se cobró (un importe mayor a cero).", "error")
    else:
        corrige = f["estado"] == "cobrada"
        db.ex("UPDATE facturas SET estado='cobrada', fecha_cobro=?, cobrado=?, cobrada_por=?, cobrada_en=? WHERE id=?",
              (fecha_cobro, monto, yo["id"], db.ahora(), fid))
        db.auditar(yo["id"], None, "factura_cobro_corregido" if corrige else "factura_cobrada", f"{f['numero']} · {fecha_cobro} · cobrado {monto:.2f} de {f['total']:.2f}")
        diferencia = round(f["total"] - monto, 2)
        aviso = f" Cobrado ${monto:,.2f} de ${f['total']:,.2f}: diferencia ${diferencia:,.2f}." if abs(diferencia) >= 0.01 else ""
        flash(("Cobro corregido." if corrige else "Cobro registrado.") + aviso, "ok")
    return redirect(url_for("facturacion.factura", fid=fid))


@bp.route("/facturacion/<int:fid>/desmarcar-cobro", methods=["POST"])
@requiere_permiso("facturacion")
def factura_desmarcar_cobro(fid):
    yo = usuario_actual()
    f = factura_o_404(fid)
    if f["estado"] != "cobrada":
        flash("La factura no figura como cobrada.", "error")
    else:
        db.ex("UPDATE facturas SET estado='emitida', fecha_cobro=NULL, cobrado=NULL, cobrada_por=NULL, cobrada_en=NULL WHERE id=?", (fid,))
        db.auditar(yo["id"], None, "factura_cobro_desmarcado", f"{f['numero']} · se quitó el cobro del {f['fecha_cobro']} ({f['cobrado'] if f['cobrado'] is not None else f['total']})")
        flash("Cobro desmarcado: la factura vuelve a figurar como emitida, pendiente de cobro.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid))


@bp.route("/facturacion/<int:fid>/anular", methods=["POST"])
@requiere_permiso("facturacion")
def factura_anular(fid):
    yo = usuario_actual()
    f = factura_o_404(fid)
    motivo = request.form.get("motivo", "").strip()[:200]
    if f["estado"] not in ("borrador", "emitida"):
        flash("Solo se puede anular una factura en borrador o emitida.", "error")
    elif not motivo:
        flash("Indicá el motivo de la anulación.", "error")
    else:
        db.ex("UPDATE facturas SET estado='anulada', anulada_por=?, anulada_en=?, anulada_motivo=? WHERE id=?", (yo["id"], db.ahora(), motivo, fid))
        db.auditar(yo["id"], None, "factura_anulada", f"{f['numero'] or 'borrador ' + str(fid)} · {motivo}")
        flash("Factura anulada: sus estudios vuelven a estar disponibles para facturar.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid))


@bp.route("/facturacion/<int:fid>/archivos", methods=["POST"])
@requiere_permiso("facturacion")
def factura_archivos_subir(fid):
    yo = usuario_actual()
    f = factura_o_404(fid)
    subidos = [x for x in request.files.getlist("archivos") if x and x.filename]
    if not subidos:
        flash("Elegí al menos un archivo.", "error")
    elif adjuntos.cantidad(fid) + len(subidos) > adjuntos.MAX_POR_FACTURA:
        flash(f"Una factura admite hasta {adjuntos.MAX_POR_FACTURA} archivos.", "error")
    else:
        leidos = [(x.filename, x.read()) for x in subidos]
        errores = [e for e in (adjuntos.validar(n, d) for n, d in leidos) if e]
        if errores:
            flash(" ".join(errores) + " No se subió ninguno.", "error")
        else:
            for nombre, datos in leidos:
                adjuntos.guardar(fid, nombre, datos, yo["id"])
            db.auditar(yo["id"], None, "factura_archivo", f"{f['numero'] or 'borrador ' + str(fid)} · " + ", ".join(adjuntos.nombre_seguro(n) for n, _ in leidos))
            flash(f"Se subió {len(leidos)} archivo(s) a la factura.", "ok")
    return redirect(url_for("facturacion.factura", fid=fid) + "#archivos")


@bp.route("/facturacion/archivo/<int:aid>")
@requiere_permiso("facturacion")
def factura_archivo(aid):
    a = adjuntos.archivo_o_none(aid) or abort(404)
    r = send_file(io.BytesIO(almacen.leer(a["datos"])), mimetype=adjuntos.EXTENSIONES.get(a["extension"], "application/octet-stream"),
                  as_attachment=a["extension"] not in adjuntos.VISIBLES, download_name=a["nombre"], conditional=False)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "private"
    return r


@bp.route("/facturacion/archivo/<int:aid>/borrar", methods=["POST"])
@requiere_permiso("facturacion")
def factura_archivo_borrar(aid):
    yo = usuario_actual()
    a = adjuntos.archivo_o_none(aid) or abort(404)
    f = factura_o_404(a["factura_id"])
    adjuntos.quitar(a)
    db.auditar(yo["id"], None, "factura_archivo_borrado", f"{f['numero'] or 'borrador ' + str(f['id'])} · {a['nombre']}")
    flash("Archivo quitado de la factura.", "ok")
    return redirect(url_for("facturacion.factura", fid=f["id"]) + "#archivos")


@bp.route("/facturacion/<int:fid>.csv")
@requiere_permiso("facturacion")
def factura_csv(fid):
    f = factura_o_404(fid)
    datos = facturacion.csv_de_factura(f, items_de_factura(fid)).encode("utf-8")
    nombre = re.sub(r"[^A-Za-z0-9_-]+", "_", f["numero"] or f"borrador_{fid}")
    return send_file(io.BytesIO(datos), mimetype="text/csv", as_attachment=True, download_name=f"factura_{nombre}.csv")


def _tarifa_post(accion, yo, general, actual):
    if accion == "crear_tarifario":
        nombre = " ".join(request.form.get("nombre", "").split())[:80].upper()
        iva = request.form.get("iva", "exento")
        if not nombre or iva not in facturacion.TIPOS_IVA:
            flash("Indicá el nombre y el IVA de la tarifa.", "error")
        elif db.uno("SELECT 1 FROM tarifarios WHERE nombre=?", (nombre,)):
            flash("Ya existe una tarifa con ese nombre.", "error")
        else:
            nuevo_id = db.ex("INSERT INTO tarifarios (nombre, iva) VALUES (?,?)", (nombre, iva))
            db.auditar(yo["id"], None, "tarifario_nuevo", nombre)
            flash(f"Tarifa {nombre} creada: cargale los importes y asignala a una cobertura desde Coberturas.", "ok")
            return url_for("facturacion.tarifario", tarifario=nuevo_id)
    elif accion == "guardar_tarifario":
        iva = request.form.get("iva", actual["iva"])
        if iva in facturacion.TIPOS_IVA:
            db.ex("UPDATE tarifarios SET iva=? WHERE id=?", (iva, actual["id"]))
        db.auditar(yo["id"], None, "tarifario", f"{actual['nombre']}: IVA {iva}")
        flash("Tarifa guardada.", "ok")
    return None


def _valores_post(accion, yo, actual, hoy_):
    if accion == "descripcion_valor":
        codigo = request.form.get("codigo", "").strip()[:20]
        descripcion = " ".join(request.form.get("descripcion", "").split())[:300]
        if not codigo:
            flash("Falta el nomenclador.", "error")
        else:
            db.lote_ex([("DELETE FROM tarifario_descripciones WHERE tarifario_id=? AND codigo=?", (actual["id"], codigo))]
                       + ([("INSERT INTO tarifario_descripciones (tarifario_id, codigo, descripcion) VALUES (?,?,?)", (actual["id"], codigo, descripcion))] if descripcion else []))
            db.auditar(yo["id"], None, "tarifa_descripcion", f"{actual['nombre']} · {codigo} · {descripcion or 'vuelve a la general'}")
            flash(f"Descripción de {codigo} guardada para {actual['nombre']}." if descripcion else f"{codigo} vuelve a usar la descripción general.", "ok")
    elif accion == "valor":
        codigo = request.form.get("codigo", "").strip()[:20]
        importe = facturacion.numero(request.form.get("importe"), None)
        desde = facturacion.fecha_flexible(request.form.get("vigente_desde")) or hoy_
        descripcion = request.form.get("descripcion", "").strip()[:300]
        if not codigo or importe is None or importe < 0:
            flash("Indicá el nomenclador y un importe válido.", "error")
        else:
            sentencias = []
            if not db.uno("SELECT 1 FROM nomencladores WHERE codigo=?", (codigo,)):
                sentencias.append(("INSERT INTO nomencladores (codigo, descripcion) VALUES (?,?)", (codigo, descripcion)))
            if descripcion:
                sentencias += [("DELETE FROM tarifario_descripciones WHERE tarifario_id=? AND codigo=?", (actual["id"], codigo)),
                               ("INSERT INTO tarifario_descripciones (tarifario_id, codigo, descripcion) VALUES (?,?,?)", (actual["id"], codigo, descripcion))]
            sentencias += [("DELETE FROM tarifario_valores WHERE tarifario_id=? AND codigo=? AND vigente_desde=?", (actual["id"], codigo, desde)),
                           ("INSERT INTO tarifario_valores (tarifario_id, codigo, importe, vigente_desde) VALUES (?,?,?,?)", (actual["id"], codigo, importe, desde))]
            db.lote_ex(sentencias)
            db.auditar(yo["id"], None, "tarifa_valor", f"{actual['nombre']} · {codigo} · {importe} desde {desde}")
            flash(f"Importe de {codigo} guardado, vigente desde {desde[8:]}/{desde[5:7]}/{desde[:4]}.", "ok")
    elif accion == "bloque":
        porcentaje = facturacion.numero(request.form.get("porcentaje"), None)
        desde = facturacion.fecha_flexible(request.form.get("vigente_desde")) or hoy_
        if porcentaje is None or porcentaje <= -100:
            flash("Indicá un porcentaje válido (por ejemplo 5 o 5,5).", "error")
        else:
            vigentes, vistos = [], set()
            for r in db.q("SELECT codigo, importe, vigente_desde FROM tarifario_valores WHERE tarifario_id=? AND vigente_desde<=? ORDER BY codigo, vigente_desde DESC", (actual["id"], desde)):
                if r["codigo"] not in vistos:
                    vistos.add(r["codigo"])
                    vigentes.append(r)
            sentencias = []
            for r in vigentes:
                nuevo_importe = round(r["importe"] * (1 + porcentaje / 100), 2)
                sentencias += [("DELETE FROM tarifario_valores WHERE tarifario_id=? AND codigo=? AND vigente_desde=?", (actual["id"], r["codigo"], desde)),
                               ("INSERT INTO tarifario_valores (tarifario_id, codigo, importe, vigente_desde) VALUES (?,?,?,?)", (actual["id"], r["codigo"], nuevo_importe, desde))]
            for i in range(0, len(sentencias), 40):
                db.lote_ex(sentencias[i:i + 40])
            db.auditar(yo["id"], None, "tarifa_bloque", f"{actual['nombre']}: {porcentaje:+}% desde {desde} ({len(vigentes)} importes)")
            flash(f"Se actualizaron {len(vigentes)} importes ({porcentaje:+g} %), vigentes desde el {desde[8:]}/{desde[5:7]}/{desde[:4]}.", "ok")
    elif accion == "importar":
        nuevos, errores = facturacion.leer_valores(request.form.get("texto", ""), hoy_)
        if errores:
            flash("No se importó nada: " + " · ".join(errores[:6]) + (f" · y {len(errores) - 6} más" if len(errores) > 6 else ""), "error")
        elif not nuevos:
            flash("No hay líneas para importar.", "error")
        else:
            sentencias = []
            for n in nuevos:
                if n["descripcion"]:
                    sentencias += [("DELETE FROM tarifario_descripciones WHERE tarifario_id=? AND codigo=?", (actual["id"], n["codigo"])),
                                   ("INSERT INTO tarifario_descripciones (tarifario_id, codigo, descripcion) VALUES (?,?,?)", (actual["id"], n["codigo"], n["descripcion"]))]
                sentencias += [("DELETE FROM tarifario_valores WHERE tarifario_id=? AND codigo=? AND vigente_desde=?", (actual["id"], n["codigo"], n["vigente_desde"])),
                               ("INSERT INTO tarifario_valores (tarifario_id, codigo, importe, vigente_desde) VALUES (?,?,?,?)", (actual["id"], n["codigo"], n["importe"], n["vigente_desde"]))]
            for i in range(0, len(sentencias), 40):
                db.lote_ex(sentencias[i:i + 40])
            db.ex("INSERT INTO nomencladores (codigo, descripcion) SELECT DISTINCT codigo, '' FROM tarifario_valores WHERE codigo NOT IN (SELECT codigo FROM nomencladores)")
            db.auditar(yo["id"], None, "tarifas_importadas", f"{actual['nombre']}: {len(nuevos)} importes")
            flash(f"Se importaron {len(nuevos)} importes.", "ok")
    elif accion == "borrar_valor" and request.form.get("id", "").isdigit():
        db.ex("DELETE FROM tarifario_valores WHERE id=? AND tarifario_id=?", (int(request.form["id"]), actual["id"]))
        flash("Importe borrado.", "ok")


@bp.route("/tarifario", methods=["GET", "POST"])
@requiere_permiso("facturacion")
def tarifario():
    yo = usuario_actual()
    tarifarios = db.q("SELECT * FROM tarifarios ORDER BY nombre")
    general = next((t for t in tarifarios if t["nombre"] == facturacion.GENERAL), tarifarios[0] if tarifarios else None)
    cob = contexto_cobertura(request.values.get("c", ""))
    elegido = request.values.get("tarifario", "")
    actual = next((t for t in tarifarios if str(t["id"]) == elegido), general)
    if cob and actual["id"] not in cob["ids"]:
        actual = next((t for t in tarifarios if t["id"] == cob["opciones"][0]["id"]), general)
    ver = request.values.get("ver", "vigentes")
    destino = url_for("facturacion.tarifario", tarifario=actual["id"], ver=ver, c=cob["cob"]["nombre"] if cob else None)
    hoy_ = hoy()
    if request.method == "POST":
        accion = request.form.get("accion", "")
        nuevo = _tarifa_post(accion, yo, general, actual)
        if nuevo is None:
            _valores_post(accion, yo, actual, hoy_)
        return redirect(nuevo or destino)
    filas = db.q("""SELECT v.id, v.codigo, v.importe, v.vigente_desde, COALESCE(NULLIF(d.descripcion, ''), n.descripcion) AS descripcion,
                           d.descripcion AS propia FROM tarifario_valores v
                    LEFT JOIN nomencladores n ON n.codigo=v.codigo
                    LEFT JOIN tarifario_descripciones d ON d.tarifario_id=v.tarifario_id AND d.codigo=v.codigo
                    WHERE v.tarifario_id=? ORDER BY v.codigo, v.vigente_desde DESC""", (actual["id"],))
    if ver != "todas":
        vistos, vigentes = set(), []
        for r in filas:
            if r["codigo"] in vistos or r["vigente_desde"] > hoy_:
                continue
            vistos.add(r["codigo"])
            vigentes.append(r)
        filas = vigentes
    usada_por = db.q("SELECT cobertura, plan FROM tarifario_coberturas WHERE tarifario_id=? ORDER BY cobertura, plan", (actual["id"],))
    nombres = {t["id"]: t["nombre"] for t in tarifarios}
    return render_template("facturacion/tarifario.html", cob=cob, tarifarios=tarifarios, actual=actual, general=general, ver="todas" if ver == "todas" else "vigentes", filas=filas, hoy=hoy_,
                           n_ceros=sum(1 for r in filas if r["importe"] == 0 and r["vigente_desde"] <= hoy_), usada_por=usada_por,
                           coberturas=coberturas_lista(), nombres=nombres, tipos_iva=facturacion.TIPOS_IVA,
                           nomencladores=db.q("SELECT codigo, descripcion FROM nomencladores ORDER BY codigo"), dos=dos_decimales)


@bp.route("/nomencladores", methods=["GET", "POST"])
@requiere_permiso("facturacion")
def nomencladores():
    yo = usuario_actual()
    tarifarios, general, actual = tarifa_elegida(request.values.get("tarifario", ""))
    cob = contexto_cobertura(request.values.get("c", ""))
    if cob and actual["id"] not in cob["ids"]:
        actual = next((t for t in tarifarios if t["id"] == cob["opciones"][0]["id"]), general)
    destino = url_for("facturacion.nomencladores", tarifario=actual["id"], c=cob["cob"]["nombre"] if cob else None)
    if request.method == "POST":
        accion = request.form.get("accion", "")
        if accion == "asignar":
            tipo = request.form.get("tipo", "")
            tipo_muestra = " ".join(request.form.get("tipo_muestra", "").split())[:80]
            sitio = " ".join(request.form.get("sitio", "").split())[:80]
            codigo = request.form.get("codigo", "").strip()
            if tipo not in facturacion.TIPOS_ESTUDIO or (codigo != facturacion.SIN_FACTURAR and not db.uno("SELECT 1 FROM nomencladores WHERE codigo=?", (codigo,))):
                flash("Elegí el tipo de estudio y un nomenclador que exista.", "error")
            else:
                db.lote_ex(sentencias_asignacion(actual["id"], [{"tipo": tipo, "tipo_muestra": tipo_muestra, "sitio": sitio, "codigo": codigo}]))
                db.auditar(yo["id"], None, "nomenclador_muestra", f"{actual['nombre']} · {tipo} · {tipo_muestra or 'cualquier muestra'} · {sitio or 'cualquier sitio'} → {codigo}")
                flash("Asignación guardada.", "ok")
        elif accion == "editar_asignacion" and request.form.get("id", "").isdigit():
            codigo = request.form.get("codigo", "").strip()[:20]
            fila = db.uno("SELECT id, tipo, sitio, tipo_muestra FROM nomenclador_muestras WHERE id=? AND tarifario_id=?", (int(request.form["id"]), actual["id"]))
            if not fila or not codigo:
                flash("Indicá el nomenclador (o - si no tiene código asignado).", "error")
            else:
                sentencias = []
                if codigo != facturacion.SIN_FACTURAR and not db.uno("SELECT 1 FROM nomencladores WHERE codigo=?", (codigo,)):
                    sentencias.append(("INSERT INTO nomencladores (codigo, descripcion) VALUES (?, '')", (codigo,)))
                sentencias.append(("UPDATE nomenclador_muestras SET codigo=? WHERE id=? AND tarifario_id=?", ("" if codigo == facturacion.SIN_FACTURAR else codigo, fila["id"], actual["id"])))
                db.lote_ex(sentencias)
                db.auditar(yo["id"], None, "nomenclador_muestra", f"{actual['nombre']} · {fila['tipo']} · {fila['tipo_muestra'] or 'cualquier muestra'} · {fila['sitio'] or 'cualquier sitio'} → {codigo}")
                flash("Nomenclador actualizado.", "ok")
        elif accion == "borrar_asignacion" and request.form.get("id", "").isdigit():
            db.ex("DELETE FROM nomenclador_muestras WHERE id=? AND tarifario_id=?", (int(request.form["id"]), actual["id"]))
            flash("Asignación borrada.", "ok")
        return redirect(destino)
    lista = db.q("SELECT codigo, descripcion FROM nomencladores ORDER BY codigo")
    asignaciones = db.q("""SELECT m.id, m.tipo, m.sitio, m.tipo_muestra, m.codigo, n.descripcion FROM nomenclador_muestras m
                           LEFT JOIN nomencladores n ON n.codigo=m.codigo WHERE m.tarifario_id=? ORDER BY m.tipo, m.tipo_muestra, m.sitio""", (actual["id"],))
    cubiertos = {(r["tarifario_id"], r["tipo"], sin_acentos(r["tipo_muestra"])) for r in db.q("SELECT tarifario_id, tipo, tipo_muestra FROM nomenclador_muestras WHERE sitio=''")}
    sin_asignar = []
    for tipo in facturacion.TIPOS_ESTUDIO:
        faltan = [t for t in tipos_de_muestra(tipo) if not any((tid, tipo, sin_acentos(t)) in cubiertos for tid in (actual["id"], general["id"]))]
        if faltan:
            sin_asignar.append((facturacion.TIPOS_ESTUDIO[tipo], faltan))
    sitios = sorted({r["sitio"] for r in db.q("SELECT DISTINCT sitio FROM catalogo WHERE tipo='BP'")})
    heredadas = db.uno("SELECT COUNT(*) AS n FROM nomenclador_muestras WHERE tarifario_id=?", (general["id"],))["n"] if actual["id"] != general["id"] else 0
    return render_template("facturacion/nomencladores.html", cob=cob, nomencladores=lista, asignaciones=asignaciones, tipos=facturacion.TIPOS_ESTUDIO, sin_asignar=sin_asignar,
                           tipos_muestra=tipos_de_muestra_bp(), sitios=sitios, tarifarios=tarifarios, actual=actual, general=general, heredadas=heredadas)


@bp.route("/nomencladores/planilla")
@requiere_permiso("facturacion")
def nomencladores_planilla():
    _, _, actual = tarifa_elegida(request.args.get("tarifario", ""))
    nombre = re.sub(r"[^A-Za-z0-9]+", "_", sin_acentos(actual["nombre"])).strip("_") or "tarifa"
    return send_file(io.BytesIO(planilla_de_tarifa(actual["id"]).encode("utf-8")), mimetype="text/csv", as_attachment=True, download_name=f"codigos_{nombre}.csv")
