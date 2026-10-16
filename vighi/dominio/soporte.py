import csv
import io
from collections import Counter
from datetime import date, datetime

from vighi.core.texto import sin_acentos

COLUMNAS = {
    "fecha": "fecha", "protocolo": "protocolo", "descripcion": "estudio", "paciente": "paciente", "nrocredencial": "afiliado", "afiliado": "afiliado",
    "nomenclador": "codigo", "unidades": "cantidad", "cantidad": "cantidad", "neto": "neto", "cond.iva": "condicion_iva", "condiva": "condicion_iva",
    "iva": "iva", "bruto": "bruto", "cobertura": "cobertura",
}
OBLIGATORIAS = ("fecha", "protocolo", "paciente", "codigo")
MAX_FILAS = 5000
MAX_ERRORES = 8


def decodificar(contenido):
    if contenido[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return contenido.decode("utf-16")
    if b"\x00" in contenido[:200]:
        return contenido.decode("utf-16-le", errors="replace")
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("cp1252", errors="replace")


def filas_csv(contenido):
    texto = decodificar(contenido).lstrip("﻿")
    primera = texto.split("\n", 1)[0]
    return list(csv.reader(io.StringIO(texto), delimiter=";" if primera.count(";") >= primera.count(",") else ","))


def filas_xlsx(contenido):
    import openpyxl
    libro = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    return [list(f) for f in libro.worksheets[0].iter_rows(values_only=True)]


def numero(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip().replace("$", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.rsplit(".", 1)[1]) == 3):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def fecha_iso(valor):
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    s = str(valor or "").strip().split(" ")[0]
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, formato).date().isoformat()
        except ValueError:
            continue
    return None


def texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return " ".join(str(valor).split())


def leer_soporte(nombre, contenido):
    nombre = (nombre or "").lower()
    try:
        if nombre.endswith((".xlsx", ".xlsm")):
            crudas = filas_xlsx(contenido)
        elif nombre.endswith((".csv", ".txt")):
            crudas = filas_csv(contenido)
        else:
            return None, ["Subí el soporte como Excel (.xlsx) o CSV."]
    except Exception:
        return None, ["No se pudo leer el archivo: no parece un Excel ni un CSV válido."]
    crudas = [f for f in crudas if any(c not in (None, "") for c in f)]
    if not crudas:
        return None, ["El archivo está vacío."]
    encabezado = {}
    for i, c in enumerate(crudas[0]):
        clave = COLUMNAS.get(sin_acentos(texto(c)).lower().replace(" ", ""))
        if clave and clave not in encabezado:
            encabezado[clave] = i
    faltan = [c for c in OBLIGATORIAS if c not in encabezado]
    if faltan or ("neto" not in encabezado and "bruto" not in encabezado):
        return None, ["Faltan columnas en el soporte: " + ", ".join(faltan + ([] if "neto" in encabezado or "bruto" in encabezado else ["Neto o Bruto"])) + "."]
    filas, errores, coberturas = [], [], Counter()

    def celda(f, clave):
        i = encabezado.get(clave)
        return f[i] if i is not None and i < len(f) else None

    for n, f in enumerate(crudas[1:], start=2):
        if not texto(celda(f, "protocolo")):
            continue
        if len(filas) >= MAX_FILAS:
            return None, [f"El soporte tiene más de {MAX_FILAS} filas."]
        problemas = []
        fecha = fecha_iso(celda(f, "fecha"))
        neto, bruto, iva = numero(celda(f, "neto")), numero(celda(f, "bruto")), numero(celda(f, "iva")) or 0.0
        importe = neto if neto is not None else (bruto - iva if bruto is not None else None)
        cantidad = numero(celda(f, "cantidad"))
        cantidad = int(round(cantidad)) if cantidad and cantidad >= 1 else 1
        if not fecha:
            problemas.append("fecha inválida")
        if importe is None:
            problemas.append("sin importe")
        if not texto(celda(f, "paciente")):
            problemas.append("sin paciente")
        if problemas:
            if len(errores) < MAX_ERRORES:
                errores.append(f"Fila {n} (protocolo {texto(celda(f, 'protocolo'))}): " + ", ".join(problemas) + ".")
            continue
        gravado = iva > 0 or texto(celda(f, "condicion_iva")).lower().startswith("grav")
        filas.append({"fecha": fecha, "protocolo": texto(celda(f, "protocolo")), "estudio": texto(celda(f, "estudio")), "paciente": texto(celda(f, "paciente")),
                      "afiliado": texto(celda(f, "afiliado")), "codigo": texto(celda(f, "codigo")), "cantidad": cantidad,
                      "unitario": round(importe / cantidad, 2), "iva": "gravado" if gravado else "exento", "importe": round(importe, 2)})
        coberturas[texto(celda(f, "cobertura"))] += 1
    if errores:
        return None, errores + ["No se cargó nada: corregí el archivo y volvé a subirlo."]
    if not filas:
        return None, ["El soporte no tiene filas con número de protocolo."]
    cobertura = coberturas.most_common(1)[0][0] if coberturas else ""
    return {"filas": filas, "cobertura": cobertura}, []


def resumen(filas):
    fechas = [f["fecha"] for f in filas]
    return {"filas": len(filas), "protocolos": len({f["protocolo"] for f in filas}), "total": round(sum(f["importe"] for f in filas), 2),
            "desde": min(fechas) if fechas else "", "hasta": max(fechas) if fechas else ""}
