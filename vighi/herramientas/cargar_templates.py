import collections
import json
import os
import re
import sys
import unicodedata

SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "seed")


def clave(texto):
    sin = "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin).casefold().strip()


def catalogo():
    with open(os.path.join(SEED, "catalogo.json"), encoding="utf-8") as f:
        filas = [x for x in json.load(f) if x["tipo"] == "BP"]
    zonas_del_sitio = collections.defaultdict(set)
    for x in filas:
        zonas_del_sitio[clave(x["sitio"])].add(x["subcategoria"])
    return {clave(x["sitio"]): x["sitio"] for x in filas}, {clave(x["subcategoria"]): x["subcategoria"] for x in filas}, zonas_del_sitio


def clasificar(zona, organo, sitios, zonas, zonas_del_sitio):
    organo_c = sitios.get(clave(organo), "")
    zona_c = zonas.get(clave(zona), "")
    unicas = zonas_del_sitio.get(clave(organo), set())
    return (zona_c or (next(iter(unicas)) if len(unicas) == 1 else "")), organo_c


def armar(extraccion):
    sitios, zonas, zonas_del_sitio = catalogo()
    micro, macro = [], []
    for x in sorted(extraccion, key=lambda z: z["id"]):
        titulo = " ".join((x["titulo"] or "").split())
        zona, organo = clasificar(x["zona"], x["organo"], sitios, zonas, zonas_del_sitio)
        base = {"titulo": titulo, "tipo_biopsia": zona, "organo": organo, "sb_id": x["id"]}
        diagnostico = (x["diagnostico"] or "").strip() or (x["observaciones"] or "").strip()
        if (x["micro"] or "").strip() or diagnostico:
            micro.append({"clase": "micro", **base, "texto": (x["micro"] or "").strip(), "conclusion": diagnostico})
        if (x["macro"] or "").strip():
            macro.append({"clase": "macro", **base, "texto": x["macro"].strip(), "conclusion": ""})
    return desambiguar(micro), desambiguar(macro)


def desambiguar(lista):
    repetidos = {t for t, n in collections.Counter(x["titulo"] for x in lista).items() if n > 1}
    vistos = collections.Counter()
    for x in lista:
        if x["titulo"] in repetidos:
            vistos[x["titulo"]] += 1
            x["titulo"] = f"{x['titulo']} ({vistos[x['titulo']]})"
    lista.sort(key=lambda z: z["titulo"].casefold())
    return lista


def guardar(nombre, datos):
    with open(os.path.join(SEED, nombre), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
        f.write("\n")


def main(argumentos):
    if not argumentos:
        print("Uso: py -m vighi.herramientas.cargar_templates <extraccion.json> [--escribir]")
        return 1
    with open(argumentos[0], encoding="utf-8") as f:
        extraccion = json.load(f)["templates"]
    micro, macro = armar(extraccion)
    vacios = len(extraccion) - len({x["sb_id"] for x in micro + macro})
    print(f"Extracción: {len(extraccion)} templates de southernbits")
    print(f"  micro: {len(micro)} ({sum(1 for x in micro if x['conclusion'])} con diagnóstico)")
    print(f"  macro: {len(macro)}")
    print(f"  sin texto en ninguno (no se cargan): {vacios}")
    print(f"  con zona del catálogo: {sum(1 for x in micro + macro if x['tipo_biopsia'])} | con órgano del catálogo: {sum(1 for x in micro + macro if x['organo'])}")
    sin_resolver = collections.Counter(x["organo"] for x in extraccion if (x["organo"] or "").strip() and x["organo"] != "N/A" and not clasificar("", x["organo"], *catalogo())[1])
    if sin_resolver:
        print("  órganos que no están en el catálogo:", dict(sin_resolver))
    if "--escribir" in argumentos:
        guardar("templates_micro.json", micro)
        guardar("templates_macro.json", macro)
        print("Escritos seed/templates_micro.json y seed/templates_macro.json")
    else:
        print("(no se escribió nada; agregá --escribir)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
