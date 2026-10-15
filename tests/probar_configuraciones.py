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
    return c


c = cliente(admin)
r = c.get("/configuraciones")
h = r.get_data(as_text=True)
chequear("el administrador ve todas las funciones del menú Más", r.status_code == 200 and all(x in h for x in (
    "Usuarios", "Perfiles y permisos", "Responsables de tareas", "Ubicaciones", "Feriados", "Listados", "Templates", "Coberturas", "Correo", "Exportar a Excel")))
chequear("con sus enlaces", all(f'href="{u}"' in h for u in ("/usuarios", "/perfiles", "/tareas/tipos", "/ubicaciones", "/feriados", "/listados", "/templates", "/coberturas", "/correo", "/exportar")), h[:0])
chequear("se llega desde el menú Más y desde el del usuario", h.count('href="/configuraciones"') >= 2)

o = cliente(ids["cito"])
r = o.get("/configuraciones")
h = r.get_data(as_text=True)
chequear("un usuario común solo ve lo que le corresponde", r.status_code == 200 and "Ubicaciones" in h and "Perfiles y permisos" not in h and "Correo" not in h
         and "Responsables de tareas" not in h and "Templates" not in h and "Coberturas" not in h and 'href="/usuarios"' not in h)
chequear("sin sesión no entra", A.app.test_client().get("/configuraciones").status_code in (302, 401, 403))

print()
print("FALLAS:", fallas if fallas else "ninguna")
