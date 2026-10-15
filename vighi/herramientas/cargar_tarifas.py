import argparse
import collections
import json
import sys

from vighi import crear_app
from vighi.core import db
from vighi.core.texto import sin_acentos

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}


def fecha_iso(texto):
    d, m, a = texto.replace(".", "").split()
    return f"20{a}-{MESES[m[:3].lower()]:02d}-{int(d):02d}"


def dias_de(texto):
    digitos = "".join(ch for ch in (texto or "") if ch.isdigit())
    return int(digitos) if digitos and "día" in (texto or "") else None


def tarifas_del_paquete(datos):
    extra = datos.get("planes_extra", {})
    salida = []
    for c in datos["coberturas"]:
        propias = extra.get(str(c["id"]), {})
        iva = "exento" if "siempre exento" in sin_acentos(c.get("iva", "")) else "gravado"
        dias = dias_de(c.get("cond"))
        base = propias["0"]["items"] if "0" in propias else c["items"]
        salida.append({"cobertura": c["nombre"], "plan": "", "iva": iva, "dias": dias, "items": base})
        for p in c.get("planes", []):
            if p["v"] != "0" and p["v"] in propias:
                salida.append({"cobertura": c["nombre"], "plan": p["t"].upper(), "iva": iva, "dias": None, "items": propias[p["v"]]["items"]})
    for t in salida:
        vistos, unicos, repetidos = set(), [], []
        for i in t["items"]:
            i["fecha"] = i.get("fecha") or fecha_iso(i["desde"])
            clave = (i["cod"], i["fecha"])
            (repetidos if clave in vistos else unicos).append(i)
            vistos.add(clave)
        t["items"], t["repetidos"] = unicos, repetidos
    return salida


def descripciones_generales(tarifas):
    cuenta = collections.defaultdict(collections.Counter)
    for t in tarifas:
        for i in t["items"]:
            if i["desc"]:
                cuenta[i["cod"]][i["desc"]] += 1
    return {cod: c.most_common(1)[0][0] for cod, c in cuenta.items()}


def trozos(lista, n):
    for i in range(0, len(lista), n):
        yield lista[i:i + n]


def aplicar(tarifas, imprimir=print):
    reales = {sin_acentos(r["valor"]): r["valor"] for r in db.q("SELECT valor FROM listas WHERE nombre='cobertura'")}
    generales = descripciones_generales(tarifas)
    existentes = {r["codigo"]: r["descripcion"] for r in db.q("SELECT codigo, descripcion FROM nomencladores")}
    nuevos = [(c, d) for c, d in generales.items() if c not in existentes]
    sentencias = [("INSERT INTO nomencladores (codigo, descripcion) VALUES (?,?)", n) for n in nuevos]
    sentencias += [("UPDATE nomencladores SET descripcion=? WHERE codigo=?", (generales[c], c)) for c, d in existentes.items() if not d and c in generales]
    for trozo in trozos(sentencias, 40):
        db.lote_ex(trozo)
    omitidas, cargadas, valores_total, planes = [], 0, 0, 0
    for t in tarifas:
        cobertura = reales.get(sin_acentos(t["cobertura"]))
        if not cobertura:
            omitidas.append(t["cobertura"])
            continue
        nombre = cobertura.upper() + (f" · {t['plan']}" if t["plan"] else "")
        fila = db.uno("SELECT tarifario_id FROM tarifario_coberturas WHERE cobertura=? AND plan=?", (cobertura, t["plan"]))
        if fila:
            tid = fila["tarifario_id"]
        else:
            if not db.uno("SELECT 1 FROM tarifarios WHERE nombre=?", (nombre,)):
                db.ex("INSERT INTO tarifarios (nombre, iva) VALUES (?,?)", (nombre, t["iva"]))
            tid = db.uno("SELECT id FROM tarifarios WHERE nombre=?", (nombre,))["id"]
            db.lote_ex([("DELETE FROM tarifario_coberturas WHERE cobertura=? AND plan=?", (cobertura, t["plan"])),
                        ("INSERT INTO tarifario_coberturas (cobertura, plan, tarifario_id) VALUES (?,?,?)", (cobertura, t["plan"], tid))])
        db.ex("UPDATE tarifarios SET iva=? WHERE id=?", (t["iva"], tid))
        actuales = {(r["codigo"], r["vigente_desde"]): r["importe"] for r in db.q("SELECT codigo, vigente_desde, importe FROM tarifario_valores WHERE tarifario_id=?", (tid,))}
        sentencias = []
        a_insertar = []
        for i in t["items"]:
            clave = (i["cod"], i["fecha"])
            if clave in actuales:
                if abs(actuales[clave] - i["imp"]) > 0.005:
                    sentencias.append(("UPDATE tarifario_valores SET importe=? WHERE tarifario_id=? AND codigo=? AND vigente_desde=?", (i["imp"], tid, i["cod"], i["fecha"])))
                continue
            a_insertar.append((tid, i["cod"], i["imp"], i["fecha"]))
        for grupo in trozos(a_insertar, 20):
            sentencias.append(("INSERT INTO tarifario_valores (tarifario_id, codigo, importe, vigente_desde) VALUES " + ",".join(["(?,?,?,?)"] * len(grupo)),
                               tuple(v for fila_ in grupo for v in fila_)))
        propias = {r["codigo"] for r in db.q("SELECT codigo FROM tarifario_descripciones WHERE tarifario_id=?", (tid,))}
        for i in t["items"]:
            if i["desc"] and i["desc"] != generales.get(i["cod"]) and i["cod"] not in propias:
                propias.add(i["cod"])
                sentencias.append(("INSERT INTO tarifario_descripciones (tarifario_id, codigo, descripcion) VALUES (?,?,?)", (tid, i["cod"], i["desc"])))
        for trozo in trozos(sentencias, 40):
            db.lote_ex(trozo)
        if t["dias"] is not None and not t["plan"]:
            db.lote_ex([("DELETE FROM cobertura_pago WHERE cobertura=?", (cobertura,)), ("INSERT INTO cobertura_pago (cobertura, dias) VALUES (?,?)", (cobertura, t["dias"]))])
        cargadas += 1
        valores_total += len(t["items"])
        planes += 1 if t["plan"] else 0
        imprimir(f"  {nombre}: {len(t['items'])} importes · IVA {t['iva']}")
    repetidos = [(t["cobertura"], t["plan"], i["cod"], i["fecha"], i["imp"], i["desc"]) for t in tarifas for i in t.get("repetidos", [])]
    return {"tarifas": cargadas, "importes": valores_total, "planes": planes, "omitidas": sorted(set(omitidas)), "codigos_nuevos": len(nuevos), "repetidos": repetidos}


def main(argumentos):
    p = argparse.ArgumentParser(description="Carga tarifas, descripciones, planes y plazos de cobro tomados del sistema anterior.")
    p.add_argument("archivo")
    p.add_argument("--si", action="store_true", help="no pedir confirmación")
    args = p.parse_args(argumentos)
    with open(args.archivo, encoding="utf-8") as f:
        datos = json.load(f)
    tarifas = tarifas_del_paquete(datos)
    print(f"{len(tarifas)} tarifas ({sum(1 for t in tarifas if t['plan'])} de plan), {sum(len(t['items']) for t in tarifas)} importes.")
    if not args.si and input("Escribí SI para guardar en la base: ").strip() != "SI":
        print("Cancelado, no se guardó nada.")
        return 1
    db.inicializar()
    with crear_app().app_context():
        r = aplicar(tarifas)
        db.auditar(None, None, "tarifas_cargadas", f"{r['tarifas']} tarifas, {r['importes']} importes, {r['planes']} planes")
    print(f"Listo: {r['tarifas']} tarifas, {r['importes']} importes, {r['planes']} planes, {r['codigos_nuevos']} nomencladores nuevos.")
    if r["repetidos"]:
        print(f"{len(r['repetidos'])} importes con el mismo código y fecha que otro de la misma tarifa: se conservó el primero y no se cargaron estos:")
        for cobertura, plan, cod, fecha, imp, desc in r["repetidos"]:
            print(f"  {cobertura}{' · ' + plan if plan else ''} · {cod} · {fecha} · {imp:.2f} · {desc}")
    if r["omitidas"]:
        print("Sin cobertura equivalente en el sistema (omitidas):", ", ".join(r["omitidas"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
