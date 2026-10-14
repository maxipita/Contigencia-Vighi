from datetime import datetime

from vighi.core import db
from vighi.dominio import trazabilidad
from vighi.dominio.estudios import NOMBRE_ETAPA, REGISTRO, TIPOS, Variante
from vighi.servicios.tacos import tacos_del_estudio


def listas():
    out = {}
    for r in db.q(SQL_LISTAS):
        out.setdefault(r["nombre"], []).append(r["valor"])
    return out


def responsables(tipo):
    sector = REGISTRO[tipo].sector_responsable
    return [u for u in db.q("SELECT id, iniciales, nombre, sectores FROM usuarios WHERE activo=1 ORDER BY iniciales")
            if sector in (u["sectores"] or "").split(",")]


SQL_ETAPAS = "SELECT estudio_id, etapa, fecha_hora FROM etapas"
SQL_CON_IHQ = "SELECT e.protocolo_id, e.tipo FROM micro m JOIN estudios e ON e.id=m.estudio_id WHERE m.solicita_ihq=1 AND e.anulado=0"
SQL_CON_DECAL = "SELECT e.protocolo_id, e.tipo FROM macro m JOIN estudios e ON e.id=m.estudio_id WHERE m.decal=1 AND e.anulado=0"
SQL_TIPOS = "SELECT e.protocolo_id, e.tipo FROM estudios e WHERE e.anulado=0"


def consultas_estudios(where="1=1", params=(), borradores=False):
    principal = f"""SELECT e.*, p.numero, p.apellido, p.nombre, p.dni, p.fecha_recoleccion, p.cargado_sistema, p.borrador,
                            p.lugar_recoleccion, p.lugar_entrega, u.iniciales AS responsable, l.codigo AS lote, t.tacos AS tacos_muestra,
                            (SELECT COUNT(*) FROM estudios x WHERE x.protocolo_id=e.protocolo_id AND x.anulado=0) AS hermanos,
                            (SELECT COUNT(*) FROM comentarios c WHERE c.protocolo_id=e.protocolo_id) AS n_comentarios
                     FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                     LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                     LEFT JOIN tacos_organo t ON t.organo=e.sitio AND t.tipo_lote=l.tipo_lote
                     WHERE {where}{'' if borradores else ' AND p.borrador=0'} ORDER BY p.id DESC, e.id"""
    return [(principal, tuple(params)), (SQL_ETAPAS, ()), (SQL_CON_IHQ, ()), (SQL_CON_DECAL, ()), (SQL_TIPOS, ())]


def cargar_estudios(where="1=1", params=(), borradores=False):
    consultas = consultas_estudios(where, params, borradores)
    db.precargar(consultas)
    filas = db.q(*consultas[0])
    hechas, fechas = {}, {}
    for r in db.q(SQL_ETAPAS):
        hechas.setdefault(r["estudio_id"], set()).add(r["etapa"])
        fechas.setdefault(r["estudio_id"], {})[r["etapa"]] = r["fecha_hora"]
    con_ihq = {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_CON_IHQ)}
    con_decal_ = {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_CON_DECAL)}
    out, fer, ahora_ = [], db.feriados(), datetime.now()
    flujos = flujos_de() if filas else {}
    for f in filas:
        d = dict(f)
        d["flujos"] = flujos.get(f["protocolo_id"], "")
        tipo = REGISTRO[f["tipo"]]
        d["solicita_ihq"] = (f["protocolo_id"], f["tipo"]) in con_ihq
        decal = (f["protocolo_id"], f["tipo"]) in con_decal_
        d["decal"] = decal
        d["estado"], prox = tipo.estado(hechas.get(f["id"], set()), Variante(d["solicita_ihq"], decal), bool(f["anulado"]))
        if f["borrador"]:
            d["estado"] = "A completar"
        d["proxima"] = prox
        d["vence"] = trazabilidad.limite(f["tipo"], prox[0], f["fecha_recoleccion"] or f["creado_en"], fer, decal) if prox else None
        d["semaforo"] = (trazabilidad.semaforo_acumulado(f["tipo"], f["fecha_recoleccion"] or f["creado_en"], {"ingreso": f["creado_en"], **fechas.get(f["id"], {})},
                                                         d["vence"], ahora_, fer, decal) if d["vence"] and not f["borrador"] else "")
        d["etiqueta"] = etiqueta(f)
        d["tacos"] = tacos_del_estudio(f)
        out.append(d)
    return out


def etiqueta(e):
    if e["tipo"] == "PAP" or not e["sitio"]:
        return TIPOS[e["tipo"]]
    return f"{TIPOS[e['tipo']]} · {e['sitio']}"


def etiqueta_flujos(tipos, con_ihq):
    t = [k for k in ("BP", "CT", "PAP") if k in tipos]
    if not t:
        return ""
    return t[0] + (" c/ " + " y ".join(t[1:]) if len(t) > 1 else "") + (" + IHQ" if con_ihq else "")


def flujos_de(protocolo_ids=None):
    tipos = {}
    for r in db.q(SQL_TIPOS):
        tipos.setdefault(r["protocolo_id"], set()).add(r["tipo"])
    ihq = {r["protocolo_id"] for r in db.q(SQL_CON_IHQ)}
    todos = {pid: etiqueta_flujos(ts, pid in ihq) for pid, ts in tipos.items()}
    return todos if not protocolo_ids else {pid: todos[pid] for pid in protocolo_ids if pid in todos}


def miembros_flujo(e):
    return db.q("SELECT * FROM estudios WHERE protocolo_id=? AND tipo=? AND anulado=0 ORDER BY id", (e["protocolo_id"], e["tipo"]))


def variante_de(protocolo_id, tipo):
    r = db.uno(SQL_VARIANTE, (protocolo_id, tipo, protocolo_id, tipo))
    return Variante(r["ihq"], r["decal"])


def flujo_avanzado(protocolo_id, tipo):
    r = db.uno("""SELECT x.etapa FROM etapas x JOIN estudios e ON e.id=x.estudio_id
                  WHERE e.protocolo_id=? AND e.tipo=? AND e.anulado=0 ORDER BY x.fecha_hora DESC, x.id DESC LIMIT 1""", (protocolo_id, tipo))
    return NOMBRE_ETAPA.get(r["etapa"], r["etapa"]) if r else None


def protocolo_cerrado(pid):
    activos = [x for x in cargar_estudios("e.protocolo_id=?", (pid,), borradores=True) if not x["anulado"]]
    return bool(activos) and not any(x["borrador"] or x["proxima"] for x in activos)


def tipos_lote_fijos():
    fijos = listas().get("tipo_lote", [])
    return fijos + [t for e in REGISTRO.values() for t in e.lotes if t not in fijos]


SQL_LISTAS = "SELECT nombre, valor FROM listas ORDER BY nombre, orden"
SQL_VARIANTE = ("SELECT (SELECT 1 FROM micro m JOIN estudios e ON e.id=m.estudio_id "
                "WHERE e.protocolo_id=? AND e.tipo=? AND e.anulado=0 AND m.solicita_ihq=1) AS ihq, "
                "(SELECT 1 FROM macro m JOIN estudios e ON e.id=m.estudio_id "
                "WHERE e.protocolo_id=? AND e.tipo=? AND e.anulado=0 AND m.decal=1) AS decal")
