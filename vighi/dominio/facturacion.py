import csv
import io
import re

from vighi.core import db
from vighi.core.texto import sin_acentos

ALICUOTA_IVA = 0.21
GENERAL = "TARIFA GENERAL"
ESTADOS = {"borrador": "Borrador", "emitida": "Emitida", "cobrada": "Cobrada", "anulada": "Anulada"}
TIPOS_IVA = {"exento": "Exento", "gravado": "Gravado"}
TIPOS_ESTUDIO = {"BP": "Biopsias", "CT": "Citologías", "PAP": "PAP"}
CLASES_ESTADO = {"borrador": "", "emitida": "activo", "cobrada": "informado", "anulada": "anulado"}
SIN_FACTURAR = "-"
TIPOS_FEC = {"tentativa": "Fecha estimada tentativa", "confirmada": "Fecha estimada confirmada", "cargada": "Fecha de cobro cargada"}


def numero(valor, defecto=0.0):
    texto = str(valor if valor is not None else "").strip().replace("$", "").replace(" ", "")
    if not texto:
        return defecto
    if "," in texto or re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return round(float(texto), 2)
    except ValueError:
        return None


def fecha_valida(texto):
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto or ""))


def fecha_flexible(texto):
    texto = (texto or "").strip()
    if fecha_valida(texto):
        return texto
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def cantidad_de(estudio_cantidad):
    texto = (estudio_cantidad or "").strip()
    return int(texto) if texto.isdigit() and int(texto) > 0 else 1


def contexto():
    tarifarios = {t["id"]: t for t in db.q("SELECT id, nombre, iva FROM tarifarios")}
    general = next((i for i, t in tarifarios.items() if t["nombre"] == GENERAL), min(tarifarios) if tarifarios else None)
    valores = {}
    for r in db.q("SELECT tarifario_id, codigo, importe, vigente_desde FROM tarifario_valores ORDER BY vigente_desde"):
        valores.setdefault((r["tarifario_id"], r["codigo"]), []).append((r["vigente_desde"], r["importe"]))
    muestras = {}
    for r in db.q("SELECT tarifario_id, tipo, sitio, tipo_muestra, codigo FROM nomenclador_muestras"):
        muestras[(r["tarifario_id"], r["tipo"], sin_acentos(r["sitio"]), sin_acentos(r["tipo_muestra"]))] = r["codigo"]
    return {"tarifarios": tarifarios, "general": general, "valores": valores, "muestras": muestras,
            "por_cobertura": {sin_acentos(r["cobertura"]): r["tarifario_id"] for r in db.q("SELECT cobertura, tarifario_id FROM tarifario_coberturas")},
            "nomencladores": {r["codigo"]: r["descripcion"] for r in db.q("SELECT codigo, descripcion FROM nomencladores")}}


def codigo_de(ctx, tarifario_id, tipo, sitio, tipo_muestra):
    s, m = sin_acentos(sitio), sin_acentos(tipo_muestra)
    for t in dict.fromkeys((tarifario_id, ctx["general"])):
        for clave in ((t, tipo, s, m), (t, tipo, "", m), (t, tipo, s, ""), (t, tipo, "", "")):
            if clave in ctx["muestras"]:
                return ctx["muestras"][clave]
    return None


def importe_vigente(ctx, tarifario_id, codigo, fecha):
    vigente = None
    for desde, importe in ctx["valores"].get((tarifario_id, codigo), []):
        if desde <= fecha:
            vigente = importe
    return vigente


def resolver(ctx, cobertura, tipo, sitio, tipo_muestra, fecha):
    tid = ctx["por_cobertura"].get(sin_acentos(cobertura), ctx["general"])
    codigo = codigo_de(ctx, tid, tipo, sitio, tipo_muestra)
    if not codigo:
        return {"ok": False, "motivo": "sin nomenclador para este tipo de muestra"}
    importe = importe_vigente(ctx, tid, codigo, fecha)
    if importe is None and tid != ctx["general"]:
        importe = importe_vigente(ctx, ctx["general"], codigo, fecha)
    if importe is None:
        return {"ok": False, "codigo": codigo, "motivo": f"sin importe vigente para {codigo}"}
    tarifario = ctx["tarifarios"].get(tid)
    return {"ok": True, "codigo": codigo, "descripcion": ctx["nomencladores"].get(codigo, ""), "importe": importe,
            "iva": tarifario["iva"] if tarifario else "exento", "tarifario": tarifario["nombre"] if tarifario else ""}


def iva_de(resultado, exento_protocolo):
    if (exento_protocolo or "").strip().lower() in ("si", "sí"):
        return "exento"
    return resultado.get("iva", "exento") if resultado else "exento"


def importe_linea(cantidad, unitario):
    return round((cantidad or 0) * (unitario or 0), 2)


def totales(items, alicuota=ALICUOTA_IVA):
    exento = round(sum(i["importe"] for i in items if i["iva"] != "gravado"), 2)
    gravado = round(sum(i["importe"] for i in items if i["iva"] == "gravado"), 2)
    iva = round(gravado * alicuota, 2)
    return {"exento": exento, "gravado": gravado, "iva": iva, "total": round(exento + gravado + iva, 2)}


def ids_facturados():
    return {r["estudio_id"]: r["factura_id"] for r in db.q(
        "SELECT i.estudio_id, i.factura_id FROM factura_items i JOIN facturas f ON f.id=i.factura_id WHERE f.estado<>'anulada'")}


def recalcular(factura_id):
    f = db.uno("SELECT alicuota FROM facturas WHERE id=?", (factura_id,))
    items = db.q("SELECT importe, iva FROM factura_items WHERE factura_id=?", (factura_id,))
    t = totales(items, f["alicuota"] if f and f["alicuota"] is not None else ALICUOTA_IVA)
    db.ex("UPDATE facturas SET exento=?, gravado=?, iva=?, total=? WHERE id=?", (t["exento"], t["gravado"], t["iva"], t["total"], factura_id))
    return t


def sentencias_items(factura_id, items):
    columnas = "factura_id, estudio_id, protocolo_id, numero_protocolo, paciente, afiliado, fecha, estudio, codigo, descripcion, cantidad, unitario, iva, importe"
    por_sentencia = 7
    sentencias = []
    for i in range(0, len(items), por_sentencia):
        grupo = items[i:i + por_sentencia]
        sentencias.append((f"INSERT INTO factura_items ({columnas}) VALUES " + ",".join(["(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"] * len(grupo)),
                           tuple(v for it in grupo for v in (factura_id, it["estudio_id"], it["protocolo_id"], it["numero_protocolo"], it["paciente"], it["afiliado"],
                                                             it["fecha"], it["estudio"], it["codigo"], it["descripcion"], it["cantidad"], it["unitario"], it["iva"], it["importe"]))))
    return sentencias


def csv_de_factura(factura, items):
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    w.writerow(["Factura", "Cobertura", "Protocolo", "Paciente", "Afiliado", "Fecha", "Estudio", "Nomenclador", "Descripción", "Cantidad", "Importe unitario", "IVA", "Importe"])
    for i in items:
        w.writerow([factura["numero"] or "", factura["cobertura"], i["numero_protocolo"], i["paciente"], i["afiliado"], i["fecha"], i["estudio"], i["codigo"],
                    i["descripcion"], i["cantidad"], f'{i["unitario"]:.2f}'.replace(".", ","), TIPOS_IVA.get(i["iva"], i["iva"]), f'{i["importe"]:.2f}'.replace(".", ",")])
    return "﻿" + salida.getvalue()


def _lector(texto):
    primera = (texto or "").split("\n", 1)[0]
    return csv.reader(io.StringIO(texto or ""), delimiter=";" if ";" in primera else ",")


def leer_valores(texto, hoy):
    nuevos, errores = [], []
    for n, fila in enumerate(_lector(texto), start=1):
        fila = [c.strip() for c in fila]
        if not any(fila):
            continue
        if n == 1 and sin_acentos(fila[0]) in ("nomenclador", "codigo"):
            continue
        if len(fila) < 3:
            errores.append(f"Línea {n}: faltan columnas (nomenclador; descripción; importe; vigente desde).")
            continue
        importe = numero(fila[2], None)
        desde = fecha_flexible(fila[3]) if len(fila) > 3 and fila[3] else hoy
        if not fila[0]:
            errores.append(f"Línea {n}: falta el nomenclador.")
        elif importe is None or importe < 0:
            errores.append(f"Línea {n}: importe inválido «{fila[2]}».")
        elif not desde:
            errores.append(f"Línea {n}: fecha inválida «{fila[3]}» (usá dd/mm/aaaa o aaaa-mm-dd).")
        else:
            nuevos.append({"codigo": fila[0][:20], "descripcion": fila[1][:300], "importe": importe, "vigente_desde": desde})
    return nuevos, errores


def leer_asignaciones(texto):
    nuevas, errores, sin_codigo = [], [], 0
    for n, fila in enumerate(_lector(texto), start=1):
        fila = [c.strip() for c in fila]
        if not any(fila):
            continue
        if n == 1 and sin_acentos(fila[0]) in ("tipo", "estudio"):
            continue
        if len(fila) < 4:
            errores.append(f"Línea {n}: faltan columnas (tipo; tipo de muestra; sitio; nomenclador).")
            continue
        tipo = fila[0].upper()
        if tipo not in TIPOS_ESTUDIO:
            errores.append(f"Línea {n}: el tipo «{fila[0]}» tiene que ser BP, CT o PAP.")
        elif not fila[3]:
            sin_codigo += 1
        else:
            nuevas.append({"tipo": tipo, "tipo_muestra": " ".join(fila[1].split())[:80], "sitio": " ".join(fila[2].split())[:80], "codigo": fila[3][:20]})
    return nuevas, errores, sin_codigo


def planilla_codigos(combinaciones, asignadas, descripciones):
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    w.writerow(["Tipo", "Tipo de muestra", "Sitio", "Nomenclador", "Descripción"])
    por_clave = {(a["tipo"], sin_acentos(a["sitio"]), sin_acentos(a["tipo_muestra"])): a for a in asignadas}
    usadas = set()
    for tipo, tipo_muestra in combinaciones:
        clave = (tipo, "", sin_acentos(tipo_muestra))
        usadas.add(clave)
        codigo = (por_clave[clave]["codigo"] or SIN_FACTURAR) if clave in por_clave else ""
        w.writerow([tipo, tipo_muestra, "", codigo, descripciones.get(codigo, "")])
    for clave, a in sorted(por_clave.items(), key=lambda x: (x[1]["tipo"], x[1]["tipo_muestra"], x[1]["sitio"])):
        if clave not in usadas:
            w.writerow([a["tipo"], a["tipo_muestra"], a["sitio"], a["codigo"] or SIN_FACTURAR, descripciones.get(a["codigo"], "")])
    return "﻿" + salida.getvalue()


def fecha_de_estudio(e):
    return (e.get("fecha_recoleccion") or e.get("creado_en") or "")[:10]
