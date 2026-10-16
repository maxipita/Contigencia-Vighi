from vighi.core import db
from vighi.dominio.estudios import pap

SQL_OPCIONES = "SELECT tipo, abreviatura, descripcion, sospechoso FROM abreviaturas_pap ORDER BY tipo, orden, id"


def opciones():
    salida = {}
    for r in db.q(SQL_OPCIONES):
        salida.setdefault(r["tipo"], []).append({"abrev": r["abreviatura"], "texto": r["descripcion"], "sospechoso": bool(r["sospechoso"])})
    return salida


def contexto():
    return {"opciones": opciones(), "escala": pap.ESCALA, "simples": pap.SIMPLES, "hormonal": pap.HORMONAL,
            "oncologica": pap.ONCOLOGICA, "resultado": pap.RESULTADO}


def valores_de_formulario(form):
    valores = {k: form.get(k, "").strip()[:200] for k in pap.CAMPOS}
    valores["conclusion"] = form.get("conclusion", "").strip()
    return valores


def es_sospechoso(texto):
    return bool(texto) and bool(db.uno("SELECT 1 FROM abreviaturas_pap WHERE tipo='resultado' AND descripcion=? AND sospechoso=1", (texto,)))


def aplicar_sospecha(e, micro_antes, resultado, yo):
    antes = es_sospechoso(pap.resultado_de(micro_antes))
    ahora = es_sospechoso(resultado)
    actuales = {r["malignidad"] or "" for r in db.q("SELECT malignidad FROM estudios WHERE flujo_id=? AND anulado=0", (e["flujo_id"],))}
    if ahora and actuales == {""}:
        nuevo, detalle = "SOSPECHOSO", "PAP: sospechoso (por el resultado)"
    elif antes and not ahora and actuales == {"SOSPECHOSO"}:
        nuevo, detalle = None, "PAP: sin malignidad (cambió el resultado)"
    else:
        return
    db.ex("UPDATE estudios SET malignidad=? WHERE flujo_id=? AND anulado=0", (nuevo, e["flujo_id"]))
    db.auditar(yo["id"], e["protocolo_id"], "malignidad", detalle)
