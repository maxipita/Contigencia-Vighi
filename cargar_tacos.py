import csv
import json
import os
import sys
import unicodedata

import db
from estudios import REGISTRO

RUTA_SEMILLA = os.path.join(db.BASE, "seed", "tacos_organo.json")
RUTA_ALIAS = os.path.join(db.BASE, "seed", "alias_organos.json")
RUTA_FALTANTES = os.path.join(db.BASE, "organos_sin_tacos.csv")


def normal(texto):
    sin_tildes = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def tipo_de_lote(texto):
    return " ".join(str(texto or "").upper().split())


def leer_excel(ruta):
    import openpyxl
    filas = list(openpyxl.load_workbook(ruta, data_only=True).worksheets[0].iter_rows(values_only=True))
    for i, fila in enumerate(filas):
        columnas = [j for j in range(len(fila) - 2) if normal(fila[j]) == "organo" and normal(fila[j + 1]) == "tipo lote" and normal(fila[j + 2]) == "tacos"]
        if columnas:
            return [(fila2[j], fila2[j + 1], fila2[j + 2]) for fila2 in filas[i + 1:] for j in columnas if j < len(fila2) and fila2[j]]
    raise ValueError("No encontré las columnas Organo, Tipo lote y Tacos en la planilla.")


def leer_csv(ruta):
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        primera = f.readline()
        f.seek(0)
        filas = list(csv.reader(f, delimiter=";" if primera.count(";") >= primera.count(",") else ","))
    encabezado = filas[0]
    if normal(encabezado[0]) != "organo":
        raise ValueError("La primera columna del CSV tiene que llamarse organo (y las demás, un tipo de lote cada una: ENDO, NO ONCO, ONCO...).")
    return [(fila[0], encabezado[j], fila[j]) for fila in filas[1:] if fila and fila[0].strip() for j in range(1, len(encabezado)) if j < len(fila) and fila[j].strip()]


def main(argumentos, semilla=RUTA_SEMILLA, faltantes=RUTA_FALTANTES, alias_ruta=RUTA_ALIAS):
    ruta = next((a for a in argumentos if not a.startswith("--")), None)
    if not ruta or not os.path.exists(ruta):
        print("Uso: py cargar_tacos.py <planilla.xlsx o .csv> [--si]")
        return 1
    try:
        leidas = leer_excel(ruta) if ruta.lower().endswith((".xlsx", ".xlsm")) else leer_csv(ruta)
    except ValueError as error:
        print(error)
        return 1
    lotes_validos = set(REGISTRO["BP"].lotes)
    ignoradas, invalidas, datos = [], [], []
    for organo, lote, tacos in leidas:
        lote = tipo_de_lote(lote)
        if not lote:
            ignoradas.append(str(organo).strip())
            continue
        if lote not in lotes_validos:
            invalidas.append((str(organo).strip(), lote))
            continue
        try:
            valor = float(str(tacos).replace(",", "."))
        except ValueError:
            invalidas.append((str(organo).strip(), tacos))
            continue
        if valor != int(valor) or valor < 0:
            invalidas.append((str(organo).strip(), tacos))
            continue
        datos.append((str(organo).strip(), lote, int(valor)))
    if invalidas:
        print("Filas con tipo de lote desconocido o tacos que no son un entero (órgano, valor):", invalidas[:12])
        return 1
    destino = db._conectar()
    sitios = {}
    for fila in destino.execute("SELECT DISTINCT sitio FROM catalogo WHERE tipo='BP'").fetchall():
        sitios.setdefault(normal(fila["sitio"]), []).append(fila["sitio"])
    alias = {normal(k): v for k, v in json.load(open(alias_ruta, encoding="utf-8")).items()} if os.path.exists(alias_ruta) else {}
    sin_sitio, resueltos, conflictos = set(), {}, {}
    for organo, lote, tacos in datos:
        nombres = alias.get(normal(organo), [organo])
        encontrados = [exacto for n in nombres for exacto in sitios.get(normal(n), [])]
        if not encontrados:
            sin_sitio.add(organo)
        for sitio in encontrados:
            clave = (sitio, lote)
            if clave in resueltos and resueltos[clave] != tacos:
                conflictos.setdefault(clave, {resueltos[clave]}).add(tacos)
            resueltos[clave] = max(tacos, resueltos.get(clave, 0))
    con_dato = {s for s, _ in resueltos} | {r["organo"] for r in destino.execute("SELECT DISTINCT organo FROM tacos_organo").fetchall()}
    faltan = sorted(s for lista in sitios.values() for s in lista if s not in con_dato)
    print(f"Planilla: {ruta}")
    print(f"  filas leídas: {len(datos)} | combinaciones órgano + tipo de lote que se guardan: {len(resueltos)}")
    if conflictos:
        print("  con varios valores para el mismo órgano y lote (se usa el MAYOR):")
        for (sitio, lote), valores in sorted(conflictos.items()):
            print(f"    {sitio} / {lote}: {sorted(valores)} -> {resueltos[(sitio, lote)]}")
    if sin_sitio:
        print(f"  nombres de la planilla sin órgano equivalente en el sistema (se ignoran): {sorted(sin_sitio)}")
    if ignoradas:
        print(f"  filas sin tipo de lote (notas) ignoradas: {len(ignoradas)}")
    print(f"  órganos del sistema sin ningún dato de tacos: {len(faltan)}")
    if "--si" not in argumentos and input("Escribí SI para guardar en la base de Cloudflare: ").strip() != "SI":
        print("Cancelado, no se guardó nada.")
        return 1
    claves = sorted(resueltos)
    sentencias = [("DELETE FROM tacos_organo WHERE organo=? AND tipo_lote=?", clave) for clave in claves]
    for i in range(0, len(claves), 30):
        trozo = claves[i:i + 30]
        sentencias.append(("INSERT INTO tacos_organo (organo, tipo_lote, tacos) VALUES " + ",".join(["(?,?,?)"] * len(trozo)),
                           [v for c in trozo for v in (c[0], c[1], resueltos[c])]))
    for i in range(0, len(sentencias), 40):
        destino.lote(sentencias[i:i + 40])
    existentes = {(x["organo"], x["tipo_lote"]): x["tacos"] for x in json.load(open(semilla, encoding="utf-8"))} if os.path.exists(semilla) else {}
    existentes.update(resueltos)
    with open(semilla, "w", encoding="utf-8", newline="") as f:
        json.dump([{"organo": o, "tipo_lote": l, "tacos": t} for (o, l), t in sorted(existentes.items())], f, ensure_ascii=False, indent=2)
        f.write("\n")
    if faltan:
        lotes = sorted(lotes_validos & {"ENDO", "NO ONCO", "ONCO"}) or sorted(lotes_validos)
        with open(faltantes, "w", encoding="utf-8-sig", newline="") as f:
            escritor = csv.writer(f, delimiter=";")
            escritor.writerow(["organo", *lotes])
            for sitio in faltan:
                escritor.writerow([sitio] + [""] * len(lotes))
    elif os.path.exists(faltantes):
        os.remove(faltantes)
    print(f"Listo: {len(resueltos)} combinaciones guardadas en la base y en seed/tacos_organo.json."
          + (f" Los {len(faltan)} órganos sin dato quedaron en {faltantes} para completar." if faltan else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
