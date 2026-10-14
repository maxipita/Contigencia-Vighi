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
    gestor = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave, permisos_mas) VALUES ('ZZGES','Gestora','ingreso',0,1,0,'usuarios,exportar,macro')")
    comun = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZCOM','Común','ingreso',0,1,0)")
    perfil_alto = db.ex("INSERT INTO perfiles (nombre, permisos) VALUES ('Todo facturación','facturacion,exportar')")
    perfil_bajo = db.ex("INSERT INTO perfiles (nombre, permisos) VALUES ('Solo exportar','exportar')")

print("1) quién entra")
c, csrf = cliente(comun)
chequear("sin el permiso no entra", c.get("/usuarios").status_code == 403)
chequear("ni a editar ni a crear", c.get("/usuarios/nuevo").status_code == 403 and c.get(f"/usuarios/{comun}").status_code == 403)
chequear("sin el permiso el menú no muestra Usuarios", 'href="/usuarios"' not in c.get("/").get_data(as_text=True))
g, gcsrf = cliente(gestor)
h = g.get("/usuarios").get_data(as_text=True)
chequear("con el permiso entra al listado", g.get("/usuarios").status_code == 200 and "ZZGES" in h)
chequear("pero no ve el botón de Perfiles ni puede entrar", "Perfiles y permisos" not in h and g.get("/perfiles").status_code == 403 and g.get("/perfiles/nuevo").status_code == 403)
menu = g.get("/").get_data(as_text=True)
chequear("el menú le muestra Usuarios y no Perfiles", 'href="/usuarios"' in menu and 'href="/perfiles"' not in menu)
chequear("no hay enlace para editar a un administrador", f'href="/usuarios/{admin}"' not in h and f'href="/usuarios/{comun}"' in h)
r = g.get(f"/usuarios/{admin}", follow_redirects=True)
chequear("no puede abrir la edición de un administrador", "solo los puede editar otro administrador" in r.get_data(as_text=True))
r = g.post(f"/usuarios/{admin}", data={"_csrf": gcsrf, "iniciales": "ZZADM", "nombre": "Pisado", "activo": "1", "admin": "1"}, follow_redirects=True)
with A.app.app_context():
    chequear("ni guardar cambios sobre un administrador", db.uno("SELECT nombre FROM usuarios WHERE id=?", (admin,))["nombre"] == "Administrador")
chequear("la edición de un usuario común no muestra «Administrador» ni «Ver como»", "name=\"admin\"" not in g.get(f"/usuarios/{comun}").get_data(as_text=True) and "ver-como" not in g.get(f"/usuarios/{comun}").get_data(as_text=True))
chequear("el administrador sí los ve", "name=\"admin\"" in cliente(admin)[0].get(f"/usuarios/{comun}").get_data(as_text=True))
a, acsrf = cliente(admin)
chequear("el administrador ve todo", a.get("/perfiles").status_code == 200 and 'href="/perfiles"' in a.get("/").get_data(as_text=True))

print("2) lo que puede otorgar")
r = g.post("/usuarios/nuevo", data={"_csrf": gcsrf, "iniciales": "ZZNUE", "nombre": "Nueva", "activo": "1", "admin": "1", "perfil_id": str(perfil_bajo),
                                    "p_facturacion": "mas", "p_usuarios": "mas", "p_macro": "mas", "p_exportar": "menos"}, follow_redirects=True)
with A.app.app_context():
    n = db.uno("SELECT * FROM usuarios WHERE iniciales='ZZNUE'")
chequear("crea al usuario", n is not None and "Usuario ZZNUE guardado" in r.get_data(as_text=True))
chequear("no lo hace administrador", n["admin"] == 0)
chequear("solo le da permisos que ella tiene (macro sí; facturación y usuarios no)", n["permisos_mas"] == "macro" and n["permisos_menos"] == "exportar", f"{n['permisos_mas']} / {n['permisos_menos']}")
r = g.post("/usuarios/nuevo", data={"_csrf": gcsrf, "iniciales": "ZZALT", "activo": "1", "perfil_id": str(perfil_alto)}, follow_redirects=True)
with A.app.app_context():
    chequear("no puede asignar un perfil con permisos que no tiene", db.uno("SELECT 1 FROM usuarios WHERE iniciales='ZZALT'") is None and "permisos que vos no tenés" in r.get_data(as_text=True))
h = g.get("/usuarios/nuevo").get_data(as_text=True)
chequear("el desplegable no ofrece perfiles de más", "Solo exportar" in h and "Todo facturación" not in h)
chequear("los permisos que no puede dar salen bloqueados", 'name="p_facturacion" style="width:auto" disabled' in h and 'name="p_macro" style="width:auto" disabled' not in h)
r = g.post(f"/usuarios/{comun}", data={"_csrf": gcsrf, "iniciales": "ZZCOM", "nombre": "Común editado", "activo": "1", "clave": "claveTemporal1"}, follow_redirects=True)
with A.app.app_context():
    cm = db.uno("SELECT nombre, clave_hash, debe_cambiar_clave FROM usuarios WHERE id=?", (comun,))
chequear("sí edita a un usuario común y le pone una clave temporal", cm["nombre"] == "Común editado" and cm["clave_hash"] and cm["debe_cambiar_clave"] == 1)
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='facturacion' WHERE id=?", (n["id"],))
g.post(f"/usuarios/{n['id']}", data={"_csrf": gcsrf, "iniciales": "ZZNUE", "nombre": "Nueva 2", "activo": "1", "p_macro": "mas"}, follow_redirects=True)
with A.app.app_context():
    chequear("al editar conserva los permisos que ella no puede tocar", db.uno("SELECT permisos_mas FROM usuarios WHERE id=?", (n["id"],))["permisos_mas"] == "facturacion,macro" or db.uno("SELECT permisos_mas FROM usuarios WHERE id=?", (n["id"],))["permisos_mas"] == "macro,facturacion",
             db.uno("SELECT permisos_mas FROM usuarios WHERE id=?", (n["id"],))["permisos_mas"])
r = g.post(f"/usuarios/{gestor}", data={"_csrf": gcsrf, "iniciales": "ZZGES", "nombre": "Gestora"}, follow_redirects=True)
chequear("no puede desactivarse a sí misma", "No podés quitarte el rol de administrador ni desactivarte" in r.get_data(as_text=True))
r = g.post(f"/usuarios/{gestor}", data={"_csrf": gcsrf, "iniciales": "ZZGES", "nombre": "Gestora 2", "activo": "1", "p_usuarios": "menos", "p_exportar": "menos"}, follow_redirects=True)
with A.app.app_context():
    s = db.uno("SELECT permisos_mas, permisos_menos, nombre FROM usuarios WHERE id=?", (gestor,))
chequear("puede editarse sin perder ni darse el permiso de Usuarios", s["nombre"] == "Gestora 2" and "usuarios" in s["permisos_mas"] and "usuarios" not in (s["permisos_menos"] or ""), str(tuple(s)))
a.post(f"/usuarios/{comun}", data={"_csrf": acsrf, "iniciales": "ZZCOM", "activo": "1", "p_usuarios": "mas"})
with A.app.app_context():
    chequear("el administrador sí puede dar el permiso Usuarios", "usuarios" in db.uno("SELECT permisos_mas FROM usuarios WHERE id=?", (comun,))["permisos_mas"])
chequear("la imagen de la firma la puede ver quien administra usuarios", g.get(f"/usuarios/{ids['med']}/firma").status_code == 200)
chequear("y quien no tiene el permiso, no", cliente(ids["otro"])[0].get(f"/usuarios/{ids['med']}/firma").status_code == 403)

print()
print("FALLAS:", fallas if fallas else "ninguna")
