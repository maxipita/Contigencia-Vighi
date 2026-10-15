from vighi.core import db
from vighi.core.texto import sin_acentos
from vighi.dominio.estudios import REGISTRO


def tipos_de_muestra(tipo):
    cuentas = {}
    for r in db.q("SELECT tipo_muestra, COUNT(*) AS n FROM catalogo WHERE tipo=? AND tipo_muestra IS NOT NULL AND tipo_muestra<>'' GROUP BY tipo_muestra", (tipo,)):
        cuentas.setdefault(sin_acentos(r["tipo_muestra"]), []).append((r["n"], r["tipo_muestra"]))
    return sorted(max(v)[1] for v in cuentas.values())


def tipos_de_muestra_bp():
    return tipos_de_muestra("BP")


def muestras_posibles(e, con_actual=True):
    filas = db.q("SELECT subcategoria, tipo_muestra FROM catalogo WHERE tipo=? AND sitio=? AND tipo_muestra IS NOT NULL AND tipo_muestra<>'' ORDER BY tipo_muestra", (e["tipo"], e["sitio"] or ""))
    propias = [r["tipo_muestra"] for r in filas if (r["subcategoria"] or "") == (e["subcategoria"] or "")] or [r["tipo_muestra"] for r in filas]
    return list(dict.fromkeys(propias + ([e["tipo_muestra"]] if con_actual and e["tipo_muestra"] else [])))


def sitios_posibles(e):
    if REGISTRO[e["tipo"]].sitio_fijo:
        return []
    filas = db.q("SELECT DISTINCT sitio FROM catalogo WHERE tipo=? AND subcategoria=? AND sitio IS NOT NULL AND sitio<>'' ORDER BY sitio", (e["tipo"], e["subcategoria"] or ""))
    return list(dict.fromkeys([r["sitio"] for r in filas] + ([e["sitio"]] if e["sitio"] else [])))


def muestra_para(e, sitio):
    opciones = muestras_posibles({**dict(e), "sitio": sitio}, con_actual=False)
    actual = e["tipo_muestra"] or ""
    if actual in opciones or not opciones:
        return actual
    return next((o for o in opciones if sin_acentos(o) == sin_acentos(actual)), opciones[0])
