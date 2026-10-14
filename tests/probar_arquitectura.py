import ast
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAQUETE = os.path.join(RAIZ, "vighi")
fallas = []


def chequear(nombre, ok, detalle=""):
    print(("  OK   " if ok else "  FALLA"), nombre, "" if ok else detalle)
    if not ok:
        fallas.append(nombre)


def modulo_de(ruta):
    relativa = os.path.relpath(ruta, RAIZ)[:-3].replace(os.sep, ".")
    return relativa[:-len(".__init__")] if relativa.endswith(".__init__") else relativa


archivos = {}
for carpeta, _, nombres in os.walk(PAQUETE):
    for n in nombres:
        if n.endswith(".py"):
            ruta = os.path.join(carpeta, n)
            archivos[modulo_de(ruta)] = ruta

importa = {}
usados_sin_importar = {}
for modulo, ruta in archivos.items():
    arbol = ast.parse(open(ruta, encoding="utf-8").read())
    destinos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            destinos.add(nodo.module)
            for alias in nodo.names:
                destinos.add(f"{nodo.module}.{alias.name}")
        elif isinstance(nodo, ast.Import):
            for alias in nodo.names:
                destinos.add(alias.name)
    importa[modulo] = {d for d in destinos if d == "vighi" or d.startswith("vighi.")}

print("1) capas")
capa = lambda m: m.split(".")[1] if m.count(".") >= 1 else "raiz"


def infracciones(origen_capa, prohibidas, descripcion):
    malas = []
    for modulo, destinos in importa.items():
        if capa(modulo) != origen_capa:
            continue
        for d in destinos:
            partes = d.split(".")
            if len(partes) > 1 and partes[1] in prohibidas:
                malas.append(f"{modulo} -> {d}")
    chequear(descripcion, not malas, malas[:5])


infracciones("core", {"servicios", "features", "herramientas"}, "core no depende de servicios, features ni herramientas")
infracciones("dominio", {"servicios", "features", "herramientas"}, "dominio no depende de servicios, features ni herramientas")
infracciones("servicios", {"features", "herramientas"}, "servicios no depende de features ni herramientas")
malas = []
for modulo, destinos in importa.items():
    if capa(modulo) == "features":
        for d in destinos:
            partes = d.split(".")
            if len(partes) > 2 and partes[1] == "features" and ".".join(partes[:3]) != modulo:
                malas.append(f"{modulo} -> {d}")
chequear("ninguna funcionalidad importa a otra", not malas, malas[:5])
malas = [m for m, ds in importa.items() if capa(m) != "herramientas" and any(d.startswith("vighi.herramientas") for d in ds)]
chequear("nada del sistema depende de las herramientas de una sola vez", not malas, malas)

print("2) higiene")
sueltos = []
for modulo, ruta in archivos.items():
    for numero, linea in enumerate(open(ruta, encoding="utf-8"), 1):
        if re.match(r"\s*(import|from)\s+(d1|db|pg|almacen|permisos|facturacion|trazabilidad|informes|estudios)\b", linea):
            sueltos.append(f"{modulo}:{numero}")
chequear("no quedan importaciones sueltas de los módulos viejos", not sueltos, sueltos[:5])

sin_usar = []
for modulo, ruta in archivos.items():
    if ruta.endswith("__init__.py"):
        continue
    arbol = ast.parse(open(ruta, encoding="utf-8").read())
    importados = {}
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            for a in n.names:
                importados[(a.asname or a.name).split(".")[0]] = n.lineno
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                importados[a.asname or a.name] = n.lineno
    usados = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
    sin_usar += [f"{modulo}:{linea} {nombre}" for nombre, linea in importados.items() if nombre not in usados]
chequear("no hay importaciones sin usar", not sin_usar, sin_usar[:6])

sin_bp = [m for m in archivos if capa(m) == "features" and not m.endswith("__init__") and m != "vighi.features"
          and "bp = Blueprint(" not in open(archivos[m], encoding="utf-8").read()]
chequear("cada funcionalidad define su blueprint", not sin_bp, sin_bp)

sin_cuerpo_largo = []
for modulo, ruta in archivos.items():
    for n in ast.parse(open(ruta, encoding="utf-8").read()).body:
        if isinstance(n, ast.FunctionDef) and n.end_lineno - n.lineno > 140:
            sin_cuerpo_largo.append(f"{modulo}.{n.name} ({n.end_lineno - n.lineno} líneas)")
chequear("ninguna función supera las 140 líneas", not sin_cuerpo_largo, sin_cuerpo_largo)

print("3) plantillas")
base = os.path.join(PAQUETE, "templates")
sueltas = [f for f in os.listdir(base) if f.endswith(".html") and f != "base.html"]
chequear("las plantillas están en carpetas por funcionalidad (solo base.html en la raíz)", not sueltas, sueltas)

print(chr(10) + "FALLAS:", fallas if fallas else "ninguna")
