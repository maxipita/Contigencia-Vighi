"""Trazabilidad de un protocolo: fecha límite de cada etapa (días hábiles desde la recolección, igual que
southernbits), fecha completada, usuario y si se cumplió a tiempo (OT) o tarde (LT)."""
from datetime import date, datetime, time, timedelta

# etapa -> (proceso, actividad, acción) tal como los muestra el sistema
ETIQUETAS = {
    "ingreso": ("INGRESO", "Cargar protocolo", "Protocolo > Cargar"),
    "macroscopia": ("DIAGNÓSTICOS", "Macroscopía", "Macro > Informar"),
    "procesamiento": ("LABORATORIO", "Procesamiento", "Histo > Procesar"),
    "inclusion": ("LABORATORIO", "Inclusión", "Cassette > Incluir"),
    "corte": ("LABORATORIO", "Corte PH", "Taco > Cortar"),
    "coloreado": ("LABORATORIO", "Coloreado", "Porta > Colorear"),
    "citotecnicos": ("TRASLADOS", "Citotécnicos", "Cito > Informar"),
    "microscopia": ("DIAGNÓSTICOS", "Microscopía", "Micro > Informar"),
    "corte_ihq": ("LABORATORIO", "Corte PH", "Taco IHQ > Cortar"),
    "envio_ihq": ("TRASLADOS", "Laboratorio", "Lab Ext > Procesar"),
    "proc_ihq": ("LABORATORIO", "Procesamiento", "IHQ > Procesar"),
    "interp_ihq": ("DIAGNÓSTICOS", "Microscopía", "Micro > Interpretar"),
}

# Plazos: (días hábiles desde la recolección, hora límite). Sacados de las capturas del sistema.
PLAZOS = {
    "BP": {"ingreso": (1, 20), "macroscopia": (2, 20), "procesamiento": (3, 20), "inclusion": (3, 20),
           "corte": (4, 20), "coloreado": (5, 20), "microscopia": (6, 20),
           "corte_ihq": (7, 20), "envio_ihq": (8, 18), "proc_ihq": (9, 20), "interp_ihq": (13, 20)},
    "PAP": {"ingreso": (1, 20), "coloreado": (2, 20), "citotecnicos": (3, 18), "microscopia": (4, 20)},
    "CT": {"ingreso": (1, 20), "coloreado": (2, 20), "microscopia": (3, 20)},
}


def _d(texto):
    return datetime.strptime(texto[:10], "%Y-%m-%d").date()


def _dt(texto):
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")


def sumar_habiles(desde, n, feriados):
    d = desde
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in feriados:
            n -= 1
    return d


def habiles_entre(desde, hasta, feriados):
    """Días hábiles transcurridos de 'desde' a 'hasta' (sin contar el día de inicio)."""
    n, d = 0, desde
    while d < hasta:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in feriados:
            n += 1
    return n


JORNADA = (8, 20)          # horario hábil: 12 hs por día hábil


def horas_habiles(desde, hasta, feriados):
    """Horas hábiles (08 a 20 hs, días hábiles) entre dos momentos."""
    if hasta <= desde:
        return 0.0
    total, d = 0.0, desde.date()
    while d <= hasta.date():
        if d.weekday() < 5 and d not in feriados:
            ini = max(desde, datetime.combine(d, time(JORNADA[0])))
            fin = min(hasta, datetime.combine(d, time(JORNADA[1])))
            if fin > ini:
                total += (fin - ini).total_seconds() / 3600
        d += timedelta(days=1)
    return total


def dias_atraso(limite, referencia, feriados):
    """Cierres hábiles vencidos después del límite (mínimo 1 si está atrasado), como 'LT 1d' del sistema."""
    k = 0
    while datetime.combine(sumar_habiles(limite.date(), k + 1, feriados), limite.time()) <= referencia:
        k += 1
    return max(k, 1)


def texto_demora(horas):
    horas = int(round(horas))
    d, h = divmod(horas, JORNADA[1] - JORNADA[0])
    partes = (f"+{d}d {h}h" if d else f"+{h}h")
    return f"{partes} ({horas}hs)"


def limite(tipo, etapa, base_texto, feriados):
    """Fecha límite de una etapa a partir de la fecha de recolección (o de ingreso) en texto."""
    dias, hora = PLAZOS[tipo].get(etapa, (0, 20))
    return datetime.combine(sumar_habiles(_d(base_texto), dias, feriados), time(hora))


def calcular(caso, pasos, etapas, feriados, ahora=None):
    """caso: fila de casos; pasos: [(clave, nombre, sector)] del flujo; etapas: {clave: fila con fecha_hora/iniciales}.
    Devuelve (encabezado, filas)."""
    ahora = ahora or datetime.now()
    tipo = caso["tipo"]
    base = _d(caso["fecha_recoleccion"]) if caso["fecha_recoleccion"] else _d(caso["creado_en"])
    completadas = {"ingreso": {"fecha_hora": caso["creado_en"], "iniciales": caso["creador"]}}
    completadas.update({k: v for k, v in etapas.items()})
    filas, proxima_marcada = [], False
    ant_limite = datetime.combine(base, time(JORNADA[0]))    # la etapa anterior a la primera: la recolección
    ant_completada = ant_limite
    for clave in ["ingreso"] + [p[0] for p in pasos]:
        dias, hora = PLAZOS[tipo].get(clave, (0, 20))
        limite = datetime.combine(sumar_habiles(base, dias, feriados), time(hora))
        hecha = completadas.get(clave)
        proceso, actividad, accion = ETIQUETAS[clave]
        f = {"clave": clave, "proceso": proceso, "actividad": actividad, "accion": accion, "limite": limite,
             "completada": _dt(hecha["fecha_hora"]) if hecha else None, "usuario": hecha["iniciales"] if hecha else None,
             "estado": "", "atraso": "", "demora": "", "proxima": False}
        referencia = f["completada"] or ahora
        if referencia > limite:
            f["estado"] = "LT"
            f["atraso"] = f"{dias_atraso(limite, referencia, feriados)}d"
            if f["completada"]:
                # horas hábiles que llevó la etapa (desde que la anterior estuvo disponible) menos las permitidas
                inicio = max(ant_completada or ant_limite, ant_limite)
                extra = horas_habiles(inicio, f["completada"], feriados) - horas_habiles(ant_limite, limite, feriados)
                if extra >= 0.5:
                    f["demora"] = texto_demora(extra)
        elif f["completada"]:
            f["estado"] = "OT"
        if not hecha and not proxima_marcada:
            f["proxima"] = proxima_marcada = True
        filas.append(f)
        ant_limite, ant_completada = limite, f["completada"]

    ultima = "interp_ihq" if "interp_ihq" in [p[0] for p in pasos] else "microscopia"
    estimada = next(f["limite"] for f in filas if f["clave"] == ultima)
    informe = completadas.get(ultima)
    encabezado = {
        "recoleccion": base if caso["fecha_recoleccion"] else None,
        "base_ingreso": not caso["fecha_recoleccion"],
        "estimada": estimada.date(),
        "estimada_habiles": PLAZOS[tipo][ultima][0],
        "informe": _dt(informe["fecha_hora"]).date() if informe else None,
        "informe_habiles": habiles_entre(base, _dt(informe["fecha_hora"]).date(), feriados) if informe else None,
    }
    return encabezado, filas


# Feriados nacionales de Argentina 2026 (trasladables ya movidos). VERIFICAR con el calendario oficial;
# se pueden editar desde la pantalla Feriados.
FERIADOS_2026 = [
    ("2026-01-01", "Año Nuevo"), ("2026-02-16", "Carnaval"), ("2026-02-17", "Carnaval"),
    ("2026-03-24", "Día de la Memoria"), ("2026-04-02", "Malvinas"), ("2026-04-03", "Viernes Santo"),
    ("2026-05-01", "Día del Trabajador"), ("2026-05-25", "Revolución de Mayo"), ("2026-06-15", "Paso a la Inmortalidad de Güemes"),
    ("2026-06-20", "Día de la Bandera"), ("2026-07-09", "Día de la Independencia"), ("2026-08-17", "Paso a la Inmortalidad de San Martín"),
    ("2026-10-12", "Diversidad Cultural"), ("2026-11-23", "Soberanía Nacional"), ("2026-12-08", "Inmaculada Concepción"),
    ("2026-12-25", "Navidad"),
]
