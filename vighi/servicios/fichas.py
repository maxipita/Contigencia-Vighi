from flask import abort

from vighi.core import db
from vighi.core.fechas import fecha_hora
from vighi.core.sesion import puede
from vighi.dominio.estudios import NOMBRE_ETAPA, PASOS_IHQ, REGISTRO, SECTORES, Variante
from vighi.servicios.consultas import cargar_estudios, etiqueta, protocolo_cerrado, variante_de


DUENO = ("(SELECT CASE WHEN d.anulado=1 THEN d.id ELSE (SELECT MIN(x.id) FROM estudios x WHERE x.protocolo_id=d.protocolo_id "
         "AND x.tipo=d.tipo AND x.anulado=0) END FROM estudios d WHERE d.id=?)")
SQL_FICHA = """SELECT e.*, p.numero, p.borrador, p.fecha_recoleccion, p.apellido, p.nombre, p.dni, p.medico, p.cobertura,
                         u.iniciales AS responsable, u2.iniciales AS creador, l.codigo AS lote, """ + DUENO.replace("?", "e.id") + """ AS dueno
                  FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                  LEFT JOIN usuarios u ON u.id=e.responsable_id LEFT JOIN usuarios u2 ON u2.id=e.creado_por
                  LEFT JOIN lotes l ON l.id=e.lote_id WHERE e.id=?"""
SQL_ETAPAS_FICHA = """SELECT x.*, u.iniciales, u.nombre FROM etapas x
                                            JOIN usuarios u ON u.id=x.usuario_id WHERE estudio_id=?"""
SQL_ULTIMA_ETAPA = "SELECT * FROM etapas WHERE estudio_id=? ORDER BY fecha_hora DESC, id DESC LIMIT 1"
SQL_HISTORIAL_ESTUDIO = """SELECT a.*, u.iniciales FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id
                        WHERE a.estudio_id IN (SELECT x.id FROM estudios x JOIN estudios d ON d.protocolo_id=x.protocolo_id AND d.tipo=x.tipo
                                               WHERE d.id=? AND (d.anulado=1 AND x.id=d.id OR d.anulado=0 AND x.anulado=0))
                        ORDER BY a.id DESC"""
SQL_MACRO = "SELECT * FROM macro WHERE estudio_id=" + DUENO
SQL_MICRO = "SELECT * FROM micro WHERE estudio_id=" + DUENO
SQL_IHQ = "SELECT * FROM ihq WHERE estudio_id=" + DUENO
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
    solicita = (Variante(micro and micro["solicita_ihq"], macro and macro["decal"]) if e["anulado"]
                else variante_de(e["protocolo_id"], e["tipo"]))
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


def estudios_sin_tecnicas(miembros):
    if not miembros:
        return []
    con = {r["estudio_id"] for r in db.q(f"SELECT DISTINCT estudio_id FROM tecnicas WHERE estudio_id IN ({','.join('?' * len(miembros))})", [m["id"] for m in miembros])}
    return [m for m in miembros if m["id"] not in con]


def sumar_cassettes(e):
    total = db.uno("""SELECT SUM(t.cassettes) AS n FROM tecnicas t JOIN estudios x ON x.id=t.estudio_id
                      WHERE x.protocolo_id=? AND x.tipo=? AND x.anulado=0""", (e["protocolo_id"], e["tipo"]))["n"]
    guardar_seccion("macro", e["dueno"], {"cassettes": total})


def guardar_seccion(tabla, eid, valores):
    if db.uno(f"SELECT 1 FROM {tabla} WHERE estudio_id=?", (eid,)):
        db.ex(f"UPDATE {tabla} SET {', '.join(k + '=?' for k in valores)} WHERE estudio_id=?", list(valores.values()) + [eid])
    else:
        db.ex(f"INSERT INTO {tabla} (estudio_id, {', '.join(valores)}) VALUES (?,{','.join('?' * len(valores))})",
              [eid] + list(valores.values()))


def entero_positivo(valor, maximo=999):
    valor = (valor or "").strip()
    return int(valor) if valor.isdigit() and 1 <= int(valor) <= maximo else None


def motivo_no_listo(yo, tipo, etapa, prox, solicita, macro, micro, ihq, sin_tecnicas):
    falta = None if etapa in PASOS_IHQ and not solicita else REGISTRO[tipo].requisito(etapa, macro, micro, ihq)
    if not falta and sin_tecnicas:
        falta = "Faltan las técnicas de: " + ", ".join(etiqueta(m) for m in sin_tecnicas) + "."
    if not prox or prox[0] != etapa:
        return "Esa etapa no es la próxima pendiente de este estudio."
    if not yo["admin"] and prox[2] not in (yo["sectores"] or "").split(","):
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
