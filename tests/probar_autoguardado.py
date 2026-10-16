import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.dominio.estudios import REGISTRO

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
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000401','2026-10-14','Test','Auto',?,?)", (admin, db.ahora()))
    insertar = ("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)")
    e1 = db.ex(insertar, (pid, "BP", "Biopsias", "Ginecológica", "Endometrio", "Biopsia", "1", ids["med"], admin, db.ahora()))
    pid2 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000402','2026-10-14','Test','Micro',?,?)", (admin, db.ahora()))
    e2 = db.ex(insertar, (pid2, "BP", "Biopsias", "Ginecológica", "Endometrio", "Biopsia", "1", ids["med"], admin, db.ahora()))
    for clave, _, _ in REGISTRO["BP"].flujo(0):
        if clave == "microscopia":
            break
        db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES ((SELECT flujo_id FROM estudios WHERE id=?),?,?,?)", (e2, clave, admin, db.ahora()))

c, csrf = cliente(admin)


def autoguardar(ruta, **datos):
    return c.post(ruta, data=dict(datos, _csrf=csrf, autoguardar="1"), headers={"Accept": "application/json"})


def fila(tabla, eid):
    with A.app.app_context():
        r = db.uno(f"SELECT * FROM {tabla} WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (eid,))
        return dict(r) if r else None


def auditorias(accion, eid):
    with A.app.app_context():
        return [r["detalle"] for r in db.q("SELECT detalle FROM auditoria WHERE accion=? AND estudio_id=?", (accion, eid))]


h = c.get(f"/estudio/{e1}").get_data(as_text=True)
chequear("la macroscopía se guarda sola (formulario marcado y con su indicador)", f'/estudio/{e1}/macro" data-autoguardar' in h and "data-autoestado" in h)
chequear("el JS del autoguardado está en la página", "form[data-autoguardar]" in c.get("/static/app.js").get_data(as_text=True))

print("1) macroscopía")
r = autoguardar(f"/estudio/{e1}/macro", template="Uno", descripcion="Fragmento pardo de 0,3 cm.", decal="1", decal_presente="1")
chequear("responde JSON y no redirige", r.status_code == 200 and r.get_json()["ok"] is True and "hora" in r.get_json(), r.get_data(as_text=True)[:100])
m = fila("macro", e1)
chequear("guarda el texto", m and m["descripcion"] == "Fragmento pardo de 0,3 cm." and m["template"] == "Uno")
chequear("pero no toca la decalcificación (se cambia al guardar)", m["decal"] == 0)
autoguardar(f"/estudio/{e1}/macro", template="Uno", descripcion="Fragmento pardo de 0,3 cm. Se incluye todo.")
chequear("vuelve a guardar al seguir escribiendo", fila("macro", e1)["descripcion"].endswith("Se incluye todo."))
chequear("el historial tiene una sola línea de autoguardado, no una por cada vez", auditorias("guardar_macro", e1) == ["autoguardado"], str(auditorias("guardar_macro", e1)))
r = c.post(f"/estudio/{e1}/macro", data={"_csrf": csrf, "descripcion": "Texto final", "decal_presente": "1", "decal": "1"}, follow_redirects=True)
chequear("el botón Guardar sigue funcionando como siempre", fila("macro", e1)["descripcion"] == "Texto final" and fila("macro", e1)["decal"] == 1 and "Macroscopía guardada" in r.get_data(as_text=True))
autoguardar(f"/estudio/{e1}/macro", template="", descripcion="Otro texto", y_listo="1")
with A.app.app_context():
    chequear("no se completó ninguna etapa", db.uno("SELECT COUNT(*) AS n FROM etapas WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (e1,))["n"] == 0)

print("2) microscopía")
r = autoguardar(f"/estudio/{e1}/micro", descripcion="Aún no corresponde", conclusion="")
chequear("si la etapa todavía no está habilitada responde error y no guarda", r.status_code == 409 and r.get_json()["ok"] is False and fila("micro", e1) is None, r.get_data(as_text=True)[:120])
r = autoguardar(f"/estudio/{e2}/micro", template="T", descripcion="Cortes con infiltrado.", conclusion="Endometrio proliferativo.", bethesda="")
mi = fila("micro", e2)
chequear("guarda descripción y conclusión", r.status_code == 200 and mi and mi["descripcion"] == "Cortes con infiltrado." and mi["conclusion"] == "Endometrio proliferativo.")
chequear("el autoguardado de la microscopía ya no activa la IHQ", mi["solicita_ihq"] == 0)
chequear("el historial tiene una sola línea de autoguardado", auditorias("guardar_micro", e2) == ["autoguardado"], str(auditorias("guardar_micro", e2)))
h = c.get(f"/estudio/{e2}").get_data(as_text=True)
chequear("la tarjeta de IHQ está en la página pero oculta hasta que se pida", 'id="ihq" hidden' in h)
chequear("el selector «¿Solicita IHQ?» ya no guarda por sí solo (sin nombre de campo)", "data-ihq-toggle" in h and 'name="solicita_ihq"' not in h)

print("3) IHQ: borrador, confirmación y resultado")
r = autoguardar(f"/estudio/{e2}/ihq", marcadores="p53; Ki67, CK7, p53", resultado="No corresponde todavía")
ih = fila("ihq", e2)
chequear("el borrador guarda los marcadores como lista sin repetidos", r.status_code == 200 and ih["marcadores"] == "p53, Ki67, CK7", ih)
chequear("antes de confirmar no se guarda el resultado", not ih["resultado"])
chequear("y el estudio todavía no tiene IHQ en su tracking", fila("micro", e2)["solicita_ihq"] == 0)
with A.app.app_context():
    tareas_antes = db.uno("SELECT COUNT(*) AS n FROM tareas WHERE protocolo_id=?", (pid2,))["n"]
    resp = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZIHQ','Resp IHQ','laboratorio',0,1,0)")
    tipo_t = db.uno("SELECT id FROM tarea_tipos WHERE titulo LIKE 'Solicitud de IHQ'")
    if tipo_t:
        db.ex("UPDATE tarea_tipos SET responsable_id=? WHERE id=?", (resp, tipo_t["id"]))
    else:
        db.ex("INSERT INTO tarea_tipos (titulo, responsable_id) VALUES ('Solicitud de IHQ', ?)", (resp,))
r = c.post(f"/estudio/{e2}/ihq/pedir", data={"_csrf": csrf, "marcadores": ""}, follow_redirects=True)
chequear("no se confirma sin marcadores... con el borrador guardado sí", "Pedido de IHQ confirmado (3 marcador(es))" in r.get_data(as_text=True), r.get_data(as_text=True)[:200])
with A.app.app_context():
    t = db.uno("SELECT * FROM tareas WHERE protocolo_id=? ORDER BY id DESC", (pid2,))
    n_tareas = db.uno("SELECT COUNT(*) AS n FROM tareas WHERE protocolo_id=?", (pid2,))["n"]
chequear("se crea la tarea «Solicitud de IHQ» para el responsable asignado", n_tareas == tareas_antes + 1 and t["titulo"] == "Solicitud de IHQ" and t["responsable_id"] == resp, dict(t) if t else None)
chequear("la tarea enlista los marcadores pedidos", t and "- p53" in t["descripcion"] and "- Ki67" in t["descripcion"] and "- CK7" in t["descripcion"] and "(3)" in t["descripcion"], t["descripcion"] if t else None)
mi = fila("micro", e2)
ih = fila("ihq", e2)
chequear("al confirmar arranca el tracking de IHQ y queda registrado quién y cuándo", mi["solicita_ihq"] == 1 and ih["pedido_en"] and ih["pedido_por"] == admin, (mi, ih))
chequear("el historial deja el pedido con los marcadores", auditorias("pedido_ihq", e2) == ["p53, Ki67, CK7"], str(auditorias("pedido_ihq", e2)))
r = c.post(f"/estudio/{e2}/ihq/pedir", data={"_csrf": csrf, "marcadores": "p16"}, follow_redirects=True)
with A.app.app_context():
    n2 = db.uno("SELECT COUNT(*) AS n FROM tareas WHERE protocolo_id=?", (pid2,))["n"]
chequear("confirmar de nuevo no duplica la tarea ni cambia los marcadores", n2 == n_tareas and "ya estaba confirmado" in r.get_data(as_text=True) and fila("ihq", e2)["marcadores"] == "p53, Ki67, CK7")
r = autoguardar(f"/estudio/{e2}/ihq", marcadores="otro", resultado="Positivo difuso")
ih = fila("ihq", e2)
chequear("confirmado el pedido, el autoguardado guarda el resultado y no toca los marcadores", ih["resultado"] == "Positivo difuso" and ih["marcadores"] == "p53, Ki67, CK7", ih)
h = c.get(f"/estudio/{e2}").get_data(as_text=True)
chequear("la pantalla muestra los marcadores como lista y el resultado", "<li>Ki67</li>" in h and "Pedido confirmado" in h and "Positivo difuso" in h)
r = c.post(f"/estudio/{e1}/ihq/pedir", data={"_csrf": csrf, "marcadores": "p53"}, follow_redirects=True)
chequear("sin llegar a la microscopía no se puede confirmar", "No se pudo confirmar" in r.get_data(as_text=True) and (fila("ihq", e1) is None or not fila("ihq", e1)["pedido_en"]))

print("4) permisos")
sin, scsrf = cliente(ids["sin"])
r = sin.post(f"/estudio/{e2}/micro", data={"_csrf": scsrf, "autoguardar": "1", "descripcion": "Intruso"}, follow_redirects=True)
chequear("sin permiso no guarda nada", fila("micro", e2)["descripcion"] == "Cortes con infiltrado.")
r = c.post(f"/estudio/{e2}/micro", data={"autoguardar": "1", "descripcion": "Sin token"})
chequear("sin el token de seguridad se rechaza", r.status_code == 400 and fila("micro", e2)["descripcion"] == "Cortes con infiltrado.")

print()
print("FALLAS:", fallas if fallas else "ninguna")
