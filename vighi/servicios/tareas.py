from vighi.core import db
from vighi.dominio.estudios import ETAPAS

ENTREGA = "entrega"
CIERRES = {**{k: v[4] for k, v in ETAPAS.items() if k != "ingreso"}, ENTREGA: "Cons > Entregar"}
SQL_TIPOS_TAREA = """SELECT t.id, t.titulo, t.responsable_id, t.cierre, u.iniciales, u.nombre AS responsable
                     FROM tarea_tipos t LEFT JOIN usuarios u ON u.id=t.responsable_id ORDER BY t.titulo"""


def tipos_de_tarea():
    return [{**dict(r), "cierre_texto": CIERRES.get(r["cierre"], "")} for r in db.q(SQL_TIPOS_TAREA)]


def usuarios_para_tareas():
    return db.q("SELECT id, iniciales, nombre FROM usuarios WHERE activo=1 ORDER BY iniciales")
