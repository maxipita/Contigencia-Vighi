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
