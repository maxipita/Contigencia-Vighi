import re

from flask import abort, flash

from vighi.core import db
from vighi.core.fechas import hoy
from vighi.dominio.estudios import NOMBRE_ETAPA, REGISTRO, TIPOS
from vighi.servicios.consultas import cargar_estudios, responsables, tipos_lote_fijos
from vighi.servicios.tacos import tacos_de_lote, tacos_de_protocolo


def ubicar_en_lote(protocolo_id, usuario_id):
    capacidad = REGISTRO["BP"].tacos_por_lote
    with db.bloqueo("lotes"):
        actual = lote_del_protocolo(protocolo_id)
        if not actual or actual["cerrado"] or actual["tipo_lote"] not in REGISTRO["BP"].lotes:
            return None
        propios = tacos_de_protocolo(protocolo_id)[0]
        ocupados = tacos_de_lote(actual["id"])[0] - propios
        if not propios or not ocupados or ocupados + propios <= capacidad:
            return None
        destino = next((l for l in db.q("SELECT * FROM lotes WHERE tipo_lote=? AND fecha=? AND cerrado=0 AND id<>? ORDER BY numero",
                                        (actual["tipo_lote"], hoy(), actual["id"])) if tacos_de_lote(l["id"])[0] + propios <= capacidad), None)
        destino = destino or crear_lote(actual["tipo_lote"], usuario_id)
        asignar_lote(protocolo_id, destino, usuario_id)
        db.auditar(usuario_id, protocolo_id, "lote_lleno", f"{actual['codigo']} llegó a {ocupados}/{capacidad} tacos: pasó a {destino['codigo']}")
        return {"desde": actual["codigo"], "hacia": destino["codigo"], "ocupados": ocupados, "capacidad": capacidad}


def avisar_lote_lleno(resultado):
    if resultado:
        flash(f"El lote {resultado['desde']} se llenó ({resultado['ocupados']}/{resultado['capacidad']} tacos): el protocolo pasó al lote {resultado['hacia']}.", "ok")


def tipos_lote(tipo=None):
    fijos = tipos_lote_fijos()
    cito = [u["iniciales"] for u in responsables("PAP")]
    if tipo:
        return REGISTRO[tipo].tipos_lote(fijos, cito)
    return fijos + [i for i in cito if i not in fijos]


def crear_lote(tipo_lote, usuario_id, fecha=None):
    f = fecha or hoy()
    prefijo = f"{tipo_lote}-{f[5:7]}{f[8:10]}"
    for _ in range(5):
        n = (db.uno("SELECT MAX(numero) AS m FROM lotes WHERE tipo_lote=? AND (fecha=? OR codigo LIKE ?)", (tipo_lote, f, prefijo + ".%"))["m"] or 0) + 1
        codigo = f"{prefijo}.{n}"
        try:
            lid = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_por, creado_en) VALUES (?,?,?,?,?,?)",
                        (codigo, tipo_lote, f, n, usuario_id, db.ahora()))
            break
        except db.IntegrityError:
            continue
    else:
        raise RuntimeError("No se pudo crear el lote, probá de nuevo.")
    db.auditar(usuario_id, None, "nuevo_lote", codigo)
    return db.uno("SELECT * FROM lotes WHERE id=?", (lid,))


def validar_lote(seleccion, tipo, actual_id=None):
    if not seleccion:
        return None, None
    if seleccion.startswith("nuevo:"):
        if seleccion[6:] not in tipos_lote(tipo):
            return None, f"Tipo de lote inválido para {TIPOS[tipo]}."
        return seleccion, None
    lote = db.uno("SELECT * FROM lotes WHERE id=?", (int(seleccion),)) if seleccion.isdigit() else None
    if not lote:
        return None, "El lote elegido no existe."
    if lote["id"] != actual_id:
        if lote["cerrado"]:
            return None, f"El lote {lote['codigo']} está cerrado."
        if lote["tipo_lote"] not in tipos_lote(tipo):
            return None, f"El lote {lote['codigo']} no corresponde a {TIPOS[tipo]}."
    return lote, None


def concretar_lote(valor, usuario_id):
    if isinstance(valor, str):
        return crear_lote(valor[6:], usuario_id)
    return valor


SQL_LOTES_ABIERTOS = "SELECT * FROM lotes WHERE fecha=? AND cerrado=0 ORDER BY tipo_lote, numero"


def lotes_para_formulario(tipo, actual_id=None):
    validos = tipos_lote(tipo)
    lotes = [l for l in db.q(SQL_LOTES_ABIERTOS, (hoy(),))
             if l["tipo_lote"] in validos]
    if actual_id and actual_id not in [l["id"] for l in lotes]:
        actual = db.uno("SELECT * FROM lotes WHERE id=?", (actual_id,))
        if actual:
            lotes.insert(0, actual)
    return lotes


def primer_estudio(protocolo_id):
    return db.uno("SELECT * FROM estudios WHERE protocolo_id=? AND anulado=0 ORDER BY id LIMIT 1", (protocolo_id,))


def lote_del_protocolo(protocolo_id):
    primero = primer_estudio(protocolo_id)
    return db.uno("SELECT * FROM lotes WHERE id=?", (primero["lote_id"],)) if primero and primero["lote_id"] else None


def asignar_lote(protocolo_id, lote, usuario_id):
    anterior = lote_del_protocolo(protocolo_id)
    db.ex("UPDATE estudios SET lote_id=? WHERE protocolo_id=? AND anulado=0", (lote["id"] if lote else None, protocolo_id))
    antes, despues = (anterior["codigo"] if anterior else None), (lote["codigo"] if lote else None)
    if antes != despues:
        db.auditar(usuario_id, protocolo_id, "lote", f"{antes or '—'} → {despues or '—'}")


def lote_o_404(lote_id):
    l = db.uno("""SELECT l.*, u.iniciales AS creador, u2.iniciales AS cerrador FROM lotes l
                  LEFT JOIN usuarios u ON u.id=l.creado_por LEFT JOIN usuarios u2 ON u2.id=l.cerrado_por
                  WHERE l.id=?""", (lote_id,))
    if not l:
        abort(404)
    return l


def orden_numero(numero):
    m = re.fullmatch(r"(\D*)(\d+)(.*)", numero or "")
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (numero or "", 0, "")


def plan_avance(lote_id):
    return plan_avance_de(cargar_estudios("e.lote_id=?", (lote_id,), borradores=True))


def plan_avance_de(estudios):
    activos = [x for x in estudios if not x["anulado"]]
    if not activos:
        return None, "El lote no tiene estudios para avanzar."
    borradores = sorted({x["numero"] for x in activos if x["borrador"]}, key=orden_numero)
    if borradores:
        return None, "Hay protocolos a completar en el lote (" + ", ".join(borradores[:8]) + (", …" if len(borradores) > 8 else "") + "): completalos antes de avanzar."
    flujos = {}
    for x in activos:
        flujos.setdefault((x["protocolo_id"], x["tipo"]), []).append(x)
    por_etapa = {}
    for f in flujos.values():
        por_etapa.setdefault(f[0]["proxima"][0] if f[0]["proxima"] else None, []).append(f)
    if len(por_etapa) > 1:
        partes = [f"{NOMBRE_ETAPA[k] if k else 'Informado'}: {len(v)}" for k, v in sorted(por_etapa.items(), key=lambda kv: -len(kv[1]))]
        return None, "Las muestras del lote no están todas en la misma etapa (" + " · ".join(partes) + ")."
    etapa = next(iter(por_etapa))
    if etapa is None:
        return None, "Todos los estudios del lote ya están informados."
    return {"etapa": etapa, "flujos": list(flujos.values()), "sector": por_etapa[etapa][0][0]["proxima"][2]}, None
