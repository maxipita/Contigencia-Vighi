import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()

fallas = []
SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed")


def chequear(nombre, ok, detalle=""):
    print(("  OK   " if ok else "  FALLA"), nombre, "" if ok else detalle)
    if not ok:
        fallas.append(nombre)


def leer(nombre):
    with open(os.path.join(SEED, nombre), encoding="utf-8") as f:
        return json.load(f)


micro, macro = leer("templates_micro.json"), leer("templates_macro.json")
seed = micro + macro
c = db._conectar()


def filas():
    origen = "sb_id" if "sb_id" in {r["name"] for r in c.execute("PRAGMA table_info(templates)")} else "NULL AS sb_id"
    return [dict(r) for r in c.execute(f"SELECT id, clase, titulo, tipo_biopsia, organo, tipo_muestra, texto, conclusion, {origen} FROM templates ORDER BY id").fetchall()]


print("1) base nueva")
nuevas = filas()
chequear("se siembran todos los templates de southernbits", len(nuevas) == len(seed), (len(nuevas), len(seed)))
chequear("cada uno guarda su número de southernbits", all(r["sb_id"] for r in nuevas))
chequear("hay más de 300 templates de microscopía con diagnóstico", sum(1 for r in nuevas if r["clase"] == "micro" and (r["conclusion"] or "").strip()) > 300)
lin = next(r for r in nuevas if r["titulo"].startswith("(EB) Linfangioma PIEL"))
chequear("«(EB) Linfangioma PIEL» trae descripción y diagnóstico", (lin["texto"] or "").strip() and (lin["conclusion"] or "").strip(), lin)
chequear("los títulos ya no están cortados a 30 caracteres", any(len(r["titulo"]) > 30 for r in nuevas))

print("2) base con el formato anterior")
import collections
prefijos = collections.Counter(db._clave_titulo(t["clase"], t["titulo"]) for t in seed)
unico = lambda t: prefijos[db._clave_titulo(t["clase"], t["titulo"])] == 1
muestra = [t for t in micro if len(t["titulo"]) > 32 and t["conclusion"] and unico(t)][:30] + [t for t in macro if len(t["titulo"]) > 32 and unico(t)][:8]
chequear("hay títulos largos y no ambiguos para probar", len(muestra) >= 20, len(muestra))
c.execute("ALTER TABLE templates RENAME TO templates_nueva")
c.execute("CREATE TABLE templates (id INTEGER PRIMARY KEY AUTOINCREMENT, clase VARCHAR(10) NOT NULL, titulo VARCHAR(120) NOT NULL, tipo_biopsia VARCHAR(40), "
          "texto TEXT, conclusion TEXT, organo VARCHAR(80), tipo_muestra VARCHAR(80), UNIQUE (clase, titulo))")
usados = {}
for i, t in enumerate(muestra):
    manual = ("Zona manual", "Órgano manual", "Tipo manual") if i % 3 == 0 else (None, None, None)
    corto = t["titulo"][:30]
    usados[(t["clase"], corto)] = usados.get((t["clase"], corto), 0) + 1
    if usados[(t["clase"], corto)] > 1:
        corto = f"{corto} ({usados[(t['clase'], corto)]})"
    c.execute("INSERT INTO templates (clase, titulo, tipo_biopsia, texto, conclusion, organo, tipo_muestra) VALUES (?,?,?,?,?,?,?)",
              (t["clase"], corto, manual[0], "texto viejo " + str(i), "", manual[1], manual[2]))
c.execute("INSERT INTO templates (clase, titulo, tipo_biopsia, texto, conclusion) VALUES (?,?,?,?,?)", ("micro", "TEMPLATE PROPIO DEL LABORATORIO", "Digestiva", "Texto propio", "Concl propia"))
c.execute("DROP TABLE templates_nueva")
c.commit()
chequear("quedó sin la columna de origen", "sb_id" not in {r["name"] for r in c.execute("PRAGMA table_info(templates)")})
antes = filas()

db.inicializar()
despues = filas()
chequear("la columna de origen se agregó", "sb_id" in {r["name"] for r in c.execute("PRAGMA table_info(templates)")})
por_id = {r["id"]: r for r in despues}
base = {r["id"]: r for r in antes}
ok_titulo = ok_texto = ok_conclusion = ok_clasif = ok_rellena = True
detalle = []
for i, t in enumerate(muestra):
    viejo = next(r for r in antes if r["texto"] == "texto viejo " + str(i))
    nuevo = por_id[viejo["id"]]
    ok_titulo &= nuevo["titulo"].startswith(t["titulo"]) or nuevo["titulo"] == t["titulo"]
    ok_texto &= nuevo["texto"] == t["texto"]
    ok_conclusion &= (nuevo["conclusion"] or "") == t["conclusion"]
    if i % 3 == 0:
        ok_clasif &= (nuevo["tipo_biopsia"], nuevo["organo"], nuevo["tipo_muestra"]) == ("Zona manual", "Órgano manual", "Tipo manual")
    else:
        ok_rellena &= (nuevo["organo"] or "") == (t["organo"] or "") and (nuevo["tipo_biopsia"] or "") == (t["tipo_biopsia"] or "")
    if not (ok_titulo and ok_texto and ok_conclusion and ok_clasif and ok_rellena) and not detalle:
        detalle = (i, t["titulo"], nuevo["titulo"], nuevo["organo"], t["organo"])
chequear("los títulos cortados pasan al título completo", ok_titulo, detalle)
chequear("el texto es el de hoy", ok_texto, detalle)
chequear("el diagnóstico se completa", ok_conclusion, detalle)
chequear("la clasificación hecha a mano se conserva", ok_clasif, detalle)
chequear("la que estaba vacía se completa con la de southernbits", ok_rellena, detalle)
propio = [r for r in despues if r["titulo"] == "TEMPLATE PROPIO DEL LABORATORIO"]
chequear("un template que no está en southernbits no se toca", len(propio) == 1 and propio[0]["texto"] == "Texto propio" and propio[0]["conclusion"] == "Concl propia" and propio[0]["sb_id"] is None, propio)
chequear("los ya existentes mantienen su número interno", all(r["id"] in por_id for r in antes))
chequear("se suman los que faltaban, sin duplicar", len(despues) == len(seed) + 1, (len(despues), len(seed) + 1))
chequear("no hay títulos repetidos dentro de una clase", len({(r["clase"], r["titulo"]) for r in despues}) == len(despues))

print("3) volver a arrancar")
db.inicializar()
chequear("no cambia nada la segunda vez", filas() == despues)
print("FALLAS:", fallas or "ninguna")
