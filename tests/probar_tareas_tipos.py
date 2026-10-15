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


def tipo(titulo):
    with A.app.app_context():
        r = db.uno("SELECT * FROM tarea_tipos WHERE titulo=?", (titulo,))
        return dict(r) if r else None


c, csrf = cliente(admin)
with A.app.app_context():
    todos = [dict(r) for r in db.q("SELECT titulo, cierre, responsable_id FROM tarea_tipos ORDER BY titulo")]
chequear("arranca con los 15 títulos del sistema actual", len(todos) == 15 and {"Macro urgente", "Reclamo informe", "Solicitud taco"} <= {t["titulo"] for t in todos})
cierres = {t["titulo"]: t["cierre"] for t in todos}
chequear("con su cierre automático", cierres["Caso incompleto"] == "entrega" and cierres["Macro urgente"] == "procesamiento" and cierres["Procesamiento IHQ urgente"] == "interp_ihq"
         and cierres["Procesamiento urgente"] == "microscopia" and cierres["Reclamo informe"] == "entrega" and cierres["Presupuesto"] is None)
chequear("sin responsable hasta que se asigne", all(t["responsable_id"] is None for t in todos))

h = c.get("/tareas/tipos").get_data(as_text=True)
chequear("la pantalla lista título, responsable y cierre", "Responsables de tareas" in h and "Macro urgente" in h and "Histo &gt; Procesar" in h and "Cons &gt; Entregar" in h and "Micro &gt; Interpretar" in h)
chequear("cada fila tiene su Modificar", h.count("Modificar") >= 15)
chequear("Configuraciones la ofrece", 'href="/tareas/tipos"' in c.get("/configuraciones").get_data(as_text=True))

print("1) modificar")
tid = tipo("Macro urgente")["id"]
chequear("el formulario trae el título, los usuarios y los cierres", all(x in c.get(f"/tareas/tipos/{tid}").get_data(as_text=True) for x in ("value=\"Macro urgente\"", "ZZOT", "Histo &gt; Procesar", "Cons &gt; Entregar")))
r = c.post(f"/tareas/tipos/{tid}", data={"_csrf": csrf, "titulo": "Macro urgente", "responsable_id": str(ids["otro"]), "cierre": "microscopia"}, follow_redirects=True)
t = tipo("Macro urgente")
chequear("cambia el responsable y el cierre", t["responsable_id"] == ids["otro"] and t["cierre"] == "microscopia" and "guardada" in r.get_data(as_text=True))
chequear("se ve en el listado", "ZZOT" in c.get("/tareas/tipos").get_data(as_text=True))
c.post(f"/tareas/tipos/{tid}", data={"_csrf": csrf, "titulo": "Macro urgente", "responsable_id": "", "cierre": ""})
t = tipo("Macro urgente")
chequear("se puede dejar sin responsable y sin cierre automático", t["responsable_id"] is None and t["cierre"] is None)
with A.app.app_context():
    chequear("queda en el historial", db.uno("SELECT COUNT(*) AS n FROM auditoria WHERE accion='tarea_tipo'")["n"] == 2)
r = c.post(f"/tareas/tipos/{tid}", data={"_csrf": csrf, "titulo": "Solicitud taco"}, follow_redirects=True)
chequear("no permite repetir un título", "Ya existe una tarea llamada" in r.get_data(as_text=True) and tipo("Macro urgente"))
r = c.post(f"/tareas/tipos/{tid}", data={"_csrf": csrf, "titulo": "Macro urgente", "responsable_id": "99999"}, follow_redirects=True)
chequear("rechaza un responsable que no existe", "Elegí un responsable" in r.get_data(as_text=True) and tipo("Macro urgente")["responsable_id"] is None)
r = c.post(f"/tareas/tipos/{tid}", data={"_csrf": csrf, "titulo": "Macro urgente", "cierre": "inventada"}, follow_redirects=True)
chequear("rechaza un cierre que no existe", "Elegí un cierre" in r.get_data(as_text=True))
r = c.post(f"/tareas/tipos/{tid}", data={"_csrf": csrf, "titulo": "   "}, follow_redirects=True)
chequear("exige un título", "Falta el título" in r.get_data(as_text=True))
chequear("un título inexistente da 404", c.get("/tareas/tipos/99999").status_code == 404)

print("2) nuevo título")
r = c.post("/tareas/tipos/nuevo", data={"_csrf": csrf, "titulo": "  Pedido   de recorte ", "responsable_id": str(ids["med"]), "cierre": "entrega"}, follow_redirects=True)
n = tipo("Pedido de recorte")
chequear("agrega un título nuevo", n is not None and n["responsable_id"] == ids["med"] and n["cierre"] == "entrega")
r = c.post("/tareas/tipos/nuevo", data={"_csrf": csrf, "titulo": "pedido de RECORTE"}, follow_redirects=True)
chequear("sin distinguir mayúsculas", "Ya existe una tarea" in r.get_data(as_text=True))

print("3) quién entra")
sin, scsrf = cliente(ids["otro"])
chequear("solo el administrador", sin.get("/tareas/tipos").status_code == 403 and sin.get("/tareas/tipos/nuevo").status_code == 403)
sin.post(f"/tareas/tipos/{tid}", data={"_csrf": scsrf, "titulo": "Intruso"})
chequear("y no puede modificar", tipo("Macro urgente") is not None and tipo("Intruso") is None)
chequear("Configuraciones no la muestra", 'href="/tareas/tipos"' not in sin.get("/configuraciones").get_data(as_text=True))

print()
print("FALLAS:", fallas if fallas else "ninguna")
