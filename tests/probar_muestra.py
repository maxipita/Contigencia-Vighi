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


with A.app.app_context():
    db.ex("INSERT INTO catalogo (tipo, categoria, subcategoria, sitio, tipo_muestra) VALUES ('BP','Biopsias','Ginecológica','Endometrio','Biopsia'), ('BP','Biopsias','Ginecológica','Endometrio','Reseccion'), "
          "('BP','Biopsias','Otra','Endometrio','No va')")
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000201','2026-10-14','Test','Muestra',?,?)", (admin, db.ahora()))
    eid = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, "BP", "Biopsias", "Ginecológica", "Endometrio", "Biopsia", "1", ids["med"], admin, db.ahora()))

c, csrf = cliente(admin)
h = c.get(f"/protocolo/{pid}").get_data(as_text=True)
chequear("la tabla de estudios ofrece cambiar la muestra", f'/estudio/{eid}/muestra' in h and 'name="tipo_muestra"' in h and "<option selected>Biopsia</option>" in h and "Reseccion</option>" in h)
chequear("solo ofrece las muestras de esa subcategoría y sitio", "No va" not in h)
r = c.post(f"/estudio/{eid}/muestra", data={"_csrf": csrf, "tipo_muestra": "Reseccion"}, follow_redirects=True)
with A.app.app_context():
    e = db.uno("SELECT tipo_muestra FROM estudios WHERE id=?", (eid,))
    a = db.uno("SELECT detalle FROM auditoria WHERE accion='cambiar_muestra'")
chequear("cambia el tipo de muestra", e["tipo_muestra"] == "Reseccion" and "Tipo de muestra cambiado" in r.get_data(as_text=True))
chequear("queda en el historial con el antes y el después", a and "Biopsia → Reseccion" in a["detalle"], str(a and a["detalle"]))
r = c.post(f"/estudio/{eid}/muestra", data={"_csrf": csrf, "tipo_muestra": "Inventada"}, follow_redirects=True)
with A.app.app_context():
    chequear("rechaza un valor que no está en el catálogo", db.uno("SELECT tipo_muestra FROM estudios WHERE id=?", (eid,))["tipo_muestra"] == "Reseccion" and "Elegí un tipo de muestra" in r.get_data(as_text=True))
c.post(f"/estudio/{eid}/muestra", data={"_csrf": csrf, "tipo_muestra": "Reseccion"})
with A.app.app_context():
    chequear("repetir el mismo valor no ensucia el historial", db.uno("SELECT COUNT(*) AS n FROM auditoria WHERE accion='cambiar_muestra'")["n"] == 1)
sin, scsrf = cliente(ids["otro"])
r = sin.post(f"/estudio/{eid}/muestra", data={"_csrf": scsrf, "tipo_muestra": "Biopsia"}, follow_redirects=True)
with A.app.app_context():
    chequear("sin el permiso de edición no cambia nada", db.uno("SELECT tipo_muestra FROM estudios WHERE id=?", (eid,))["tipo_muestra"] == "Reseccion")
chequear("y no ve el lápiz", f'/estudio/{eid}/muestra' not in sin.get(f"/protocolo/{pid}").get_data(as_text=True))
c.post(f"/estudio/{eid}/anular", data={"_csrf": csrf, "motivo": "prueba"})
r = c.post(f"/estudio/{eid}/muestra", data={"_csrf": csrf, "tipo_muestra": "Biopsia"}, follow_redirects=True)
with A.app.app_context():
    chequear("un estudio anulado no se modifica", db.uno("SELECT tipo_muestra FROM estudios WHERE id=?", (eid,))["tipo_muestra"] == "Reseccion")

print()
print("FALLAS:", fallas if fallas else "ninguna")
