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


c = A.app.test_client()
with c.session_transaction() as s:
    s["uid"] = admin
c.get("/")
with c.session_transaction() as s:
    csrf = s["csrf"]
H = {"Accept": "application/json"}


def tareas(pid):
    with A.app.app_context():
        return {r["titulo"]: dict(r) for r in db.q("SELECT * FROM tareas WHERE protocolo_id=?", (pid,))}


def auditorias(accion):
    with A.app.app_context():
        return [r["detalle"] for r in db.q("SELECT detalle FROM auditoria WHERE accion=? ORDER BY id", (accion,))]


insertar = ("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)")
with A.app.app_context():
    def protocolo(numero, email=None):
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, email, creado_por, creado_en) VALUES (?,?,?,?,?,?,?)",
                    (numero, "2026-10-14", "Test", numero, email, admin, db.ahora()))
        eid = db.ex(insertar, (pid, "BP", "Biopsias", "Ginecológica", "Endometrio", "Biopsia", "1", ids["med"], admin, db.ahora()))
        return pid, eid
    p1, e1 = protocolo("C000601")
    p2, e2 = protocolo("C000602")
    p3, e3 = protocolo("C000603", "ana@correo.com")
    for eid in (e1, e2):
        db.ex("INSERT INTO macro (estudio_id, descripcion) VALUES (?, 'macro de prueba')", (eid,))
        db.ex("INSERT INTO tecnicas (estudio_id, numero, fragmentos, inclusion, tacos, cassettes, comentarios, usuario_id, creado_en) VALUES (?, 'A', 1, 'Reserva', 1, 1, '', ?, '2026-10-14 10:00:00')", (eid, admin))
    for clave, _, _ in REGISTRO["BP"].flujo(0):
        db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (e3, clave, admin, db.ahora()))
    db.ex("INSERT INTO informes_emitidos (protocolo_id, version, usuario_id, firmante_id, creado_en, archivo, pdf) VALUES (?,?,?,?,?,?,?)",
          (p3, 1, admin, ids["med"], "2026-10-15 10:00:00", "Informe.pdf", b"%PDF-1.4 prueba"))
    db.ex("INSERT INTO tarea_tipos (titulo, cierre) VALUES ('T macro','macroscopia'), ('T proc','procesamiento'), ('T entrega','entrega'), ('T manual', NULL)")
    tipos = {r["titulo"]: r["id"] for r in db.q("SELECT id, titulo FROM tarea_tipos")}


def crear(pid, *titulos):
    for t in titulos:
        c.post(f"/protocolo/{pid}/tarea/nueva", data={"_csrf": csrf, "tipo": str(tipos[t]), "urgencia": "regular", "prioridad": "media"})


for p in (p1, p2, p3):
    crear(p, "T macro", "T proc", "T entrega", "T manual")

print("1) al completar una etapa")
r = c.post(f"/estudio/{e1}/listo/macroscopia", data={"_csrf": csrf}, follow_redirects=True)
t = tareas(p1)
chequear("se cierra la tarea de esa etapa", t["T macro"]["estado"] == "cerrada" and t["T macro"]["cerrada_por"] == admin and t["T macro"]["cierre_detalle"] == "Macroscopía"
         and "Se cerraron las tareas" in r.get_data(as_text=True))
chequear("las demás siguen abiertas", all(t[x]["estado"] == "abierta" for x in ("T proc", "T entrega", "T manual")))
chequear("no toca otros protocolos", all(x["estado"] == "abierta" for x in tareas(p2).values()))
chequear("queda en el historial", any("T macro (Macroscopía)" in x for x in auditorias("tarea_cerrada")))
c.post(f"/estudio/{e1}/listo/procesamiento", data={"_csrf": csrf})
t = tareas(p1)
chequear("la siguiente etapa cierra la suya", t["T proc"]["estado"] == "cerrada" and t["T entrega"]["estado"] == "abierta" and t["T manual"]["estado"] == "abierta")
c.post(f"/estudio/{e1}/deshacer", data={"_csrf": csrf})
chequear("deshacer la etapa no reabre la tarea", tareas(p1)["T proc"]["estado"] == "cerrada")
crear(p1, "T proc")
c.post(f"/estudio/{e1}/listo/procesamiento", data={"_csrf": csrf})
with A.app.app_context():
    nuevas = [r for r in db.q("SELECT estado FROM tareas WHERE protocolo_id=? AND titulo='T proc'", (p1,))]
chequear("una tarea nueva se cierra con la próxima vez que se completa", [r["estado"] for r in nuevas] == ["cerrada", "cerrada"])
chequear("una etapa sin tareas no hace nada raro", c.post(f"/estudio/{e1}/listo/inclusion", data={"_csrf": csrf}).status_code in (200, 302))

print("2) al avanzar un lote")
with A.app.app_context():
    db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, cerrado, creado_por, creado_en) VALUES ('ENDO-1014.9','ENDO','2026-10-14',9,0,?,?)", (admin, db.ahora()))
    lid = db.uno("SELECT id FROM lotes WHERE codigo='ENDO-1014.9'")["id"]
    db.ex("UPDATE estudios SET lote_id=? WHERE id=?", (lid, e2))
r = c.post(f"/lotes/{lid}/avanzar", data={"_csrf": csrf, "etapa": "macroscopia"}, follow_redirects=True)
t = tareas(p2)
chequear("avanzar el lote cierra la tarea de cada protocolo", "registrada" in r.get_data(as_text=True) and t["T macro"]["estado"] == "cerrada" and "lote ENDO-1014.9" in t["T macro"]["cierre_detalle"], str(t["T macro"]))
chequear("las otras siguen abiertas", all(t[x]["estado"] == "abierta" for x in ("T proc", "T entrega", "T manual")))

print("3) al enviar el informe")
chequear("antes del envío está abierta", tareas(p3)["T entrega"]["estado"] == "abierta")
r = c.post(f"/protocolo/{p3}/enviar/correo", data={"_csrf": csrf, "modo": "mailto", "solo": "paciente", "paciente_email": "ana@correo.com"}, headers=H)
t = tareas(p3)
chequear("preparar el correo propio cierra «Cons > Entregar»", r.status_code == 200 and t["T entrega"]["estado"] == "cerrada" and t["T entrega"]["cierre_detalle"] == "informe preparado para enviar", r.get_data(as_text=True)[:150])
chequear("sin tocar las demás", t["T manual"]["estado"] == "abierta" and t["T macro"]["estado"] == "abierta")
crear(p3, "T entrega")
r = c.post(f"/protocolo/{p3}/enviar/whatsapp", data={"_csrf": csrf, "numero": "11 5015 1099", "rol": "paciente"}, headers=H)
with A.app.app_context():
    estados = [r["estado"] for r in db.q("SELECT estado FROM tareas WHERE protocolo_id=? AND titulo='T entrega' ORDER BY id", (p3,))]
chequear("WhatsApp también", r.status_code == 200 and estados == ["cerrada", "cerrada"], str(estados))
crear(p3, "T entrega")
r = c.post(f"/protocolo/{p3}/enviar/correo", data={"_csrf": csrf, "modo": "mailto", "solo": "otro"}, headers=H)
with A.app.app_context():
    estados = [r["estado"] for r in db.q("SELECT estado FROM tareas WHERE protocolo_id=? AND titulo='T entrega' ORDER BY id", (p3,))]
chequear("un envío que no se preparó no cierra nada", r.status_code == 400 and estados[-1] == "abierta", str(estados))

print()
print("FALLAS:", fallas if fallas else "ninguna")
