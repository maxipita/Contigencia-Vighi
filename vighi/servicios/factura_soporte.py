from vighi.core import db
from vighi.core.texto import sin_acentos
from vighi.dominio import facturacion, soporte

COLUMNAS = "factura_id, orden, fecha, protocolo, estudio, paciente, afiliado, codigo, cantidad, unitario, iva, importe"
POR_SENTENCIA = 7


def cabecera_de(fid):
    return db.uno("SELECT s.nombre, s.subido_en, u.iniciales AS subio FROM factura_soportes s LEFT JOIN usuarios u ON u.id=s.subido_por WHERE s.factura_id=?", (fid,))


def filas_de(fid):
    return db.q("SELECT * FROM factura_soporte_filas WHERE factura_id=? ORDER BY orden", (fid,))


def soporte_de(fid):
    cab = cabecera_de(fid)
    if not cab:
        return None
    filas = filas_de(fid)
    return {"cabecera": cab, "resumen": soporte.resumen(filas), "vista": filas[:20]}


def sentencias_guardar(fid, nombre, filas, usuario_id):
    sentencias = [("DELETE FROM factura_soporte_filas WHERE factura_id=?", (fid,)), ("DELETE FROM factura_soportes WHERE factura_id=?", (fid,)),
                  ("INSERT INTO factura_soportes (factura_id, nombre, subido_por, subido_en) VALUES (?,?,?,?)", (fid, nombre[:200], usuario_id, db.ahora()))]
    for i in range(0, len(filas), POR_SENTENCIA):
        grupo = filas[i:i + POR_SENTENCIA]
        sentencias.append((f"INSERT INTO factura_soporte_filas ({COLUMNAS}) VALUES " + ",".join(["(?,?,?,?,?,?,?,?,?,?,?,?)"] * len(grupo)),
                           tuple(v for n, f in enumerate(grupo, start=i) for v in (fid, n, f["fecha"], f["protocolo"], f["estudio"], f["paciente"], f["afiliado"], f["codigo"],
                                                                                 f["cantidad"], f["unitario"], f["iva"], f["importe"]))))
    return sentencias


def guardar(fid, nombre, filas, usuario_id):
    db.lote_ex(sentencias_guardar(fid, nombre, filas, usuario_id))


def quitar(fid):
    db.lote_ex([("DELETE FROM factura_soporte_filas WHERE factura_id=?", (fid,)), ("DELETE FROM factura_soportes WHERE factura_id=?", (fid,))])


def items_de_planilla(fid):
    descripciones = {r["codigo"]: r["descripcion"] for r in db.q("SELECT codigo, descripcion FROM nomencladores")}
    return [{"numero_protocolo": f["protocolo"], "paciente": f["paciente"], "afiliado": f["afiliado"], "fecha": f["fecha"], "estudio": f["estudio"], "codigo": f["codigo"],
             "descripcion": descripciones.get(f["codigo"], ""), "cantidad": f["cantidad"], "unitario": f["unitario"], "iva": f["iva"], "importe": f["importe"]}
            for f in filas_de(fid)]


def totales(filas):
    exento = round(sum(f["importe"] for f in filas if f["iva"] != "gravado"), 2)
    gravado = round(sum(f["importe"] for f in filas if f["iva"] == "gravado"), 2)
    iva = round(gravado * facturacion.ALICUOTA_IVA, 2)
    return {"exento": exento, "gravado": gravado, "iva": iva, "total": round(exento + gravado + iva, 2)}


def cobertura_de_lista(nombre):
    reales = {sin_acentos(r["valor"]).lower(): r["valor"] for r in db.q("SELECT valor FROM listas WHERE nombre='cobertura'")}
    return reales.get(sin_acentos(nombre or "").lower())


def sentencias_factura(numero, cobertura, ff, fec, fec_tipo, filas, nombre, usuario_id):
    t = totales(filas)
    ahora = db.ahora()
    return ("INSERT INTO facturas (numero, estado, cobertura, fecha_factura, fecha_estimada_cobro, fec_tipo, exento, gravado, iva, total, alicuota, observaciones, "
            "creado_por, creado_en, emitida_por, emitida_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (numero, "emitida", cobertura, ff, fec or None, fec_tipo, t["exento"], t["gravado"], t["iva"], t["total"], facturacion.ALICUOTA_IVA,
             f"Cargada desde el soporte del sistema anterior ({nombre[:80]}), sin detalle de estudios del sistema nuevo.", usuario_id, ahora, usuario_id, ahora))


def crear_factura(numero, cobertura, ff, fec, fec_tipo, filas, nombre, usuario_id):
    sql, params = sentencias_factura(numero, cobertura, ff, fec, fec_tipo, filas, nombre, usuario_id)
    fid = db.ex(sql, params)
    try:
        guardar(fid, nombre, filas, usuario_id)
    except Exception:
        db.ex("DELETE FROM facturas WHERE id=?", (fid,))
        raise
    return fid
