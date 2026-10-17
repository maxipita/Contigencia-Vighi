from datetime import date, datetime, timedelta

from vighi.core import db
from vighi.dominio import trazabilidad
from vighi.dominio.estudios import ETAPAS, NOMBRE_ETAPA, SECTORES
from vighi.servicios.consultas import SQL_ETAPAS, SQL_RESPONSABLES
from vighi.servicios.tablero import cargar_protocolos, plazos

VISTAS = [("gerencial", "Gerencial"), ("ingreso", "Ingreso"), ("laboratorio", "Laboratorio"), ("macroscopia", "Macroscopía"),
          ("traslados", "Traslados"), ("citotecnicos", "Citotécnicos"), ("patologos", "Patólogos"), ("performance", "Performance")]
PERMISO_DE = {clave: "dashboard_" + clave for clave, _ in VISTAS}
ETAPAS_DE = {
    "ingreso": [("ingreso", "")],
    "laboratorio": [(k, "") for k, v in ETAPAS.items() if v[1] == "laboratorio"],
    "macroscopia": [("macroscopia", "")],
    "traslados": [(k, "") for k, v in ETAPAS.items() if v[1] == "traslados"],
    "citotecnicos": [("microscopia", "PAP")],
}
ETAPAS_PATOLOGOS = ("microscopia", "interp_ihq", "revision")
ACTIVIDADES = [("ingreso", "Ingreso: Protocolo > Cargar")] + [(k, f"{v[2].capitalize()}: {v[4]}") for k, v in ETAPAS.items() if k != "ingreso"]
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
UNIDADES = {"protocolos": "Protocolos", "estudios": "Estudios"}
SEMANAS_VISTAS = 5
HORAS_DIA = trazabilidad.JORNADA[1] - trazabilidad.JORNADA[0]

SQL_COPIA_EVENTO = """(SELECT COUNT(*) FROM estudios e WHERE e.flujo_id=f.id AND e.anulado=0) AS estudios"""
SQL_EVENTOS = ("SELECT et.flujo_id, et.etapa, et.usuario_id, et.fecha_hora, f.protocolo_id, f.tipo, f.creado_en, p.fecha_recoleccion, p.lugar_recoleccion, "
               "p.lugar_entrega, p.cobertura, u.iniciales, u.nombre, " + SQL_COPIA_EVENTO + " "
               "FROM etapas et JOIN flujos f ON f.id=et.flujo_id JOIN protocolos p ON p.id=f.protocolo_id JOIN usuarios u ON u.id=et.usuario_id "
               "WHERE et.fecha_hora>=? AND p.borrador=0 ORDER BY et.fecha_hora, et.id")
SQL_INGRESOS = ("SELECT f.id AS flujo_id, f.protocolo_id, f.tipo, f.creado_en, f.creado_en AS fecha_hora, p.fecha_recoleccion, p.lugar_recoleccion, p.lugar_entrega, "
                "p.cobertura, p.creado_por AS usuario_id, u.iniciales, u.nombre, " + SQL_COPIA_EVENTO + " "
                "FROM flujos f JOIN protocolos p ON p.id=f.protocolo_id JOIN usuarios u ON u.id=p.creado_por "
                "WHERE f.creado_en>=? AND p.borrador=0 ORDER BY f.creado_en, f.id")
SQL_BORRADORES = "SELECT COUNT(*) AS n FROM protocolos WHERE borrador=1"
SQL_A_VALIDAR = "SELECT COUNT(*) AS n FROM protocolos WHERE pendiente_validacion=1 AND borrador=0"
SQL_COBERTURAS = "SELECT DISTINCT cobertura FROM protocolos WHERE COALESCE(cobertura,'')<>'' ORDER BY cobertura"
SQL_PROTOCOLOS_DE_COBERTURA = "SELECT id FROM protocolos WHERE cobertura=?"
SQL_UBICACIONES = ("SELECT DISTINCT lugar_recoleccion AS lugar FROM protocolos WHERE COALESCE(lugar_recoleccion,'')<>'' "
                   "UNION SELECT DISTINCT lugar_entrega FROM protocolos WHERE COALESCE(lugar_entrega,'')<>''")


def filtros_de(args):
    return {k: args.get(k, "").strip() for k in ("anio", "mes", "tipo", "cobertura", "ubicacion", "actividad", "unidad", "persona")}


def momento(texto):
    return datetime.strptime(texto[:19], "%Y-%m-%d %H:%M:%S")


def horas_entre(antes, despues, feriados):
    if not antes or not despues:
        return None
    return trazabilidad.horas_habiles(momento(antes), momento(despues), feriados)


def texto_demora(horas):
    if horas is None:
        return ""
    return f"{round(horas / HORAS_DIA)}d" if horas >= HORAS_DIA else f"{round(horas)}h"


def periodo(f, hoy):
    anio = int(f["anio"]) if f["anio"].isdigit() and 2000 <= int(f["anio"]) <= 2100 else hoy.year
    mes = int(f["mes"]) if f["mes"].isdigit() and 1 <= int(f["mes"]) <= 12 else hoy.month
    desde = date(anio, mes, 1)
    hasta = date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)
    return {"anio": anio, "mes": mes, "desde": desde, "hasta": hasta, "hasta_efectivo": min(hasta, hoy)}


def habiles(desde, hasta, feriados):
    n, d = 0, desde
    while d <= hasta:
        if d.weekday() < 5 and d not in feriados:
            n += 1
        d += timedelta(days=1)
    return n


def evento(r, etapa, anterior, feriados):
    cuando = momento(r["fecha_hora"])
    return {"flujo": r["flujo_id"], "protocolo": r["protocolo_id"], "tipo": r["tipo"], "etapa": etapa, "usuario": r["usuario_id"], "iniciales": r["iniciales"],
            "nombre": r["nombre"] or r["iniciales"], "cuando": cuando, "dia": cuando.date(), "estudios": r["estudios"], "texto": r["fecha_hora"],
            "base": r["fecha_recoleccion"] or r["creado_en"] or r["fecha_hora"], "lugares": (r["lugar_recoleccion"], r["lugar_entrega"]), "cobertura": r["cobertura"],
            "demora": horas_entre(anterior, r["fecha_hora"], feriados) if anterior else None}


def cargar_eventos(desde):
    feriados = db.feriados()
    por_flujo = {}
    for r in db.q(SQL_ETAPAS):
        por_flujo.setdefault(r["flujo_id"], []).append(r["fecha_hora"])
    eventos = []
    for r in db.q(SQL_EVENTOS, (desde.isoformat(),)):
        previas = [x for x in por_flujo.get(r["flujo_id"], ()) if x < r["fecha_hora"]]
        eventos.append(evento(r, r["etapa"], max(previas) if previas else r["creado_en"], feriados))
    eventos += [evento(r, "ingreso", None, feriados) for r in db.q(SQL_INGRESOS, (desde.isoformat(),))]
    return eventos


def pasa(e, f):
    return ((not f["tipo"] or e["tipo"] == f["tipo"]) and (not f["ubicacion"] or f["ubicacion"] in e["lugares"])
            and (not f["cobertura"] or e["cobertura"] == f["cobertura"]))


def opciones():
    lugares = sorted({r["lugar"] for r in db.q(SQL_UBICACIONES)}, key=db.clave_nombre)
    return {"coberturas": [r["cobertura"] for r in db.q(SQL_COBERTURAS)], "lugares": lugares,
            "anios": list(range(date.today().year, date.today().year - 5, -1)), "meses": list(enumerate(MESES, start=1))}


def cantidad_de(eventos, unidad):
    return len({e["protocolo"] for e in eventos}) if unidad == "protocolos" else sum(e["estudios"] for e in eventos)


def demora_media(eventos):
    horas = [e["demora"] for e in eventos if e["demora"] is not None]
    return sum(horas) / len(horas) if horas else None


def pendientes_por_etapa(protocolos, fechas, etapas, f, feriados, ahora):
    cuenta = {e: {"n": 0, "on_time": 0, "delayed": 0, "late": 0} for e in etapas}
    for p in protocolos.values():
        if f["ubicacion"] and f["ubicacion"] not in (p.lugar_recoleccion, p.lugar_entrega):
            continue
        for m in p.activas():
            if not m.proxima or m.proxima[0] not in etapas or (etapas[m.proxima[0]] and m.tipo != etapas[m.proxima[0]]) or (f["tipo"] and m.tipo != f["tipo"]):
                continue
            plazos(p, m, fechas, feriados, ahora)
            c = cuenta[m.proxima[0]]
            c["n"] += 1
            if m.semaforo:
                c[m.semaforo] += 1
    return cuenta


def sector(vista, f, hoy):
    protocolos, fechas, _ = cargar_protocolos()
    feriados, ahora = db.feriados(), datetime.now()
    etapas = dict(ETAPAS_DE[vista])
    pend = pendientes_por_etapa(protocolos, fechas, {k: v for k, v in etapas.items() if k != "ingreso"}, f, feriados, ahora)
    filas = [{"clave": etapa, "tipo": etapas[etapa], "etapa": NOMBRE_ETAPA[etapa] if etapa != "ingreso" else "Protocolo > Cargar", "pend": pend.get(etapa)} for etapa in etapas]
    extra = []
    if vista == "ingreso":
        extra = [("Protocolos por completar", db.uno(SQL_BORRADORES)["n"]), ("Datos de pacientes por validar", db.uno(SQL_A_VALIDAR)["n"])]
    return {"filas": filas, "extra": extra}


def hay_cobertura(f):
    return {r["id"] for r in db.q(SQL_PROTOCOLOS_DE_COBERTURA, (f["cobertura"],))} if f["cobertura"] else None


def gerencial(f, hoy):
    protocolos, fechas, _ = cargar_protocolos()
    feriados, ahora = db.feriados(), datetime.now()
    de_cobertura = hay_cobertura(f)
    semaforo = {"on_time": 0, "delayed": 0, "late": 0}
    por_sector, por_tipo = {}, {}
    for pid, p in protocolos.items():
        if (de_cobertura is not None and pid not in de_cobertura) or (f["ubicacion"] and f["ubicacion"] not in (p.lugar_recoleccion, p.lugar_entrega)):
            continue
        for m in p.activas():
            if not m.proxima or (f["tipo"] and m.tipo != f["tipo"]):
                continue
            plazos(p, m, fechas, feriados, ahora)
            if m.semaforo:
                semaforo[m.semaforo] += 1
            por_sector[m.proxima[2]] = por_sector.get(m.proxima[2], 0) + 1
            por_tipo[m.tipo] = por_tipo.get(m.tipo, 0) + 1
    return {"pendientes": sum(semaforo.values()), "semaforo": semaforo, "por_tipo": sorted(por_tipo.items()),
            "por_sector": sorted(((k, SECTORES[k], n) for k, n in por_sector.items() if k in SECTORES), key=lambda x: -x[2])}


CAMPOS_PATOLOGOS = ("pend", "p_on_time", "p_delayed", "p_late", "p_hasta_5", "p_de_5_a_10", "p_mas_de_10")


def fila_patologo(iniciales, nombre, tipo):
    return {"iniciales": iniciales, "nombre": nombre, "tipo": tipo, **{k: 0 for k in CAMPOS_PATOLOGOS}}


def sumar_pendientes(filas, etapa, f, nombres, solo_iniciales, feriados, ahora):
    protocolos, fechas, _ = cargar_protocolos()
    de_cobertura = hay_cobertura(f)
    for p in protocolos.values():
        if (de_cobertura is not None and p.id not in de_cobertura) or (f["ubicacion"] and f["ubicacion"] not in (p.lugar_recoleccion, p.lugar_entrega)):
            continue
        for m in p.activas():
            if not m.proxima or m.proxima[0] != etapa or (f["tipo"] and m.tipo != f["tipo"]) or (solo_iniciales and m.responsable != solo_iniciales):
                continue
            plazos(p, m, fechas, feriados, ahora)
            estado = trazabilidad.semaforo(m.vence, ahora, feriados) if m.vence else "on_time"
            iniciales = m.responsable or ""
            fila = filas.setdefault((iniciales, m.tipo), fila_patologo(iniciales, nombres.get(iniciales, "Sin médico asignado"), m.tipo))
            fila["pend"] += 1
            fila["p_" + estado] += 1
            if estado == "late":
                atraso = trazabilidad.dias_atraso(m.vence, ahora, feriados)
                fila["p_hasta_5" if atraso <= 5 else ("p_de_5_a_10" if atraso <= 10 else "p_mas_de_10")] += 1


def patologos(f, hoy, solo_iniciales=None):
    etapa = f["actividad"] if f["actividad"] in ETAPAS_PATOLOGOS else "microscopia"
    feriados, ahora = db.feriados(), datetime.now()
    usuarios = db.q(SQL_RESPONSABLES)
    nombres = {u["iniciales"]: u["nombre"] or u["iniciales"] for u in usuarios}
    filas = {}
    sumar_pendientes(filas, etapa, f, nombres, solo_iniciales, feriados, ahora)
    ordenadas = sorted((x for x in filas.values() if not f["persona"] or x["iniciales"] == f["persona"]), key=lambda x: (x["iniciales"] == "", db.clave_nombre(x["nombre"]), x["tipo"]))
    total = {k: sum(x[k] for x in ordenadas) for k in CAMPOS_PATOLOGOS}
    personas = None if solo_iniciales else [(u["iniciales"], u["nombre"] or u["iniciales"]) for u in usuarios if "firmante" in (u["sectores"] or "").split(",")]
    elegida = next((n for i, n in (personas or []) if i == f["persona"]), "") if f["persona"] else ""
    return {"filas": ordenadas, "total": total, "etapa": etapa, "actividades": [(k, NOMBRE_ETAPA[k]) for k in ETAPAS_PATOLOGOS], "personas": personas, "elegida": elegida}


def ventanas(per):
    def inicio(n):
        total = per["anio"] * 12 + per["mes"] - n
        return date(total // 12, total % 12 + 1, 1)
    anterior_fin = per["desde"] - timedelta(days=1)
    return [(MESES[per["mes"] - 1].upper(), per["desde"], per["hasta"]), (MESES[anterior_fin.month - 1].upper(), anterior_fin.replace(day=1), anterior_fin),
            ("3 MESES", inicio(3), per["hasta"]), ("6 MESES", inicio(6), per["hasta"]), ("12 MESES", inicio(12), per["hasta"])]


def celda(eventos, desde, hasta, unidad, feriados, hoy):
    dentro = [e for e in eventos if desde <= e["dia"] <= hasta]
    dias = habiles(desde, min(hasta, hoy), feriados)
    cantidad = cantidad_de(dentro, unidad)
    promedio = cantidad / dias if dias else 0
    return {"pd": round(promedio), "pad": texto_demora(demora_media(dentro)),
            "detalle": f"Cantidad: {cantidad} · Días hábiles: {dias} · Promedio: {promedio:.2f}".replace(".", ",")}


def semanas_hasta(fin):
    lunes = fin - timedelta(days=fin.weekday())
    return [(lunes - timedelta(days=7 * i), lunes - timedelta(days=7 * i) + timedelta(days=6)) for i in range(SEMANAS_VISTAS)]


def performance(f, hoy):
    per = periodo(f, hoy)
    etapa = f["actividad"] if f["actividad"] in dict(ACTIVIDADES) else "ingreso"
    unidad = f["unidad"] if f["unidad"] in UNIDADES else "protocolos"
    feriados = db.feriados()
    cols = ventanas(per)
    inicio = min(c[1] for c in cols)
    semanas = semanas_hasta(per["hasta_efectivo"] if per["hasta_efectivo"] >= per["desde"] else per["desde"])
    inicio = min([inicio] + [s[0] for s in semanas])
    eventos = [e for e in cargar_eventos(inicio) if e["etapa"] == etapa and pasa(e, f)]
    personas = {}
    for e in eventos:
        personas.setdefault(e["usuario"], {"nombre": e["nombre"], "eventos": []})["eventos"].append(e)
    ordenadas = sorted(personas.values(), key=lambda x: db.clave_nombre(x["nombre"]))
    meses = [{"nombre": p["nombre"], "celdas": [celda(p["eventos"], d, h, unidad, feriados, hoy) for _, d, h in cols]} for p in ordenadas]
    total_meses = [celda(eventos, d, h, unidad, feriados, hoy) for _, d, h in cols]
    por_semana = [{"nombre": p["nombre"], "celdas": [celda(p["eventos"], d, h, unidad, feriados, hoy) for d, h in semanas]} for p in ordenadas]
    total_semanas = [celda(eventos, d, h, unidad, feriados, hoy) for d, h in semanas]
    dias = [per["desde"] + timedelta(days=i) for i in range((per["hasta"] - per["desde"]).days + 1)]
    por_dia = [{"nombre": p["nombre"], "dias": [cantidad_de([e for e in p["eventos"] if e["dia"] == d], unidad) for d in dias]} for p in ordenadas]
    total_dias = [cantidad_de([e for e in eventos if e["dia"] == d], unidad) for d in dias]
    return {"periodo": per, "etapa": etapa, "unidad": unidad, "columnas": [c[0] for c in cols], "meses": meses, "total_meses": total_meses,
            "semanas": [(d.isocalendar()[1], d.isoformat()) for d, _ in semanas], "por_semana": por_semana, "total_semanas": total_semanas,
            "dias": [d.day for d in dias], "por_dia": por_dia, "total_dias": total_dias, "actividades": ACTIVIDADES, "unidades": UNIDADES}
