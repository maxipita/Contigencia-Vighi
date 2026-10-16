import os
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


def tareas(pid):
    with A.app.app_context():
        return [dict(r) for r in db.q("SELECT * FROM tareas WHERE protocolo_id=? ORDER BY id", (pid,))]


def auditorias(accion):
    with A.app.app_context():
        return [r["detalle"] for r in db.q("SELECT detalle FROM auditoria WHERE accion=? ORDER BY id", (accion,))]


with A.app.app_context():
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, medico, lugar_recoleccion, creado_por, creado_en) VALUES ('C000501','2026-10-14','Perez','Ana','Gomez','ACOYTE1200',?,?)", (admin, db.ahora()))
    pid2 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000502','2026-10-14','Otro','Pac',?,?)", (admin, db.ahora()))
    macro = db.uno("SELECT id FROM tarea_tipos WHERE titulo='Macro urgente'")["id"]
    presupuesto = db.uno("SELECT id FROM tarea_tipos WHERE titulo='Presupuesto'")["id"]
    db.ex("UPDATE tarea_tipos SET responsable_id=? WHERE id=?", (ids["med"], macro))

c, csrf = cliente(admin)

h = c.get(f"/protocolo/{pid}").get_data(as_text=True)
chequear("la ficha tiene la tarjeta de tareas, vacía", 'id="tareas"' in h and "No hay tareas abiertas." in h and "Crear una tarea" in h)

print("1) nueva tarea")
h = c.get(f"/protocolo/{pid}/tarea/nueva").get_data(as_text=True)
chequear("la pantalla muestra el protocolo, el catálogo y los sectores", all(x in h for x in ("Nueva tarea", "Perez, Ana", "ACOYTE1200", "Macro urgente", "Solicitud taco", "Laboratorio", "Notificar por e-mail")))
chequear("el responsable del catálogo viaja en el asunto", f'value="{macro}" data-responsable="{ids["med"]}"' in h)
datos = {"_csrf": csrf, "tipo": str(macro), "descripcion": "Para hoy a la tarde", "responsable_id": str(ids["med"]), "urgencia": "urgente", "prioridad": "alta"}
r = c.post(f"/protocolo/{pid}/tarea/nueva", data=datos, follow_redirects=True)
t = tareas(pid)
chequear("la crea con sus datos y vuelve a la ficha", len(t) == 1 and t[0]["titulo"] == "Macro urgente" and t[0]["urgencia"] == "urgente" and t[0]["prioridad"] == "alta"
         and t[0]["responsable_id"] == ids["med"] and t[0]["estado"] == "abierta" and t[0]["cierre"] == "procesamiento" and t[0]["creado_por"] == admin
         and "Tarea «Macro urgente» creada" in r.get_data(as_text=True))
h = r.get_data(as_text=True)
chequear("la tarjeta la lista", "Macro urgente" in h and "Urgente" in h and "Responsable:" in h and "Cerrar tarea" in h and "Para hoy a la tarde" not in h and "Prioridad alta" not in h)
chequear("queda en el historial", len(auditorias("tarea_nueva")) == 1 and "Macro urgente" in auditorias("tarea_nueva")[0])
chequear("no aparece en otro protocolo", "Macro urgente" not in c.get(f"/protocolo/{pid2}").get_data(as_text=True))

r = c.post(f"/protocolo/{pid}/tarea/nueva", data={"_csrf": csrf, "tipo": str(presupuesto), "urgencia": "regular", "prioridad": "media"}, follow_redirects=True)
t = tareas(pid)
chequear("sin descripción ni responsable también se puede", len(t) == 2 and t[1]["responsable_id"] is None and t[1]["descripcion"] is None and t[1]["cierre"] is None)

n = len(tareas(pid))
for nombre, cambio, texto in (("sin asunto", {"tipo": ""}, "Elegí el asunto"), ("asunto inventado", {"tipo": "99999"}, "Elegí el asunto"),
                              ("responsable inexistente", {"responsable_id": "99999"}, "Elegí un responsable"), ("urgencia inválida", {"urgencia": "ya"}, "urgencia y la prioridad"),
                              ("prioridad inválida", {"prioridad": "maxima"}, "urgencia y la prioridad"), ("descripción enorme", {"descripcion": "x" * 2001}, "demasiado larga")):
    r = c.post(f"/protocolo/{pid}/tarea/nueva", data={**datos, **cambio}, follow_redirects=True)
    chequear(f"rechaza {nombre}", len(tareas(pid)) == n and texto in r.get_data(as_text=True))
chequear("un protocolo inexistente da 404", c.get("/protocolo/99999/tarea/nueva").status_code == 404)

print("2) reasignar")
t1, t2 = tareas(pid)
r = c.post(f"/tarea/{t1['id']}/responsable", data={"_csrf": csrf, "responsable_id": str(ids["otro"])}, follow_redirects=True)
chequear("cambia el responsable", tareas(pid)[0]["responsable_id"] == ids["otro"] and "Responsable actualizado" in r.get_data(as_text=True))
chequear("y lo deja en el historial", any("→ ZZOT" in x for x in auditorias("tarea_responsable")))
c.post(f"/tarea/{t1['id']}/responsable", data={"_csrf": csrf, "responsable_id": ""})
chequear("se puede dejar sin asignar", tareas(pid)[0]["responsable_id"] is None)
r = c.post(f"/tarea/{t1['id']}/responsable", data={"_csrf": csrf, "responsable_id": "99999"}, follow_redirects=True)
chequear("rechaza un responsable inexistente", "Elegí un responsable" in r.get_data(as_text=True) and tareas(pid)[0]["responsable_id"] is None)
chequear("una tarea inexistente da 404", c.post("/tarea/99999/responsable", data={"_csrf": csrf}).status_code == 404)

print("3) cerrar y reabrir")
r = c.post(f"/tarea/{t1['id']}/cerrar", data={"_csrf": csrf}, follow_redirects=True)
t = tareas(pid)[0]
chequear("la cierra a mano y deja quién y cuándo", t["estado"] == "cerrada" and t["cerrada_por"] == admin and t["cerrada_en"] and t["cierre_detalle"] == "a mano" and "cerrada" in r.get_data(as_text=True))
h = r.get_data(as_text=True)
chequear("pasa a Cerradas y la otra sigue abierta", "Cerradas (1)" in h and "Cerrada por" in h and "Cerrar tarea" in h)
chequear("queda en el historial", len(auditorias("tarea_cerrada")) == 1)
c.post(f"/tarea/{t1['id']}/cerrar", data={"_csrf": csrf})
chequear("cerrarla dos veces no repite el historial", len(auditorias("tarea_cerrada")) == 1)
r = c.post(f"/tarea/{t1['id']}/responsable", data={"_csrf": csrf, "responsable_id": str(ids["med"])}, follow_redirects=True)
chequear("cerrada no se reasigna", tareas(pid)[0]["responsable_id"] is None and "reabrila" in r.get_data(as_text=True))
c.post(f"/tarea/{t1['id']}/reabrir", data={"_csrf": csrf})
t = tareas(pid)[0]
chequear("se reabre y limpia el cierre", t["estado"] == "abierta" and t["cerrada_por"] is None and t["cerrada_en"] is None and t["cierre_detalle"] is None and len(auditorias("tarea_reabierta")) == 1)

print("4) quién entra")
sin = A.app.test_client()
chequear("sin sesión no entra", sin.get(f"/protocolo/{pid}/tarea/nueva").status_code in (302, 401, 403))
otro, ocsrf = cliente(ids["cito"])
otro.post(f"/protocolo/{pid}/tarea/nueva", data={**datos, "_csrf": ocsrf})
chequear("cualquier usuario con sesión puede crear", len(tareas(pid)) == n + 1)
r = c.post(f"/tarea/{t1['id']}/cerrar", data={})
chequear("sin el token de seguridad se rechaza", r.status_code == 400 and tareas(pid)[0]["estado"] == "abierta")

print()
print("FALLAS:", fallas if fallas else "ninguna")
