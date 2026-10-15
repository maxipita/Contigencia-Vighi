import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()

fallas = []


def chequear(nombre, ok, detalle=""):
    print(("  OK   " if ok else "  FALLA"), nombre, "" if ok else detalle)
    if not ok:
        fallas.append(nombre)


def cliente(uid):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["uid"] = uid
    c.get("/")
    with c.session_transaction() as s:
        return c, s["csrf"]


with A.app.app_context():
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000701','2026-10-14','Garcia','Lucia',?,?)", (admin, db.ahora()))
    tipo = db.uno("SELECT id FROM tarea_tipos WHERE titulo='Presupuesto'")["id"]
    nuevo = db.uno("SELECT id FROM tarea_tipos WHERE titulo='Nuevo corte'")["id"]

c, csrf = cliente(admin)


def crear(titulo_id, resp, urgencia="regular", prioridad="media", descripcion=""):
    c.post(f"/protocolo/{pid}/tarea/nueva", data={"_csrf": csrf, "tipo": str(titulo_id), "responsable_id": str(resp) if resp else "", "urgencia": urgencia,
                                                  "prioridad": prioridad, "descripcion": descripcion})


def tareas():
    with A.app.app_context():
        return [dict(r) for r in db.q("SELECT * FROM tareas ORDER BY id")]


def cuenta(cl):
    m = re.search(r'title="Tareas"[^>]*>.*?(?:<span class="cuenta([^"]*)"[^>]*>(\d+)</span>)?</a>', cl.get("/").get_data(as_text=True), re.S)
    return (int(m.group(2)), m.group(1).strip()) if m and m.group(2) else None


print("1) contador en la barra")
h = c.get("/").get_data(as_text=True)
chequear("hay un botón Tareas en la barra", 'href="/tareas"' in h and 'title="Tareas"' in h)
chequear("sin tareas asignadas no hay contador", cuenta(c) is None)
crear(tipo, admin, "regular", "baja", "la mía regular")
chequear("con una tarea muestra 1 sin color de urgente", cuenta(c) == (1, ""), str(cuenta(c)))
crear(nuevo, admin, "urgente", "alta", "la mía urgente")
chequear("con una urgente suma y se marca", cuenta(c) == (2, "urgente"), str(cuenta(c)))
crear(tipo, ids["med"], "regular", "media", "de otro")
crear(tipo, None, "regular", "media", "sin dueño")
chequear("las de otros o sin responsable no cuentan", cuenta(c) == (2, "urgente"))
o, ocsrf = cliente(ids["med"])
chequear("el otro usuario ve su propia cantidad", cuenta(o) == (1, ""), str(cuenta(o)))
x, _ = cliente(ids["cito"])
chequear("quien no tiene tareas no ve número", cuenta(x) is None)
t = tareas()
c.post(f"/tarea/{t[0]['id']}/cerrar", data={"_csrf": csrf})
chequear("al cerrarla baja el contador", cuenta(c) == (1, "urgente"), str(cuenta(c)))

print("2) la pantalla")
h = c.get("/tareas").get_data(as_text=True)
chequear("por defecto muestra las mías abiertas", "la mía urgente" in h and "la mía regular" not in h and "de otro" not in h and "sin dueño" not in h)
chequear("con el protocolo, el paciente y el enlace", "C000701" in h and "Garcia, Lucia" in h and f'href="/protocolo/{pid}#tareas"' in h)
h = c.get("/tareas?resp=todos").get_data(as_text=True)
chequear("todos: las abiertas de todos", all(x in h for x in ("la mía urgente", "de otro", "sin dueño")) and "la mía regular" not in h)
chequear("las urgentes salen primero", h.index("la mía urgente") < h.index("de otro"))
h = c.get("/tareas?resp=sin").get_data(as_text=True)
chequear("sin asignar", "sin dueño" in h and "de otro" not in h and "la mía urgente" not in h)
h = c.get(f"/tareas?resp={ids['med']}").get_data(as_text=True)
chequear("las de otra persona", "de otro" in h and "la mía urgente" not in h)
h = c.get("/tareas?estado=cerradas").get_data(as_text=True)
chequear("cerradas", "la mía regular" in h and "la mía urgente" not in h and "Reabrir" in h)
h = c.get("/tareas?resp=todos&estado=todas").get_data(as_text=True)
chequear("todas", all(x in h for x in ("la mía regular", "la mía urgente", "de otro", "sin dueño")))
h = c.get("/tareas?resp=raro&estado=raro").get_data(as_text=True)
chequear("un filtro inválido vuelve al valor por defecto", "la mía urgente" in h and "de otro" not in h)

print("3) acciones desde la lista")
abierta = [x for x in tareas() if x["descripcion"] == "de otro"][0]
r = c.post(f"/tarea/{abierta['id']}/responsable", data={"_csrf": csrf, "responsable_id": str(admin)}, headers={"Referer": "http://localhost/tareas?resp=todos"})
chequear("reasignar vuelve a la lista", r.status_code == 302 and "/tareas?resp=todos" in r.headers["Location"], r.headers.get("Location"))
chequear("y pasa a mis tareas", cuenta(c) == (2, "urgente"))
sin = A.app.test_client()
chequear("sin sesión no entra", sin.get("/tareas").status_code in (302, 401, 403))

print()
print("FALLAS:", fallas if fallas else "ninguna")
