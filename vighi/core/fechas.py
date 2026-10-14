from datetime import datetime


def fecha_hora(v):
    if not v:
        return ""
    try:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return v


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def fecha_larga(d):
    return f"{d.day} {MESES[d.month - 1]} {d.year}" if d else ""


def edad(v):
    try:
        n = datetime.strptime(v, "%Y-%m-%d")
    except (TypeError, ValueError):
        return ""
    hoy = datetime.now()
    return f"{hoy.year - n.year - ((hoy.month, hoy.day) < (n.month, n.day))} ({n.year})"


def fecha_hora_dt(d):
    return d.strftime("%d/%m/%Y %H:%M hs") if d else ""


def fecha(v):
    if not v:
        return ""
    try:
        return datetime.strptime(v, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return v


def hoy():
    return datetime.now().strftime("%Y-%m-%d")


def peso(v):
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return ""
    texto = f"{abs(n):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if n < 0 else "") + "$ " + texto


def peso_entero(v):
    try:
        n = round(float(v or 0))
    except (TypeError, ValueError):
        return ""
    return ("-" if n < 0 else "") + "$ " + f"{abs(n):,}".replace(",", ".")


MESES_CORTOS = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
