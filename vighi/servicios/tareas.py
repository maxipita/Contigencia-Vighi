from vighi.core import db
from vighi.dominio.estudios import ETAPAS, SECTORES

ENTREGA = "entrega"
CIERRES = {**{k: v[4] for k, v in ETAPAS.items() if k != "ingreso"}, ENTREGA: "Cons > Entregar"}
SQL_TIPOS_TAREA = """SELECT t.id, t.titulo, t.responsable_id, t.cierre, u.iniciales, u.nombre AS responsable
                     FROM tarea_tipos t LEFT JOIN usuarios u ON u.id=t.responsable_id ORDER BY t.titulo"""


def tipos_de_tarea():
    return [{**dict(r), "cierre_texto": CIERRES.get(r["cierre"], "")} for r in db.q(SQL_TIPOS_TAREA)]


def usuarios_para_tareas():
    return db.q("SELECT id, iniciales, nombre FROM usuarios WHERE activo=1 ORDER BY iniciales")


URGENCIAS = {"regular": "Regular", "urgente": "Urgente"}
PRIORIDADES = {"baja": "Baja", "media": "Media", "alta": "Alta"}
SQL_TAREAS = """SELECT t.*, r.iniciales AS resp_iniciales, r.nombre AS resp_nombre, c.iniciales AS creador, x.iniciales AS cerrador
                FROM tareas t LEFT JOIN usuarios r ON r.id=t.responsable_id LEFT JOIN usuarios c ON c.id=t.creado_por
                LEFT JOIN usuarios x ON x.id=t.cerrada_por WHERE t.protocolo_id=? ORDER BY t.estado, t.id DESC"""


def tareas_de(pid):
    return db.q(SQL_TAREAS, (pid,))


SQL_USUARIOS_SECTORES = "SELECT id, iniciales, nombre, sectores FROM usuarios WHERE activo=1 ORDER BY iniciales"


def usuarios_con_sectores():
    return [{**dict(u), "sectores_lista": [x for x in (u["sectores"] or "").split(",") if x in SECTORES]} for u in db.q(SQL_USUARIOS_SECTORES)]


def responsable_valido(valor):
    if not valor:
        return None, None
    if valor.isdigit() and db.uno("SELECT 1 FROM usuarios WHERE id=? AND activo=1", (int(valor),)):
        return int(valor), None
    return None, "Elegí un responsable de la lista."


def validar_tarea(form):
    tipo = form.get("tipo", "")
    t = db.uno("SELECT * FROM tarea_tipos WHERE id=?", (int(tipo),)) if tipo.isdigit() else None
    descripcion = form.get("descripcion", "").strip()
    resp, error = responsable_valido(form.get("responsable_id", ""))
    if not t:
        error = "Elegí el asunto de la tarea."
    elif len(descripcion) > 2000:
        error = "La descripción es demasiado larga (máximo 2000 caracteres)."
    elif form.get("urgencia") not in URGENCIAS or form.get("prioridad") not in PRIORIDADES:
        error = "Elegí la urgencia y la prioridad."
    return t, descripcion, resp, error


def crear_tarea(pid, t, descripcion, urgencia, prioridad, resp, yo):
    tid = db.ex("INSERT INTO tareas (protocolo_id, titulo, descripcion, urgencia, prioridad, responsable_id, cierre, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, t["titulo"], descripcion or None, urgencia, prioridad, resp, t["cierre"], yo, db.ahora()))
    quien = db.uno("SELECT iniciales FROM usuarios WHERE id=?", (resp,)) if resp else None
    db.auditar(yo, pid, "tarea_nueva", f"{t['titulo']} ({URGENCIAS[urgencia]}, {PRIORIDADES[prioridad]}) → {quien['iniciales'] if quien else 'sin asignar'}")
    return tid


def sentencias_de_cierre(protocolos, clave, detalle, yo):
    protocolos = list(dict.fromkeys(protocolos))
    abiertas = []
    for i in range(0, len(protocolos), 80):
        grupo = protocolos[i:i + 80]
        abiertas += db.q(f"SELECT id, protocolo_id, titulo FROM tareas WHERE estado='abierta' AND cierre=? AND protocolo_id IN ({','.join('?' * len(grupo))})", (clave, *grupo))
    if not abiertas:
        return []
    ahora = db.ahora()
    sentencias = []
    for i in range(0, len(abiertas), 80):
        grupo = abiertas[i:i + 80]
        sentencias.append((f"UPDATE tareas SET estado='cerrada', cerrada_por=?, cerrada_en=?, cierre_detalle=? WHERE id IN ({','.join('?' * len(grupo))})",
                           (yo, ahora, detalle[:100], *(t["id"] for t in grupo))))
    for i in range(0, len(abiertas), 16):
        grupo = abiertas[i:i + 16]
        sentencias.append(("INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, estudio_id, accion, detalle) VALUES " + ",".join(["(?,?,?,?,?,?)"] * len(grupo)),
                           tuple(v for t in grupo for v in (ahora, yo, t["protocolo_id"], None, "tarea_cerrada", f"{t['titulo']} ({detalle})"))))
    return sentencias


def cerrar_por_etapa(protocolo_id, etapa, detalle, yo):
    sentencias = sentencias_de_cierre([protocolo_id], etapa, detalle, yo)
    if sentencias:
        db.lote_ex(sentencias)
    return sentencias


ESTADOS_LISTA = {"abiertas": "Abiertas", "cerradas": "Cerradas", "todas": "Todas"}


def listar_tareas(responsable, estado):
    condiciones, params = [], []
    if estado == "abiertas":
        condiciones.append("t.estado='abierta'")
    elif estado == "cerradas":
        condiciones.append("t.estado='cerrada'")
    if responsable == "sin":
        condiciones.append("t.responsable_id IS NULL")
    elif responsable.isdigit():
        condiciones.append("t.responsable_id=?")
        params.append(int(responsable))
    donde = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    return db.q(f"""SELECT t.*, p.numero, p.apellido, p.nombre AS pac_nombre, r.iniciales AS resp_iniciales, r.nombre AS resp_nombre, c.iniciales AS creador, x.iniciales AS cerrador
                    FROM tareas t JOIN protocolos p ON p.id=t.protocolo_id LEFT JOIN usuarios r ON r.id=t.responsable_id
                    LEFT JOIN usuarios c ON c.id=t.creado_por LEFT JOIN usuarios x ON x.id=t.cerrada_por {donde}
                    ORDER BY CASE t.estado WHEN 'abierta' THEN 0 ELSE 1 END, CASE t.urgencia WHEN 'urgente' THEN 0 ELSE 1 END,
                             CASE t.prioridad WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, t.id LIMIT 300""", params)
