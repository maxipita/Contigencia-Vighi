import json
import re
import unicodedata
from datetime import datetime, timedelta

from vighi.core import db
from vighi.servicios.consultas import tipos_lote_fijos
from vighi.servicios.lotes import orden_numero


TIPOS_ETIQUETA = {"bp": "Recepción", "pap": "PAP-Laboratorio", "lab": "BP-Laboratorio"}
GRUPO_NUMERACION = ("bp", "pap")
ESTUDIO_LAB = {"lab": "BP", "pap": "PAP"}
LOTES_ETIQUETA_EXTRA = ["PAPS"]
MUESTRAS_PAP = ["EXO", "ENDO", "ENDO/EXO", "PAPURG", "CUPULA", "DERRAME"]
CODIGO_MUESTRA_PAP = {"citologia endocervical": "ENDO", "citologia exocervical": "EXO", "cupula vaginal": "CUPULA", "liquido": "DERRAME"}
MAX_PROTOCOLO = 999999
DIAS_ETIQUETADOS = 3


def codigo_muestra_pap(tipo_muestra, cantidad=""):
    if (cantidad or "").strip() == "1/2":
        return "ENDO/EXO"
    normal = unicodedata.normalize("NFD", tipo_muestra or "").encode("ascii", "ignore").decode().strip().lower()
    return CODIGO_MUESTRA_PAP.get(normal, (tipo_muestra or "").strip().upper())


def numero_protocolo(n):
    return f"C{n:06d}"


def estudio_de_lote(tipo_lote):
    return {"PAPS": "PAP", "CT": "CT"}.get(tipo_lote, "BP")


def numero_emitido(protocolo):
    m = re.fullmatch(r"C(\d{6})", protocolo or "")
    if not m:
        return True
    n = int(m.group(1))
    return db.uno("SELECT 1 FROM etiquetas_lotes WHERE tipo IN ('bp','pap') AND desde <= ? AND hasta >= ?", (n, n)) is not None


def personal(sector):
    filas = db.q("SELECT iniciales, nombre, sectores FROM usuarios WHERE activo=1 ORDER BY iniciales")
    return [{"iniciales": u["iniciales"], "nombre": u["nombre"] if (u["nombre"] or u["iniciales"]) != u["iniciales"] else ""}
            for u in filas if sector in (u["sectores"] or "").split(",")]


def tipos_lote_etiqueta():
    return sorted(set(tipos_lote_fijos()) | set(LOTES_ETIQUETA_EXTRA), key=str.casefold)


def listas_etiquetas():
    return {"tiposLote": tipos_lote_etiqueta(), "muestrasPap": MUESTRAS_PAP,
            "citotecnicos": personal("citotecnico"), "patologos": personal("firmante")}


def etiquetas_historial():
    progreso = {r["etiqueta_lote_id"]: r["ok"] for r in db.q(
        "SELECT etiqueta_lote_id, SUM(CASE WHEN borrador=0 THEN 1 ELSE 0 END) AS ok FROM protocolos "
        "WHERE etiqueta_lote_id IS NOT NULL GROUP BY etiqueta_lote_id")}
    out = []
    for f in db.q("""SELECT e.*, u.iniciales AS creador, l.codigo AS lote_codigo FROM etiquetas_lotes e
                     LEFT JOIN usuarios u ON u.id=e.creado_por LEFT JOIN lotes l ON l.id=e.lote_id ORDER BY e.id"""):
        out.append({"id": f["id"], "tipo": f["tipo"], "desde": f["desde"], "hasta": f["hasta"], "loteId": f["lote_id"],
                    "loteCodigo": f["lote_codigo"], "n": f["n"], "porProto": f["por_proto"], "etiquetas": f["etiquetas"],
                    "creadoEn": f["creado_en"], "creador": f["creador"] or "", "params": json.loads(f["params"]),
                    "completados": progreso.get(f["id"]) if f["tipo"] == "bp" else None})
    return out


def etiquetas_cantidad(cantidad):
    return int(cantidad) if (cantidad or "").isdigit() else (1 if cantidad else 0)


def tecnicas_por_estudio():
    out = {}
    for r in db.q("SELECT estudio_id, numero, cassettes FROM tecnicas ORDER BY id"):
        out.setdefault(r["estudio_id"], []).append(r)
    return out


def rotulos_cassettes(tecnicas):
    out = []
    for t in tecnicas:
        n = t["cassettes"] or 1
        numero = (t["numero"] or "").strip()
        out += [numero] if n == 1 else [f"{numero} {k}/{n}".strip() for k in range(1, n + 1)]
    return out


def etiquetas_casos():
    limite = (datetime.now() - timedelta(days=DIAS_ETIQUETADOS)).strftime("%Y-%m-%d")
    filas = db.q("""SELECT e.id, e.tipo, p.numero, p.apellido, p.nombre, e.cantidad, e.lote_id, l.codigo AS lote,
                           p.fecha_recoleccion, e.lab_etiquetado_en, e.tipo_muestra, u.iniciales AS resp
                    FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                    LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN lotes l ON l.id=e.lote_id
                    WHERE p.borrador=0 AND e.anulado=0 AND e.tipo IN ('BP','PAP') AND e.cantidad IS NOT NULL AND e.cantidad<>''
                      AND (e.lab_etiquetado_en IS NULL OR e.lab_etiquetado_en >= ?) ORDER BY e.lote_id, e.id""", (limite,))
    tecnicas = tecnicas_por_estudio()
    rotulos = {f["id"]: rotulos_cassettes(tecnicas.get(f["id"], [])) if f["tipo"] == "BP" else [] for f in filas}
    return [{"id": f["id"], "estudio": f["tipo"], "protocolo": f["numero"], "apellido": f["apellido"] or "",
             "nombre": f["nombre"] or "", "cantidad": len(rotulos[f["id"]]) or etiquetas_cantidad(f["cantidad"]),
             "nros": rotulos[f["id"]], "frascos": etiquetas_cantidad(f["cantidad"]), "loteId": f["lote_id"],
             "loteCodigo": f["lote"] or "", "fechaRec": f["fecha_recoleccion"] or "", "resp": f["resp"] or "",
             "muestra": codigo_muestra_pap(f["tipo_muestra"], f["cantidad"]) if f["tipo"] == "PAP" else "",
             "etiquetado": bool(f["lab_etiquetado_en"])}
            for f in sorted(filas, key=lambda f: (f["lote_id"] or 0, orden_numero(f["numero"]), f["id"]))]


def siguiente_libre():
    marcas = ",".join("?" * len(GRUPO_NUMERACION))
    fila = db.uno(f"SELECT MAX(hasta) AS m FROM etiquetas_lotes WHERE tipo IN ({marcas})", GRUPO_NUMERACION)
    return (fila["m"] or 0) + 1


def _entero(valor, minimo, maximo):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return None
    return n if minimo <= n <= maximo else None


def datos_etiquetas():
    return {"listas": listas_etiquetas(), "historial": etiquetas_historial(), "casos": etiquetas_casos()}
