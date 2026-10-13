import csv
import io
import re

COLUMNAS = ("abreviatura", "nombre", "direccion", "medicos", "telefonos")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


class ErrorArchivo(ValueError):
    pass


def emails_de(texto):
    return list(dict.fromkeys(e.lower() for e in EMAIL.findall(texto or "")))


def decodificar(contenido):
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("cp1252", errors="replace")


def leer_csv(contenido):
    lector = csv.DictReader(io.StringIO(decodificar(contenido)))
    faltan = [c for c in COLUMNAS if c not in (lector.fieldnames or [])]
    if faltan:
        raise ErrorArchivo(f"Al archivo le faltan las columnas: {', '.join(faltan)}. Tiene que tener: {', '.join(COLUMNAS)}.")
    por_nombre = {}
    for r in lector:
        abreviatura = (r["abreviatura"] or "").strip()
        if not abreviatura:
            continue
        medicos = [m.strip() for m in (r["medicos"] or "").split(" | ") if m.strip()]
        contactos = (r["telefonos"] or "").strip()
        de_informes = (r.get("emails_informes") or "").strip()
        sueltos = [s for s in re.split(r"\s*\|\s*", de_informes) if re.sub(r"[\s;,()]+", "", EMAIL.sub("", s))]
        extra = " / ".join(s for s in sueltos if s not in contactos)
        contactos = f"{contactos} / {extra}" if contactos and extra else (contactos or extra)
        u = por_nombre.setdefault(abreviatura, {"abreviatura": abreviatura, "nombre": "", "direccion": "", "contactos": "", "emails_informes": "", "medicos": []})
        u["emails_informes"] = f"{u['emails_informes']} {de_informes}".strip()
        u["nombre"] = u["nombre"] or (r["nombre"] or "").strip()
        u["direccion"] = u["direccion"] or (r["direccion"] or "").strip()
        if contactos and contactos not in u["contactos"]:
            u["contactos"] = f"{u['contactos']} / {contactos}" if u["contactos"] else contactos
        u["medicos"] = list(dict.fromkeys(u["medicos"] + medicos))
    for u in por_nombre.values():
        u["emails"] = ", ".join(emails_de(u["emails_informes"] + " " + u["contactos"]))
    return list(por_nombre.values())
