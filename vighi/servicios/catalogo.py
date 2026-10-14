from vighi.core import db
from vighi.core.texto import sin_acentos


def tipos_de_muestra(tipo):
    cuentas = {}
    for r in db.q("SELECT tipo_muestra, COUNT(*) AS n FROM catalogo WHERE tipo=? AND tipo_muestra IS NOT NULL AND tipo_muestra<>'' GROUP BY tipo_muestra", (tipo,)):
        cuentas.setdefault(sin_acentos(r["tipo_muestra"]), []).append((r["n"], r["tipo_muestra"]))
    return sorted(max(v)[1] for v in cuentas.values())


def tipos_de_muestra_bp():
    return tipos_de_muestra("BP")
