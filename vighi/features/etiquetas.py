import json
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.fechas import hoy
from vighi.core.sesion import puede, requiere_permiso, usuario_actual
from vighi.dominio.estudios import REGISTRO
from vighi.servicios.etiquetas import ESTUDIO_LAB, GRUPO_NUMERACION, MAX_PROTOCOLO, TIPOS_ETIQUETA, _entero, codigo_muestra_pap, datos_etiquetas, estudio_de_lote, etiquetas_cantidad, etiquetas_casos, etiquetas_historial, numero_protocolo, personal, rotulos_cassettes, siguiente_libre, tecnicas_por_estudio, tipos_lote_etiqueta
from vighi.servicios.lotes import tipos_lote

bp = Blueprint("etiquetas", __name__)


@bp.route("/etiquetas")
@requiere_permiso("etiquetas_recepcion", "etiquetas_lab")
def etiquetas():
    preset = None
    if request.args.get("lote"):
        lote = db.uno("SELECT * FROM lotes WHERE id=?", (int(request.args["lote"]),)) if request.args["lote"].isdigit() else None
        if not lote:
            flash("El lote no existe.", "error")
            return redirect(url_for("lotes.lotes"))
        if not puede("etiquetas_lab"):
            flash("No tenés permiso para las etiquetas de laboratorio.", "error")
            return redirect(url_for("lotes.lote", lote_id=lote["id"]))
        if lote["tipo_lote"] in tipos_lote("BP"):
            preset = {"tab": "lab", "loteId": lote["id"]}
        elif lote["tipo_lote"] in tipos_lote("PAP"):
            preset = {"tab": "pap", "loteId": lote["id"]}
        else:
            flash("Las etiquetas de laboratorio son para lotes de biopsias y de PAP.", "error")
            return redirect(url_for("lotes.lote", lote_id=lote["id"]))
    return render_template("etiquetas/etiquetas.html", datos={**datos_etiquetas(), "nombres": TIPOS_ETIQUETA, "preset": preset})


@bp.route("/api/etiquetas/estado")
@requiere_permiso("etiquetas_recepcion", "etiquetas_lab")
def api_etiquetas_estado():
    return jsonify({"historial": etiquetas_historial(), "casos": etiquetas_casos()})


@bp.route("/api/etiquetas/confirmar", methods=["POST"])
@requiere_permiso("etiquetas_recepcion", "etiquetas_lab")
def api_etiquetas_confirmar():
    yo = usuario_actual()
    d = request.get_json(silent=True) or {}
    p = d.get("params") if isinstance(d.get("params"), dict) else {}
    tipo = d.get("tipo")

    def error(texto, estado=400, **extra):
        return jsonify({"ok": False, "error": texto, **datos_etiquetas(), **extra}), estado

    if tipo not in TIPOS_ETIQUETA:
        return error("Tipo de etiqueta inválido.")
    if not puede("etiquetas_recepcion" if tipo == "bp" else "etiquetas_lab"):
        return error(f"No tenés permiso para etiquetas de {TIPOS_ETIQUETA[tipo]}.", 403)
    citos = {x["iniciales"] for x in personal("citotecnico")}
    desde = hasta = None
    borradores = etiquetados = None

    if tipo == "bp":
        n = _entero(d.get("n"), 1, 1000)
        desde = _entero(d.get("inicio"), 1, MAX_PROTOCOLO)
        if not n or not desde:
            return error("Cargá la cantidad de protocolos (1 a 1000) y el primer número.")
        hasta = desde + n - 1
        if hasta > MAX_PROTOCOLO:
            return error(f"El rango se pasa de {numero_protocolo(MAX_PROTOCOLO)}. Bajá la cantidad o el primer número.")
        try:
            datetime.strptime(str(p.get("fecha", "")), "%Y-%m-%d")
        except ValueError:
            return error("Elegí la fecha de recolección antes de confirmar.")
        if p.get("lote") not in tipos_lote_etiqueta():
            return error("Tipo de lote inválido.")
        paps = p["lote"] == "PAPS"
        if paps and p.get("cito") not in citos:
            return error("Elegí el citotécnico: con lote PAPS va en la segunda línea de cada etiqueta.")
        cito = p["cito"] if paps else ""
        params = {"fecha": p["fecha"], "lote": p["lote"], "cito": cito}
        est = REGISTRO[estudio_de_lote(p["lote"])]
        borradores = {"estudio": est.clave, "categoria": est.categoria, "subcategoria": est.subcategoria_fija,
                      "sitio": est.sitio_fijo, "tipo_lote": cito if paps else p["lote"], "fecha_lote": hoy(),
                      "fecha_rec": p["fecha"], "protocolos": [numero_protocolo(k) for k in range(desde, hasta + 1)],
                      "responsable_id": (db.uno("SELECT id FROM usuarios WHERE iniciales=?", (cito,))["id"] if paps else None)}
        por_proto, total = 2, n * 2
    else:
        ids = d.get("items")
        if not isinstance(ids, list) or not ids or len(ids) > 500 or len(set(ids)) != len(ids) or \
                not all(isinstance(i, int) for i in ids):
            return error("Marcá al menos un protocolo para etiquetar.")
        filas = {f["id"]: f for f in db.q(
            f"""SELECT e.*, p.numero, p.borrador, p.fecha_recoleccion, u.iniciales AS resp, l.codigo AS lote_codigo
                FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                WHERE e.id IN ({','.join('?' * len(ids))})""", ids)}
        items = []
        tecnicas = tecnicas_por_estudio() if tipo == "lab" else {}
        for i in ids:
            f = filas.get(i)
            if not f or f["anulado"] or f["borrador"] or f["tipo"] != ESTUDIO_LAB[tipo] or not etiquetas_cantidad(f["cantidad"]):
                return error(f"El protocolo {f['numero'] if f else i} no está listo para {TIPOS_ETIQUETA[tipo]}: "
                             "tiene que estar completo (paciente y cantidad) y ser del estudio que corresponde.")
            nros = rotulos_cassettes(tecnicas.get(f["id"], [])) if tipo == "lab" else []
            items.append({"casoId": f["id"], "protocolo": f["numero"], "cantidad": len(nros) or etiquetas_cantidad(f["cantidad"]),
                          "loteCodigo": f["lote_codigo"] or "", "resp": f["resp"] or "", "fechaRec": f["fecha_recoleccion"] or "",
                          "muestra": codigo_muestra_pap(f["tipo_muestra"], f["cantidad"]) if tipo == "pap" else "", "nros": nros})
        n, total, por_proto = len(items), sum(i["cantidad"] for i in items), 1
        params = {"items": items}
        por_etiqueta = lambda campo: [i[campo] for i in items for _ in range(i["cantidad"])]
        if tipo == "lab":
            params["patos"] = por_etiqueta("resp")
            params["nros"] = [x for i in items for x in (i["nros"] + [""] * (i["cantidad"] - len(i["nros"])))]
        else:
            params["muestras"] = por_etiqueta("muestra")
        etiquetados = ids

    r = db.etiquetas_confirmar(tipo, GRUPO_NUMERACION, desde, hasta, n, por_proto, total,
                               json.dumps(params, ensure_ascii=False), yo["id"], borradores, etiquetados)
    if r.get("error") == "choque":
        f = r["fila"]
        return error(f"Ese rango se pisa con el lote de etiquetas N° {f['id']} ({TIPOS_ETIQUETA[f['tipo']]}), ya confirmado: "
                     f"{numero_protocolo(f['desde'])} a {numero_protocolo(f['hasta'])}. Cambiá el primer número: el siguiente "
                     f"libre es {numero_protocolo(siguiente_libre())}.", 409, conflicto=True)
    if r.get("error") == "existentes":
        ej = ", ".join(r["protocolos"][:3]) + ("…" if len(r["protocolos"]) > 3 else "")
        return error(f"Ya existen protocolos con esos números ({ej}), cargados a mano. "
                     "Elegí otro primer número.", 409)
    if r["lote"]:
        if r["lote"]["nuevo"]:
            db.auditar(yo["id"], None, "nuevo_lote", r["lote"]["codigo"])
        detalle = f"{numero_protocolo(desde)} a {numero_protocolo(hasta)} → lote {r['lote']['codigo']}"
    else:
        detalle = f"{n} protocolos"
    db.auditar(yo["id"], None, "etiquetas", f"{TIPOS_ETIQUETA[tipo]} {detalle} ({total} etiquetas)")
    return jsonify({"ok": True, "id": r["id"], **datos_etiquetas()})
