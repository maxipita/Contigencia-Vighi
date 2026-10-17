from datetime import datetime
from math import ceil

from vighi.core import db
from vighi.core.config import SEMAFOROS
from vighi.dominio import informes, trazabilidad
from vighi.dominio.estudios import GINECOLOGICA, REGISTRO, SECTORES, Variante, sector_marca
from vighi.servicios.consultas import SQL_CON_DECAL, SQL_CON_IHQ, SQL_ETAPAS, SQL_RESPONSABLES, SQL_SIN_REVISION, etiqueta_flujos
from vighi.servicios.lotes import orden_numero
from vighi.servicios.mensajeria import MALIGNIDADES

POR_PAGINA = 100
CLASES_BIOPSIA = ("Dermatológicas", "Ginecológicas", "Quirúrgicas")
DIAGNOSTICOS = (("con", "Con diagnóstico"), ("sin", "Sin diagnóstico")) + tuple(MALIGNIDADES)

SQL_TABLERO = """SELECT e.protocolo_id, e.flujo_id, e.tipo, e.subcategoria, e.sitio, e.tipo_muestra, e.anulado, e.creado_en, e.lote_id, e.malignidad,
                        p.numero, p.apellido, p.nombre, p.dni, p.fecha_recoleccion, p.cargado_sistema, p.pendiente_validacion, p.lugar_recoleccion, p.lugar_entrega,
                        p.cobertura, p.plan, p.medico, u.iniciales, l.codigo, l.tipo_lote
                 FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                 LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                 WHERE p.borrador=0 ORDER BY p.id DESC, e.id"""

SQL_DIAGNOSTICO = """SELECT f.protocolo_id, f.tipo FROM micro m JOIN flujos f ON f.id=m.flujo_id
                      WHERE m.conclusion LIKE ? OR m.resultado LIKE ? OR m.bethesda LIKE ?"""


def consultas_tablero():
    return [(SQL_TABLERO, ()), (SQL_ETAPAS, ()), (SQL_CON_IHQ, ()), (SQL_CON_DECAL, ()), (SQL_SIN_REVISION, ()), (SQL_RESPONSABLES, ())]


class Muestra:
    __slots__ = ("flujo_id", "tipo", "subcategoria", "sitio", "tipo_muestra", "anulado", "creado_en", "responsable", "lote", "tipo_lote", "malignidad",
                 "decal", "ihq", "estado", "proxima", "vence", "semaforo")


class Protocolo:
    __slots__ = ("id", "numero", "apellido", "nombre", "dni", "fecha_recoleccion", "cargado_sistema", "validar", "lugar_recoleccion", "lugar_entrega",
                 "cobertura", "plan", "medico", "lote_id", "lote", "muestras", "ingreso")

    def activas(self):
        return [m for m in self.muestras if not m.anulado]


def cargar_protocolos():
    db.precargar(consultas_tablero())
    fechas = {}
    for r in db.q(SQL_ETAPAS):
        fechas.setdefault(r["flujo_id"], {})[r["etapa"]] = r["fecha_hora"]
    con_ihq = {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_CON_IHQ)}
    con_decal = {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_CON_DECAL)}
    sin_revision = {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_SIN_REVISION)}
    protocolos, por_flujo = {}, {}
    for (pid, flujo_id, tipo, subcategoria, sitio, tipo_muestra, anulado, creado_en, lote_id, malignidad, numero, apellido, nombre, dni, fecha_recoleccion,
         cargado_sistema, validar, lugar_recoleccion, lugar_entrega, cobertura, plan, medico, responsable, lote, tipo_lote) in db.q(SQL_TABLERO):
        p = protocolos.get(pid)
        if p is None:
            p = protocolos[pid] = Protocolo()
            p.id, p.numero, p.apellido, p.nombre, p.dni, p.fecha_recoleccion = pid, numero, apellido, nombre, dni, fecha_recoleccion
            p.cargado_sistema, p.validar, p.lugar_recoleccion, p.lugar_entrega = cargado_sistema, validar, lugar_recoleccion, lugar_entrega
            p.cobertura, p.plan, p.medico = cobertura, plan, medico
            p.lote_id, p.lote, p.muestras, p.ingreso = lote_id, lote, [], creado_en
        elif creado_en < p.ingreso:
            p.ingreso = creado_en
        m = Muestra()
        m.flujo_id, m.tipo, m.subcategoria, m.sitio, m.tipo_muestra, m.anulado = flujo_id, tipo, subcategoria, sitio, tipo_muestra, bool(anulado)
        m.creado_en, m.responsable, m.lote, m.vence, m.semaforo = creado_en, responsable, lote, None, None
        m.tipo_lote, m.malignidad = tipo_lote, malignidad
        m.decal = (pid, tipo) in con_decal
        m.ihq = (pid, tipo) in con_ihq
        if m.anulado:
            m.estado, m.proxima = "ANULADO", None
        else:
            clave = (flujo_id, pid, tipo)
            if clave not in por_flujo:
                por_flujo[clave] = REGISTRO[tipo].estado(fechas.get(flujo_id, ()), Variante((pid, tipo) in con_ihq, m.decal, (pid, tipo) not in sin_revision), False)
            m.estado, m.proxima = por_flujo[clave]
        p.muestras.append(m)
    return protocolos, fechas, {pid for pid, _ in con_ihq}


def plazos(p, m, fechas, feriados, ahora):
    if m.semaforo is not None:
        return
    m.vence, m.semaforo = None, ""
    if m.proxima:
        base = p.fecha_recoleccion or m.creado_en
        m.vence = trazabilidad.limite(m.tipo, m.proxima[0], base, feriados, m.decal, m.ihq)
        m.semaforo = trazabilidad.semaforo_acumulado(m.tipo, base, {"ingreso": m.creado_en, **fechas.get(m.flujo_id, {})}, m.vence, ahora, feriados, m.decal, m.ihq)


def pagina_pedida(texto):
    return int(texto) if texto and len(texto) < 9 and texto.isascii() and texto.isdigit() else 1


def clase_biopsia(subcategoria):
    if not subcategoria:
        return ""
    return "Dermatológicas" if subcategoria == "Dermatológica" else ("Ginecológicas" if subcategoria == GINECOLOGICA else "Quirúrgicas")


def coincidencias_diagnostico(texto):
    limpio = texto.replace("%", "").replace("_", "").strip()
    if not limpio:
        return None
    patron = f"%{limpio}%"
    return {(r["protocolo_id"], r["tipo"]) for r in db.q(SQL_DIAGNOSTICO, (patron, patron, patron))}


def del_protocolo(p, f, firmante):
    ingreso = p.ingreso[:10]
    return not (
        (f.get("ubicacion") and f["ubicacion"] not in (p.lugar_recoleccion, p.lugar_entrega))
        or (f.get("mf") and f["mf"] != firmante)
        or (f.get("medico") and f["medico"].lower() not in (p.medico or "").lower())
        or (f.get("cobertura") and f["cobertura"] != p.cobertura)
        or (f.get("plan") and f["plan"] != p.plan)
        or (f.get("anio") and f["anio"] != ingreso[:4])
        or (f.get("mes") and f["mes"] != ingreso[5:7])
        or (f.get("dia") and f["dia"] != ingreso[8:10])
        or (f.get("desde") and ingreso < f["desde"])
        or (f.get("hasta") and ingreso > f["hasta"]))


def del_estudio(m, pid, f, fechas, coinciden):
    if f.get("tipo") and m.tipo != f["tipo"]:
        return False
    if f.get("sector") and not (m.proxima and m.proxima[2] == f["sector"]):
        return False
    if f.get("etapa") and not (m.proxima and m.proxima[0] == f["etapa"]):
        return False
    if (f.get("zona") and m.subcategoria != f["zona"]) or (f.get("organo") and m.sitio != f["organo"]):
        return False
    if (f.get("biopsia") and clase_biopsia(m.subcategoria) != f["biopsia"]) or (f.get("lote") and m.tipo_lote != f["lote"]):
        return False
    d = f.get("diagnostico")
    if d in ("con", "sin") and ("microscopia" in fechas.get(m.flujo_id, ())) != (d == "con"):
        return False
    if d and d not in ("con", "sin") and m.malignidad != d:
        return False
    return coinciden is None or (pid, m.tipo) in coinciden


def opciones(protocolos, f):
    def con(valores, elegido):
        return sorted({v for v in valores if v} | ({elegido} if elegido else set()), key=db.clave_nombre)
    muestras = [m for p in protocolos.values() for m in p.muestras]
    return {"coberturas": con((p.cobertura for p in protocolos.values()), f.get("cobertura")),
            "planes": con((p.plan for p in protocolos.values() if not f.get("cobertura") or p.cobertura == f["cobertura"]), f.get("plan")),
            "zonas": con((m.subcategoria for m in muestras), f.get("zona")),
            "organos": con((m.sitio for m in muestras if not f.get("zona") or m.subcategoria == f["zona"]), f.get("organo")),
            "tipos_lote": con((m.tipo_lote for m in muestras), f.get("lote")),
            "anios": sorted({p.ingreso[:4] for p in protocolos.values()} | ({f["anio"]} if f.get("anio") else set()), reverse=True),
            "lugares": con((l for p in protocolos.values() for l in (p.lugar_recoleccion, p.lugar_entrega)), f.get("ubicacion"))}


def armar(f, sectores, pagina=1, por_pagina=POR_PAGINA, propios=None):
    protocolos, fechas, con_ihq = cargar_protocolos()
    usuarios = db.q(SQL_RESPONSABLES)
    firmantes = [u for u in usuarios if "firmante" in (u["sectores"] or "").split(",")]
    iniciales_firmantes = {u["iniciales"] for u in firmantes}
    pap = next((u for u in usuarios if informes.FIRMANTE_PAP in (u["nombre"] or "").lower()), None)
    feriados, ahora = db.feriados(), datetime.now()
    mis = set(sectores)

    def firmante_de(p):
        activas = p.activas()
        if pap and activas and all(m.tipo == "PAP" for m in activas):
            return pap["iniciales"]
        return next((m.responsable for m in activas if m.responsable in iniciales_firmantes), "")

    if propios:
        protocolos = {pid: p for pid, p in protocolos.items() if firmante_de(p) == propios or any(m.responsable == propios for m in p.activas())}

    conteo = {"pendientes": 0, "informados": 0, "sin_cargar": 0}
    for p in protocolos.values():
        activas = p.activas()
        if any(m.proxima for m in activas):
            conteo["pendientes"] += 1
        elif activas:
            conteo["informados"] += 1
            if not p.cargado_sistema:
                conteo["sin_cargar"] += 1

    def del_ver(p):
        activas = p.activas()
        pendientes = [m for m in activas if m.proxima]
        v = f["ver"]
        if v == "pendientes":
            return bool(pendientes)
        if v == "mios":
            return any(sector_marca(mis, m.tipo, m.proxima[0], m.proxima[2]) for m in pendientes)
        if v == "informados":
            return bool(activas) and not pendientes
        if v == "sin_cargar":
            return bool(activas) and not pendientes and not p.cargado_sistema
        if v == "anulados":
            return not activas
        return True

    def con_texto(p):
        q = f["q"].lower()
        return any(q in " ".join(str(x or "") for x in (p.numero, p.apellido, p.nombre, p.dni, m.lote, m.sitio)).lower() for m in p.muestras)

    coinciden = coincidencias_diagnostico(f.get("kwd", ""))
    candidatos = []
    for p in protocolos.values():
        if not del_ver(p) or (f["q"] and not con_texto(p)) or not del_protocolo(p, f, firmante_de(p)):
            continue
        elegidas = [m for m in p.muestras if del_estudio(m, p.id, f, fechas, coinciden)]
        if f["ver"] == "anulados":
            vista = [m for m in elegidas if m.anulado]
        elif f["ver"] in ("pendientes", "mios"):
            vista = [m for m in elegidas if not m.anulado and m.proxima and (f["ver"] != "mios" or sector_marca(mis, m.tipo, m.proxima[0], m.proxima[2]))]
        else:
            vista = [m for m in elegidas if not m.anulado] or elegidas
        if not vista:
            continue
        for m in vista:
            plazos(p, m, fechas, feriados, ahora)
        semaforo = max((m.semaforo for m in vista), key=lambda s: trazabilidad.GRAVEDAD[s or ""])
        candidatos.append(((p.ingreso, orden_numero(p.numero), p.id), p, vista, semaforo))
    candidatos.sort(key=lambda c: c[0])
    por_semaforo = {k: sum(1 for c in candidatos if c[3] == k) for k in SEMAFOROS}
    if f["semaforo"]:
        candidatos = [c for c in candidatos if c[3] == f["semaforo"]]

    total = len(candidatos)
    paginas = max(1, ceil(total / por_pagina))
    pagina = min(max(1, pagina), paginas)
    desde = (pagina - 1) * por_pagina
    filas = []
    for _, p, vista, semaforo in candidatos[desde:desde + por_pagina]:
        activas = p.activas() or p.muestras
        vencen = [m.vence for m in vista if m.vence]
        filas.append({
            "protocolo_id": p.id, "numero": p.numero, "flujos": etiqueta_flujos({m.tipo for m in activas}, p.id in con_ihq),
            "estudios": len(activas),
            "apellido": p.apellido, "nombre": p.nombre, "dni": p.dni, "validar": p.validar,
            "muestras": list(dict.fromkeys((m.subcategoria or "", m.tipo_muestra or "") for m in vista)),
            "lote_id": p.lote_id, "lote": p.lote,
            "responsables": list(dict.fromkeys(m.responsable for m in vista if m.responsable)),
            "estados": list(dict.fromkeys((m.estado, SECTORES[m.proxima[2]] if m.proxima else "", m.anulado, not m.proxima) for m in vista)),
            "semaforo": semaforo, "vence": min(vencen) if vencen else None, "creado_en": p.ingreso})
    return {"filas": filas, "conteo": conteo, "por_semaforo": por_semaforo, "firmantes": firmantes, **opciones(protocolos, f),
            "pagina": pagina, "paginas": paginas, "total": total, "primera": desde + 1 if total else 0, "ultima": desde + len(filas), "por_pagina": por_pagina}
