from flask import Blueprint, flash, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.fechas import hoy
from vighi.core.sesion import requiere_login, requiere_permiso, usuario_actual
from vighi.dominio.estudios import NOMBRE_ETAPA, REGISTRO, SECTORES, Variante
from vighi.servicios.consultas import cargar_estudios, etiqueta
from vighi.servicios.fichas import motivo_no_listo
from vighi.servicios.lotes import asignar_lote, crear_lote, lote_del_protocolo, lote_o_404, orden_numero, plan_avance, plan_avance_de, primer_estudio, tipos_lote
from vighi.servicios.tareas import sentencias_de_cierre
from vighi.servicios.tacos import tacos_de_lote, tacos_por

bp = Blueprint("lotes", __name__)


@bp.route("/lotes")
@requiere_login
def lotes():
    fecha_sel = request.args.get("fecha") or hoy()
    filas = db.q("""SELECT l.*, u.iniciales AS creador, COUNT(e.id) AS cantidad
                    FROM lotes l LEFT JOIN usuarios u ON u.id=l.creado_por
                    LEFT JOIN estudios e ON e.lote_id=l.id AND e.anulado=0
                    WHERE l.fecha=? GROUP BY l.id, u.iniciales ORDER BY l.cerrado, l.tipo_lote, l.numero""", (fecha_sel,))
    dias = db.q("SELECT fecha, COUNT(*) AS n FROM lotes GROUP BY fecha ORDER BY fecha DESC LIMIT 15")
    return render_template("lotes/lotes.html", lotes=filas, fecha_sel=fecha_sel, es_hoy=fecha_sel == hoy(), dias=dias,
                           tacos=tacos_por("lote_id"), lotes_bp=REGISTRO["BP"].lotes, capacidad=REGISTRO["BP"].tacos_por_lote,
                           grupos_lote=[("Biopsias", tipos_lote("BP")), ("Citologías", tipos_lote("CT")),
                                        ("PAP · citotécnico", tipos_lote("PAP"))])


@bp.route("/lotes/nuevo", methods=["POST"])
@requiere_permiso("lotes_armar")
def nuevo_lote():
    tipo_lote = request.form.get("tipo_lote", "")
    if tipo_lote not in tipos_lote():
        flash("Elegí el tipo de lote.", "error")
        return redirect(url_for("lotes.lotes"))
    lote = crear_lote(tipo_lote, usuario_actual()["id"])
    flash(f"Lote {lote['codigo']} creado.", "ok")
    return redirect(url_for("lotes.lote", lote_id=lote["id"]))


@bp.route("/lotes/<int:lote_id>/avanzar", methods=["POST"])
@requiere_permiso("etapas")
def lote_avanzar(lote_id):
    yo = usuario_actual()
    l = lote_o_404(lote_id)
    destino = url_for("lotes.lote", lote_id=lote_id)
    plan, error = plan_avance(lote_id)
    if not error and request.form.get("etapa") != plan["etapa"]:
        error = "El lote cambió de etapa mientras tenías la pantalla abierta: revisá y volvé a intentar."
    if not error and not yo["admin"] and plan["sector"] not in (yo["sectores"] or "").split(","):
        error = f"La etapa {NOMBRE_ETAPA[plan['etapa']]} la marca el sector {SECTORES[plan['sector']]}."
    if error:
        flash(error, "error")
        return redirect(destino)
    etapa = plan["etapa"]
    db.precargar([(f"SELECT m.* FROM {t} m JOIN estudios e ON e.id=m.estudio_id WHERE e.lote_id=?", (lote_id,)) for t in ("macro", "micro", "ihq")]
                 + [("SELECT DISTINCT t.estudio_id FROM tecnicas t JOIN estudios e ON e.id=t.estudio_id WHERE e.lote_id=?", (lote_id,))])
    por_tabla = {t: {r["estudio_id"]: r for r in db.q(f"SELECT m.* FROM {t} m JOIN estudios e ON e.id=m.estudio_id WHERE e.lote_id=?", (lote_id,))}
                 for t in ("macro", "micro", "ihq")}
    con_tecnicas = {r["estudio_id"] for r in db.q("SELECT DISTINCT t.estudio_id FROM tecnicas t JOIN estudios e ON e.id=t.estudio_id WHERE e.lote_id=?", (lote_id,))}
    problemas = []
    for flujo in plan["flujos"]:
        cabecera = min(m["id"] for m in flujo)
        primero = flujo[0]
        sin = [m for m in flujo if m["id"] not in con_tecnicas] if etapa == "macroscopia" and "macro" in REGISTRO[primero["tipo"]].secciones else []
        motivo = motivo_no_listo(yo, primero["tipo"], etapa, primero["proxima"], Variante(primero["solicita_ihq"], primero["decal"]),
                                 por_tabla["macro"].get(cabecera), por_tabla["micro"].get(cabecera), por_tabla["ihq"].get(cabecera), sin)
        if motivo:
            problemas.append(f"{primero['numero']}: {motivo}")
    if problemas:
        flash(f"No se avanzó el lote ({NOMBRE_ETAPA[etapa]}): " + " · ".join(problemas[:6]) + (f" · y {len(problemas) - 6} más" if len(problemas) > 6 else ""), "error")
        return redirect(destino)
    ahora_ = db.ahora()
    estudios = [m for f in plan["flujos"] for m in f]
    sentencias = []
    for i in range(0, len(estudios), 25):
        grupo = estudios[i:i + 25]
        sentencias.append(("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES " + ",".join(["(?,?,?,?)"] * len(grupo)),
                           tuple(v for m in grupo for v in (m["id"], etapa, yo["id"], ahora_))))
    for i in range(0, len(plan["flujos"]), 16):
        grupo = plan["flujos"][i:i + 16]
        sentencias.append(("INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, estudio_id, accion, detalle) VALUES " + ",".join(["(?,?,?,?,?,?)"] * len(grupo)),
                           tuple(v for f in grupo for v in (ahora_, yo["id"], f[0]["protocolo_id"], f[0]["id"], "listo",
                                                            f"{NOMBRE_ETAPA[etapa]} (lote {l['codigo']})"))))
    sentencias += sentencias_de_cierre([f[0]["protocolo_id"] for f in plan["flujos"]], etapa, f"{NOMBRE_ETAPA[etapa]} (lote {l['codigo']})", yo["id"])
    try:
        db.lote_ex(sentencias)
    except db.IntegrityError:
        flash("No se avanzó el lote: alguna etapa se registró en el medio. Recargá la pantalla y volvé a intentar.", "error")
        return redirect(destino)
    flash(f"✔ {NOMBRE_ETAPA[etapa]} registrada por {yo['iniciales']} en {len(plan['flujos'])} protocolo(s) / {len(estudios)} estudio(s) del lote {l['codigo']}.", "ok")
    return redirect(destino)


@bp.route("/lotes/<int:lote_id>")
@requiere_login
def lote(lote_id):
    l = lote_o_404(lote_id)
    del_lote = [x for x in cargar_estudios("e.lote_id=?", (lote_id,), borradores=True) if not x["anulado"]]
    del_lote.sort(key=lambda x: (orden_numero(x["numero"]), x["id"]))
    primeros = {r["id"] for r in db.q("SELECT MIN(id) AS id FROM estudios WHERE anulado=0 GROUP BY protocolo_id")}
    sin_lote = [x for x in cargar_estudios("e.lote_id IS NULL AND e.anulado=0")
                if x["id"] in primeros and l["tipo_lote"] in tipos_lote(x["tipo"])][:300]
    en_bp = l["tipo_lote"] in REGISTRO["BP"].lotes
    tacos_total, sin_dato = tacos_de_lote(lote_id) if en_bp else (0, 0)
    avance, sin_avance = plan_avance_de(del_lote)
    return render_template("lotes/lote.html", avance=avance, sin_avance=sin_avance, l=l, estudios=del_lote, sin_lote=sin_lote, capacidad=REGISTRO["BP"].tacos_por_lote if en_bp else None,
                           tacos_total=tacos_total, sin_dato=sin_dato,
                           etiquetas_lab=(l["tipo_lote"] in tipos_lote("BP") or l["tipo_lote"] in tipos_lote("PAP"))
                           and any(not x["anulado"] and not x["borrador"] for x in del_lote))


@bp.route("/lotes/<int:lote_id>/agregar", methods=["POST"])
@requiere_permiso("lotes_armar")
def lote_agregar(lote_id):
    yo = usuario_actual()
    l = lote_o_404(lote_id)
    elegido = request.form.get("estudio_id", "")
    numero = request.form.get("protocolo", "").strip()
    if elegido.isdigit():
        p = db.uno("SELECT p.* FROM protocolos p JOIN estudios e ON e.protocolo_id=p.id WHERE e.id=?", (int(elegido),))
    else:
        p = db.uno("SELECT * FROM protocolos WHERE numero=?", (numero,)) if numero else None
    primero = primer_estudio(p["id"]) if p else None
    if l["cerrado"]:
        flash("El lote está cerrado.", "error")
    elif not elegido and not numero:
        flash("Elegí un protocolo de la lista o escribí su N°.", "error")
    elif not p:
        flash(f"No existe el protocolo {numero}. Primero hay que ingresarlo.", "error")
    elif not primero:
        flash(f"El protocolo {p['numero']} no tiene estudios activos.", "error")
    elif l["tipo_lote"] not in tipos_lote(primero["tipo"]):
        flash(f"El protocolo {p['numero']} empieza con {etiqueta(primero)} y el lote lo marca su primer flujo: no va en un lote {l['tipo_lote']}.", "error")
    elif primero["lote_id"] == lote_id:
        flash(f"{p['numero']} ya está en este lote.", "error")
    else:
        previo = lote_del_protocolo(p["id"])
        asignar_lote(p["id"], l, yo["id"])
        flash(f"{p['numero']} agregado al lote" + (f" (estaba en {previo['codigo']})." if previo else "."), "ok")
        capacidad = REGISTRO["BP"].tacos_por_lote
        total = tacos_de_lote(lote_id)[0] if l["tipo_lote"] in REGISTRO["BP"].lotes else 0
        if total > capacidad:
            flash(f"Atención: el lote {l['codigo']} queda en {total}/{capacidad} tacos.", "error")
    return redirect(url_for("lotes.lote", lote_id=lote_id))


@bp.route("/lotes/<int:lote_id>/quitar/<int:eid>", methods=["POST"])
@requiere_permiso("lotes_armar")
def lote_quitar(lote_id, eid):
    l = lote_o_404(lote_id)
    e = db.uno("SELECT protocolo_id FROM estudios WHERE id=? AND lote_id=?", (eid, lote_id))
    if l["cerrado"]:
        flash("El lote está cerrado.", "error")
    elif e:
        asignar_lote(e["protocolo_id"], None, usuario_actual()["id"])
        flash("Protocolo quitado del lote.", "ok")
    return redirect(url_for("lotes.lote", lote_id=lote_id))


@bp.route("/lotes/<int:lote_id>/cerrar", methods=["POST"])
@requiere_permiso("lotes_cerrar")
def lote_cerrar(lote_id):
    yo = usuario_actual()
    l = lote_o_404(lote_id)
    if l["cerrado"]:
        db.ex("UPDATE lotes SET cerrado=0, cerrado_por=NULL, cerrado_en=NULL WHERE id=?", (lote_id,))
        db.auditar(yo["id"], None, "reabrir_lote", l["codigo"])
        flash(f"Lote {l['codigo']} reabierto.", "ok")
    else:
        db.ex("UPDATE lotes SET cerrado=1, cerrado_por=?, cerrado_en=? WHERE id=?", (yo["id"], db.ahora(), lote_id))
        db.auditar(yo["id"], None, "cerrar_lote", l["codigo"])
        flash(f"Lote {l['codigo']} cerrado.", "ok")
    return redirect(url_for("lotes.lote", lote_id=lote_id))


@bp.route("/lotes/<int:lote_id>/observaciones", methods=["POST"])
@requiere_permiso("lotes_armar")
def lote_observaciones(lote_id):
    lote_o_404(lote_id)
    db.ex("UPDATE lotes SET observaciones=? WHERE id=?", (request.form.get("observaciones", "").strip(), lote_id))
    flash("Observaciones guardadas.", "ok")
    return redirect(url_for("lotes.lote", lote_id=lote_id))


@bp.route("/lotes/<int:lote_id>/eliminar", methods=["POST"])
@requiere_permiso("lotes_cerrar")
def lote_eliminar(lote_id):
    l = lote_o_404(lote_id)
    if db.uno("SELECT 1 FROM estudios WHERE lote_id=? AND anulado=0", (lote_id,)):
        flash("Solo se puede eliminar un lote vacío.", "error")
        return redirect(url_for("lotes.lote", lote_id=lote_id))
    db.ex("UPDATE estudios SET lote_id=NULL WHERE lote_id=?", (lote_id,))
    db.ex("DELETE FROM lotes WHERE id=?", (lote_id,))
    db.auditar(usuario_actual()["id"], None, "eliminar_lote", l["codigo"])
    flash(f"Lote {l['codigo']} eliminado.", "ok")
    return redirect(url_for("lotes.lotes", fecha=l["fecha"]))
