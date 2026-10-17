import re
from datetime import datetime, timedelta

from flask import abort

from vighi.core import db
from vighi.core.fechas import fecha_hora
from vighi.core.sesion import puede
from vighi.dominio.estudios import NOMBRE_ETAPA, PASOS_IHQ, REGISTRO, SECTORES, Variante, sector_marca
from vighi.servicios.consultas import cargar_estudios, etiqueta, protocolo_cerrado


FLUJO_DE = "(SELECT flujo_id FROM estudios WHERE id=?)"
SQL_FICHA = """SELECT e.*, p.numero, p.borrador, p.fecha_recoleccion, p.apellido, p.nombre, p.dni, p.medico, p.cobertura,
                         u.iniciales AS responsable, u2.iniciales AS creador, l.codigo AS lote
                  FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                  LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN usuarios u2 ON u2.id=e.creado_por
                  LEFT JOIN lotes l ON l.id=e.lote_id WHERE e.id=?"""
SQL_ETAPAS_FICHA = """SELECT x.*, u.iniciales, u.nombre FROM etapas x
                                            JOIN usuarios u ON u.id=x.usuario_id WHERE x.flujo_id=""" + FLUJO_DE
SQL_ULTIMA_ETAPA = "SELECT * FROM etapas WHERE flujo_id=" + FLUJO_DE + " ORDER BY fecha_hora DESC, id DESC LIMIT 1"
SQL_HISTORIAL_ESTUDIO = """SELECT a.*, u.iniciales FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id
                        WHERE a.estudio_id IN (SELECT x.id FROM estudios x WHERE x.flujo_id=""" + FLUJO_DE + """)
                        ORDER BY a.id DESC"""
SQL_MACRO = "SELECT * FROM macro WHERE flujo_id=" + FLUJO_DE
SQL_MICRO = "SELECT * FROM micro WHERE flujo_id=" + FLUJO_DE
SQL_IHQ = "SELECT * FROM ihq WHERE flujo_id=" + FLUJO_DE
SQL_TEMPLATES = "SELECT id, titulo, tipo_biopsia AS zona, organo, tipo_muestra AS tipo FROM templates WHERE clase=? ORDER BY titulo"


def consultas_ficha(eid):
    return [(SQL_FICHA, (eid,)), (SQL_MACRO, (eid,)), (SQL_MICRO, (eid,)), (SQL_IHQ, (eid,)), (SQL_ETAPAS_FICHA, (eid,))]


def ficha(eid):
    db.precargar(consultas_ficha(eid))
    e = db.uno(SQL_FICHA, (eid,))
    if not e:
        abort(404)
    macro = db.uno(SQL_MACRO, (eid,))
    micro = db.uno(SQL_MICRO, (eid,))
    ihq = db.uno(SQL_IHQ, (eid,))
    etapas = {x["etapa"]: x for x in db.q(SQL_ETAPAS_FICHA, (eid,))}
    solicita = Variante(micro and micro["solicita_ihq"], macro and macro["decal"], bool(micro and micro["solicita_revision"]))
    return e, macro, micro, ihq, etapas, solicita


def con_permiso(permiso, estado):
    return estado if puede(permiso) or not estado[0] else (False, "No tenés permiso para cargar esta sección.")


def habilitada(e, etapas, solicita, etapa):
    if e["anulado"]:
        return False, "El estudio está anulado."
    _, prox = REGISTRO[e["tipo"]].estado(set(etapas), solicita)
    if prox and prox[0] == etapa:
        return True, ""
    if etapa in etapas:
        x = etapas[etapa]
        return False, (f"{NOMBRE_ETAPA[etapa]} ya fue completada por {x['iniciales']} el {fecha_hora(x['fecha_hora'])}. "
                       "Para corregirla hay que deshacer las etapas hasta esa.")
    return False, (f"Se habilita cuando el estudio llegue a {NOMBRE_ETAPA[etapa]}"
                   + (f" (ahora está en {prox[1]})." if prox else "."))


def micro_editable(e, etapas, solicita):
    en_micro = habilitada(e, etapas, solicita, "microscopia")
    if en_micro[0]:
        return en_micro
    en_revision = habilitada(e, etapas, solicita, "revision")
    return en_revision if en_revision[0] else en_micro


def macro_editable(e, etapas, solicita):
    en_macro = habilitada(e, etapas, solicita, "macroscopia")
    if en_macro[0]:
        return con_permiso("macro", en_macro)
    en_micro = habilitada(e, etapas, solicita, "microscopia")
    if en_micro[0] and "macro" in REGISTRO[e["tipo"]].secciones:
        return (True, "") if puede("macro") or puede("micro") else (False, "No tenés permiso para cargar esta sección.")
    return en_macro


SQL_TECNICAS = """SELECT t.id, t.estudio_id, t.numero, t.fragmentos, t.inclusion, t.tacos, t.cassettes, t.comentarios, t.creado_en, u.iniciales
                  FROM tecnicas t JOIN estudios e ON e.id=t.estudio_id LEFT JOIN usuarios u ON u.id=t.usuario_id
                  WHERE e.protocolo_id=? AND e.tipo=? AND e.anulado=0 ORDER BY t.id"""
INCLUSIONES = ("Reserva", "Inclusión total")
INCLUSION_POR_LOTE = {"ENDO": "Inclusión total"}
FRAGMENTOS_VARIOS = 4
OPCIONES_FRAGMENTOS = (("1", 1), ("2", 2), ("3", 3), ("Varios (más de 3)", FRAGMENTOS_VARIOS))


def fragmentos_de(valor):
    texto = (valor or "").strip().lower()
    if texto.startswith("varios"):
        return FRAGMENTOS_VARIOS
    n = entero_positivo(texto)
    return None if not n else min(n, FRAGMENTOS_VARIOS)


def rotulo_fragmentos(n):
    if n is None:
        return ""
    return "Varios" if n >= FRAGMENTOS_VARIOS else str(n)


def estudios_sin_tecnicas(miembros):
    if not miembros:
        return []
    con = {r["estudio_id"] for r in db.q(f"SELECT DISTINCT estudio_id FROM tecnicas WHERE estudio_id IN ({','.join('?' * len(miembros))})", [m["id"] for m in miembros])}
    return [m for m in miembros if m["id"] not in con]


def sumar_cassettes(e):
    total = db.uno("""SELECT SUM(t.cassettes) AS n FROM tecnicas t JOIN estudios x ON x.id=t.estudio_id
                      WHERE x.protocolo_id=? AND x.tipo=? AND x.anulado=0""", (e["protocolo_id"], e["tipo"]))["n"]
    guardar_seccion("macro", e["flujo_id"], {"cassettes": total})


def lista_marcadores(texto):
    return list(dict.fromkeys(x.strip() for x in re.split(r"[,;\n]+", texto or "") if x.strip()))


def pedido_ihq_confirmado(micro, ihq):
    return bool(ihq and ihq["pedido_en"])


def guardar_seccion(tabla, flujo_id, valores):
    if db.uno(f"SELECT 1 FROM {tabla} WHERE flujo_id=?", (flujo_id,)):
        db.ex(f"UPDATE {tabla} SET {', '.join(k + '=?' for k in valores)} WHERE flujo_id=?", list(valores.values()) + [flujo_id])
    else:
        db.ex(f"INSERT INTO {tabla} (flujo_id, {', '.join(valores)}) VALUES (?,{','.join('?' * len(valores))})",
              [flujo_id] + list(valores.values()))


def entero_positivo(valor, maximo=999):
    valor = (valor or "").strip()
    return int(valor) if valor.isdigit() and 1 <= int(valor) <= maximo else None


def motivo_no_listo(yo, tipo, etapa, prox, solicita, macro, micro, ihq, sin_tecnicas):
    falta = None if etapa in PASOS_IHQ and not solicita else REGISTRO[tipo].requisito(etapa, macro, micro, ihq)
    if not falta and solicita and (etapa == "microscopia" or etapa in PASOS_IHQ) and not pedido_ihq_confirmado(micro, ihq):
        falta = "Falta confirmar el pedido de IHQ: cargá los marcadores y apretá «Confirmar pedido de IHQ»."
    if not falta and sin_tecnicas:
        falta = "Faltan las técnicas de: " + ", ".join(etiqueta(m) for m in sin_tecnicas) + "."
    if not prox or prox[0] != etapa:
        return "Esa etapa no es la próxima pendiente de este estudio."
    if not yo["admin"] and not sector_marca((yo["sectores"] or "").split(","), tipo, etapa, prox[2]):
        return f"La etapa {prox[1]} la marca el sector {SECTORES[prox[2]]}."
    return falta


SQL_INFORME_EMITIDO = """SELECT i.id, i.version, i.creado_en, i.comentario, i.estudios, u.iniciales, u.nombre AS generado_por, f.nombre AS firmante
                     FROM informes_emitidos i LEFT JOIN usuarios u ON u.id=i.usuario_id LEFT JOIN usuarios f ON f.id=i.firmante_id
                     WHERE i.protocolo_id=?"""


def informe_emitido(pid):
    return db.uno(SQL_INFORME_EMITIDO, (pid,))


def informe_vigente(pid, emitido):
    if not emitido or not protocolo_cerrado(pid):
        return False
    if not emitido["estudios"]:
        return True
    activos = {str(x["id"]) for x in cargar_estudios("e.protocolo_id=?", (pid,), borradores=True) if not x["anulado"]}
    return set(emitido["estudios"].split(",")) == activos


def auditar_autoguardado(yo, e, accion):
    desde = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    if not db.uno("SELECT 1 FROM auditoria WHERE estudio_id=? AND accion=? AND usuario_id=? AND fecha_hora>=?", (e["id"], accion, yo["id"], desde)):
        db.auditar(yo["id"], e["protocolo_id"], accion, "autoguardado", e["id"])
