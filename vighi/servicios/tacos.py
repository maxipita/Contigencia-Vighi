from vighi.core import db


def tacos_del_estudio(e):
    if e["tipo"] != "BP" or e["tacos_muestra"] is None:
        return None
    frascos = int(e["cantidad"]) if (e["cantidad"] or "").isdigit() else 1
    return frascos * e["tacos_muestra"]


def sql_tacos(campo):
    return f"""SELECT e.{campo} AS clave,
                      SUM((CASE WHEN e.cantidad GLOB '[0-9]*' THEN CAST(e.cantidad AS INTEGER) ELSE 1 END) * COALESCE(t.tacos, 0)) AS tacos,
                      SUM(CASE WHEN t.tacos IS NULL THEN 1 ELSE 0 END) AS sin_dato
               FROM estudios e LEFT JOIN lotes l ON l.id=e.lote_id LEFT JOIN tacos_organo t ON t.organo=e.sitio AND t.tipo_lote=l.tipo_lote
               WHERE e.tipo='BP' AND e.anulado=0 AND e.{campo} IS NOT NULL{{filtro}} GROUP BY e.{campo}"""


def tacos_por(campo, valor=None):
    filas = db.q(sql_tacos(campo).format(filtro="" if valor is None else f" AND e.{campo}=?"), () if valor is None else (valor,))
    return {f["clave"]: (f["tacos"] or 0, f["sin_dato"] or 0) for f in filas}


def tacos_de_lote(lote_id):
    return tacos_por("lote_id", lote_id).get(lote_id, (0, 0))


def tacos_de_protocolo(protocolo_id):
    return tacos_por("protocolo_id", protocolo_id).get(protocolo_id, (0, 0))
