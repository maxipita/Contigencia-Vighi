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
        db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (e2, clave, admin, db.ahora()))

c, csrf = cliente(admin)


def autoguardar(ruta, **datos):
    return c.post(ruta, data=dict(datos, _csrf=csrf, autoguardar="1"), headers={"Accept": "application/json"})


def fila(tabla, eid):
    with A.app.app_context():
        r = db.uno(f"SELECT * FROM {tabla} WHERE estudio_id=?", (eid,))
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
    chequear("no se completó ninguna etapa", db.uno("SELECT COUNT(*) AS n FROM etapas WHERE estudio_id=?", (e1,))["n"] == 0)

print("2) microscopía")
r = autoguardar(f"/estudio/{e1}/micro", descripcion="Aún no corresponde", conclusion="")
chequear("si la etapa todavía no está habilitada responde error y no guarda", r.status_code == 409 and r.get_json()["ok"] is False and fila("micro", e1) is None, r.get_data(as_text=True)[:120])
r = autoguardar(f"/estudio/{e2}/micro", template="T", descripcion="Cortes con infiltrado.", conclusion="Endometrio proliferativo.", bethesda="", solicita_ihq="1")
mi = fila("micro", e2)
chequear("guarda descripción y conclusión", r.status_code == 200 and mi and mi["descripcion"] == "Cortes con infiltrado." and mi["conclusion"] == "Endometrio proliferativo.")
chequear("sin tocar «¿Solicita IHQ?»", mi["solicita_ihq"] == 0)
chequear("una sola línea de historial", auditorias("guardar_micro", e2) == ["autoguardado"])

print("3) IHQ")
r = autoguardar(f"/estudio/{e2}/ihq", marcadores="p53, Ki67", resultado="Positivo")
ih = fila("ihq", e2)
chequear("guarda marcadores y resultado", r.status_code == 200 and ih["marcadores"] == "p53, Ki67" and ih["resultado"] == "Positivo")

print("4) permisos")
sin, scsrf = cliente(ids["sin"])
r = sin.post(f"/estudio/{e2}/micro", data={"_csrf": scsrf, "autoguardar": "1", "descripcion": "Intruso"}, follow_redirects=True)
chequear("sin permiso no guarda nada", fila("micro", e2)["descripcion"] == "Cortes con infiltrado.")
r = c.post(f"/estudio/{e2}/micro", data={"autoguardar": "1", "descripcion": "Sin token"})
chequear("sin el token de seguridad se rechaza", r.status_code == 400 and fila("micro", e2)["descripcion"] == "Cortes con infiltrado.")

print()
print("FALLAS:", fallas if fallas else "ninguna")
