from datetime import datetime, time, timedelta

from estudios import ETAPAS, REGISTRO


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
    n, d = 0, desde
    while d < hasta:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in feriados:
            n += 1
    return n


JORNADA = (8, 20)


def horas_habiles(desde, hasta, feriados):
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
    dias, hora = REGISTRO[tipo].plazos.get(etapa, (0, 20))
    return datetime.combine(sumar_habiles(_d(base_texto), dias, feriados), time(hora))


def semaforo(limite, ahora, feriados):
    if ahora <= limite:
        return "on_time"
    tope = datetime.combine(sumar_habiles(limite.date(), 1, feriados), limite.time())
    return "late" if ahora >= tope else "delayed"


GRAVEDAD = {"": 0, "on_time": 1, "delayed": 2, "late": 3}


def semaforo_acumulado(tipo, base_texto, completadas, limite_actual, ahora, feriados):
    peor = semaforo(limite_actual, ahora, feriados) if limite_actual else ""
    for etapa, cuando in completadas.items():
        if etapa not in REGISTRO[tipo].plazos:
            continue
        estado = semaforo(limite(tipo, etapa, base_texto, feriados), _dt(cuando), feriados)
        if GRAVEDAD[estado] > GRAVEDAD[peor]:
            peor = estado
    return peor


def calcular(estudio, pasos, etapas, feriados, ahora=None):
    ahora = ahora or datetime.now()
    tipo = REGISTRO[estudio["tipo"]]
    base = _d(estudio["fecha_recoleccion"]) if estudio["fecha_recoleccion"] else _d(estudio["creado_en"])
    completadas = {"ingreso": {"fecha_hora": estudio["creado_en"], "iniciales": estudio["creador"]}}
    completadas.update(etapas)
    filas, proxima_marcada = [], False
    ant_limite = datetime.combine(base, time(JORNADA[0]))
    ant_completada = ant_limite
    for clave in ["ingreso"] + [p[0] for p in pasos]:
        dias, hora = tipo.plazos.get(clave, (0, 20))
        lim = datetime.combine(sumar_habiles(base, dias, feriados), time(hora))
        hecha = completadas.get(clave)
        _, _, proceso, actividad, accion = ETAPAS[clave]
        f = {"clave": clave, "proceso": proceso, "actividad": actividad, "accion": accion, "limite": lim,
             "completada": _dt(hecha["fecha_hora"]) if hecha else None, "usuario": hecha["iniciales"] if hecha else None,
             "estado": "", "atraso": "", "demora": "", "proxima": False}
        referencia = f["completada"] or ahora
        if referencia > lim:
            f["estado"] = "LT"
            f["atraso"] = f"{dias_atraso(lim, referencia, feriados)}d"
            if f["completada"]:
                inicio = max(ant_completada or ant_limite, ant_limite)
                extra = horas_habiles(inicio, f["completada"], feriados) - horas_habiles(ant_limite, lim, feriados)
                if extra >= 0.5:
                    f["demora"] = texto_demora(extra)
        elif f["completada"]:
            f["estado"] = "OT"
        if not hecha and not proxima_marcada:
            f["proxima"] = proxima_marcada = True
        filas.append(f)
        ant_limite, ant_completada = lim, f["completada"]

    ultima = pasos[-1][0]
    estimada = next(f["limite"] for f in filas if f["clave"] == ultima)
    informe = completadas.get(ultima)
    encabezado = {
        "recoleccion": base if estudio["fecha_recoleccion"] else None,
        "base_ingreso": not estudio["fecha_recoleccion"],
        "estimada": estimada.date(),
        "estimada_habiles": tipo.plazos[ultima][0],
        "informe": _dt(informe["fecha_hora"]).date() if informe else None,
        "informe_habiles": habiles_entre(base, _dt(informe["fecha_hora"]).date(), feriados) if informe else None,
    }
    return encabezado, filas


FERIADOS_2026 = [
    ("2026-01-01", "Año Nuevo"), ("2026-02-16", "Carnaval"), ("2026-02-17", "Carnaval"),
    ("2026-03-24", "Día de la Memoria"), ("2026-04-02", "Malvinas"), ("2026-04-03", "Viernes Santo"),
    ("2026-05-01", "Día del Trabajador"), ("2026-05-25", "Revolución de Mayo"), ("2026-06-15", "Paso a la Inmortalidad de Güemes"),
    ("2026-06-20", "Día de la Bandera"), ("2026-07-09", "Día de la Independencia"), ("2026-08-17", "Paso a la Inmortalidad de San Martín"),
    ("2026-10-12", "Diversidad Cultural"), ("2026-11-23", "Soberanía Nacional"), ("2026-12-08", "Inmaculada Concepción"),
    ("2026-12-25", "Navidad"),
]
