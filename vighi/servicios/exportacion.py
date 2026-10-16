from vighi.core import db
from vighi.core.fechas import fecha, fecha_hora
from vighi.dominio.estudios import NOMBRE_ETAPA, REGISTRO, Variante
from vighi.servicios.consultas import SQL_CON_DECAL, SQL_CON_IHQ, etiqueta

PROTOCOLOS_POR_TANDA = 250
ORDEN_ETAPAS = [k for k in NOMBRE_ETAPA if k != "ingreso"]
CABECERA = (["N° Protocolo", "Estudio", "Estado", "Lote", "Anulado", "Protocolo sistema", "Cargado en sistema", "Responsable",
             "Ingresado", "Fecha recolección", "DNI", "Apellido", "Nombre", "Sexo", "Fecha nacimiento", "Cobertura",
             "N° afiliado", "Exento", "E-mail", "Teléfono", "Médico", "Lugar recolección", "Lugar entrega",
             "Observaciones protocolo", "Categoría", "Subcategoría", "Sitio", "Tipo de muestra", "Cantidad",
             "Citología hormonal", "Observaciones estudio",
             "Template macro", "Descripción macro", "Cassettes", "Template micro", "Descripción micro", "Conclusión",
             "Bethesda", "Técnicas especiales", "Solicita IHQ", "Marcadores IHQ", "Resultado IHQ"]
            + [f"{NOMBRE_ETAPA[k]} - {x}" for k in ORDEN_ETAPAS for x in ("usuario", "fecha/hora")])

SQL_PROTOCOLOS_EXPORTABLES = "SELECT id FROM protocolos WHERE borrador=0 ORDER BY id DESC"
SQL_ESTUDIOS = """SELECT e.id, e.protocolo_id, e.flujo_id, e.tipo, e.categoria, e.subcategoria, e.sitio, e.tipo_muestra, e.cantidad, e.citologia_hormonal,
                         e.observaciones AS observaciones_estudio, e.anulado, e.tecnicas_especiales, e.creado_en, u.iniciales AS responsable, l.codigo AS lote,
                         p.numero, p.protocolo_sistema, p.cargado_sistema, p.fecha_recoleccion, p.dni, p.apellido, p.nombre, p.sexo, p.fecha_nacimiento,
                         p.cobertura, p.n_afiliado, p.exento, p.email, p.telefono, p.medico, p.lugar_recoleccion, p.lugar_entrega, p.observaciones
                  FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                  LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                  WHERE p.borrador=0 AND e.protocolo_id BETWEEN ? AND ? ORDER BY p.id DESC, e.id"""
SQL_ETAPAS_TANDA = """SELECT x.flujo_id, x.etapa, x.fecha_hora, u.iniciales FROM etapas x JOIN flujos f ON f.id=x.flujo_id
                      LEFT JOIN usuarios u ON u.id=x.usuario_id WHERE f.protocolo_id BETWEEN ? AND ?"""
SQL_MACRO_TANDA = "SELECT m.* FROM macro m JOIN flujos f ON f.id=m.flujo_id WHERE f.protocolo_id BETWEEN ? AND ?"
SQL_MICRO_TANDA = "SELECT m.* FROM micro m JOIN flujos f ON f.id=m.flujo_id WHERE f.protocolo_id BETWEEN ? AND ?"
SQL_IHQ_TANDA = "SELECT m.* FROM ihq m JOIN flujos f ON f.id=m.flujo_id WHERE f.protocolo_id BETWEEN ? AND ?"
SQL_CON_IHQ_TANDA = SQL_CON_IHQ + " AND f.protocolo_id BETWEEN ? AND ?"
SQL_CON_DECAL_TANDA = SQL_CON_DECAL + " AND f.protocolo_id BETWEEN ? AND ?"


def tandas():
    ids = [r["id"] for r in db.q(SQL_PROTOCOLOS_EXPORTABLES)]
    for i in range(0, len(ids), PROTOCOLOS_POR_TANDA):
        yield ids[min(i + PROTOCOLOS_POR_TANDA, len(ids)) - 1], ids[i]


def texto(fila, clave):
    return (fila[clave] if fila else "") or ""


def filas_de_tanda(desde, hasta):
    rango = (desde, hasta)
    db.precargar([(sql, rango) for sql in (SQL_ESTUDIOS, SQL_ETAPAS_TANDA, SQL_MACRO_TANDA, SQL_MICRO_TANDA, SQL_IHQ_TANDA, SQL_CON_IHQ_TANDA, SQL_CON_DECAL_TANDA)])
    etapas = {}
    for x in db.q(SQL_ETAPAS_TANDA, rango):
        etapas.setdefault(x["flujo_id"], {})[x["etapa"]] = x
    macro = {r["flujo_id"]: r for r in db.q(SQL_MACRO_TANDA, rango)}
    micro = {r["flujo_id"]: r for r in db.q(SQL_MICRO_TANDA, rango)}
    ihq = {r["flujo_id"]: r for r in db.q(SQL_IHQ_TANDA, rango)}
    con_ihq = {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_CON_IHQ_TANDA, rango)}
    con_decal = {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_CON_DECAL_TANDA, rango)}
    filas = []
    for e in db.q(SQL_ESTUDIOS, rango):
        ma, mi, ih, et = macro.get(e["flujo_id"]), micro.get(e["flujo_id"]), ihq.get(e["flujo_id"]), etapas.get(e["flujo_id"], {})
        clave = (e["protocolo_id"], e["tipo"])
        estado = REGISTRO[e["tipo"]].estado(et, Variante(clave in con_ihq, clave in con_decal), bool(e["anulado"]))[0]
        fila = [e["numero"], etiqueta(e), estado, e["lote"], "Si" if e["anulado"] else "", e["protocolo_sistema"],
                "Si" if e["cargado_sistema"] else "No", e["responsable"], fecha_hora(e["creado_en"]),
                fecha(e["fecha_recoleccion"]), e["dni"], e["apellido"], e["nombre"], e["sexo"], fecha(e["fecha_nacimiento"]),
                e["cobertura"], e["n_afiliado"], e["exento"], e["email"], e["telefono"], e["medico"], e["lugar_recoleccion"],
                e["lugar_entrega"], e["observaciones"], e["categoria"], e["subcategoria"], e["sitio"], e["tipo_muestra"],
                e["cantidad"], e["citologia_hormonal"], e["observaciones_estudio"],
                texto(ma, "template"), texto(ma, "descripcion"), texto(ma, "cassettes"),
                texto(mi, "template"), texto(mi, "descripcion"), texto(mi, "conclusion"), texto(mi, "resultado") or texto(mi, "bethesda"),
                e["tecnicas_especiales"] or texto(mi, "tecnicas_especiales"), "Si" if mi and mi["solicita_ihq"] else "", texto(ih, "marcadores"), texto(ih, "resultado")]
        for k in ORDEN_ETAPAS:
            x = et.get(k)
            fila += [x["iniciales"] if x else "", fecha_hora(x["fecha_hora"]) if x else ""]
        filas.append(fila)
    db.olvidar_cache()
    return filas


def filas_exportables():
    for desde, hasta in tandas():
        yield from filas_de_tanda(desde, hasta)
