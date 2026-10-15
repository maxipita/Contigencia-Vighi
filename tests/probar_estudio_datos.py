import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.servicios.lotes import tipos_lote

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
    db.ex("INSERT INTO catalogo (tipo, categoria, subcategoria, sitio, tipo_muestra) VALUES "
          "('BP','Biopsias','Ginecológica','Endometrio','Biopsia'), ('BP','Biopsias','Ginecológica','Endometrio','Reseccion'), "
          "('BP','Biopsias','Ginecológica','Cuello Uterino','Biopsia'), ('BP','Biopsias','Ginecológica','Cuello Uterino','Reseccion'), "
          "('BP','Biopsias','Ginecológica','Sitio de prueba','Reseccion maligna'), ('BP','Biopsias','Digestivo','Estómago','Biopsia')")
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000301','2026-10-14','Test','Datos',?,?)", (admin, db.ahora()))
    insertar = ("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)")
    e1 = db.ex(insertar, (pid, "BP", "Biopsias", "Ginecológica", "Endometrio", "Biopsia", "1", ids["med"], admin, db.ahora()))
    e2 = db.ex(insertar, (pid, "BP", "Biopsias", "Ginecológica", "Cuello Uterino", "Biopsia", "2", ids["med"], admin, db.ahora()))
    tipo_lote = tipos_lote("BP")[0]

c, csrf = cliente(admin)


def estudio(eid):
    with A.app.app_context():
        return dict(db.uno("SELECT * FROM estudios WHERE id=?", (eid,)))


def auditorias(accion):
    with A.app.app_context():
        return [r["detalle"] for r in db.q("SELECT detalle FROM auditoria WHERE accion=?", (accion,))]


def enviar(ruta, **datos):
    return c.post(ruta, data=dict(datos, _csrf=csrf), follow_redirects=True).get_data(as_text=True)


h = c.get(f"/protocolo/{pid}").get_data(as_text=True)
chequear("cada dato tiene su lápiz", all(f"/estudio/{e1}/{x}" in h for x in ("sitio", "muestra", "cantidad", "responsable", "lote")))
chequear("el lote solo se cambia desde el primer estudio", f"/estudio/{e2}/lote" not in h and f"/estudio/{e2}/sitio" in h)
chequear("el órgano ofrece los de la misma subcategoría", "Cuello Uterino</option>" in h and "Sitio de prueba</option>" in h and "Estómago</option>" not in h)

print("1) órgano")
t = enviar(f"/estudio/{e1}/sitio", sitio="Cuello Uterino")
chequear("cambia el órgano y conserva la muestra si existe", estudio(e1)["sitio"] == "Cuello Uterino" and estudio(e1)["tipo_muestra"] == "Biopsia" and "Órgano cambiado" in t)
chequear("queda en el historial", any("Endometrio → Cuello Uterino" in d for d in auditorias("cambiar_sitio")), str(auditorias("cambiar_sitio")))
t = enviar(f"/estudio/{e1}/sitio", sitio="Sitio de prueba")
chequear("si la muestra no existe en el nuevo órgano la reemplaza y lo avisa", estudio(e1)["tipo_muestra"] == "Reseccion maligna" and "La muestra pasó a «Reseccion maligna»" in t)
t = enviar(f"/estudio/{e1}/sitio", sitio="Estómago")
chequear("rechaza un órgano de otra subcategoría", estudio(e1)["sitio"] == "Sitio de prueba" and "Elegí un órgano de la lista" in t)
enviar(f"/estudio/{e1}/sitio", sitio="Endometrio")
enviar(f"/estudio/{e1}/muestra", tipo_muestra="Biopsia")

print("2) cantidad")
t = enviar(f"/estudio/{e1}/cantidad", cantidad="4")
chequear("cambia la cantidad", estudio(e1)["cantidad"] == "4" and "Cantidad cambiada a 4 frascos" in t)
chequear("queda en el historial", any("1 → 4 frascos" in d for d in auditorias("cambiar_cantidad")), str(auditorias("cambiar_cantidad")))
t = enviar(f"/estudio/{e1}/cantidad", cantidad="99")
chequear("rechaza una cantidad inválida", estudio(e1)["cantidad"] == "4" and "Elegí una cantidad" in t)

print("3) responsable")
t = enviar(f"/estudio/{e1}/responsable", responsable_id=str(ids["otro"]))
chequear("cambia el responsable", estudio(e1)["responsable_id"] == ids["otro"] and "Responsable cambiado a ZZOT" in t)
chequear("queda en el historial", any("DM → ZZOT" in d for d in auditorias("cambiar_responsable")), str(auditorias("cambiar_responsable")))
t = enviar(f"/estudio/{e1}/responsable", responsable_id=str(ids["cito"]))
chequear("rechaza a alguien que no es responsable de ese tipo de estudio", estudio(e1)["responsable_id"] == ids["otro"] and "Elegí un responsable" in t)

print("4) lote")
t = enviar(f"/estudio/{e1}/lote", lote_id=f"nuevo:{tipo_lote}")
with A.app.app_context():
    lote = db.uno("SELECT codigo FROM lotes WHERE id=?", (estudio(e1)["lote_id"],))
chequear("crea un lote nuevo y se lo asigna a todo el protocolo", lote is not None and estudio(e2)["lote_id"] == estudio(e1)["lote_id"] and "Lote del protocolo actualizado" in t, str(lote))
chequear("queda en el historial", any(lote["codigo"] in d for d in auditorias("lote")) if lote else False)
t = enviar(f"/estudio/{e2}/lote", lote_id="")
chequear("desde un estudio que no es el primero no se cambia", "se cambia desde su primer estudio" in t and estudio(e2)["lote_id"] == estudio(e1)["lote_id"])
t = enviar(f"/estudio/{e1}/lote", lote_id="99999")
chequear("rechaza un lote que no existe", "no existe" in t and estudio(e1)["lote_id"] is not None)
t = enviar(f"/estudio/{e1}/lote", lote_id="")
chequear("permite dejar el protocolo sin lote", estudio(e1)["lote_id"] is None and estudio(e2)["lote_id"] is None)

print("5) desde la pantalla del estudio")
h = c.get(f"/estudio/{e1}").get_data(as_text=True)
chequear("la tarjeta del estudio ofrece cambiar cada dato", all(f"/estudio/{e1}/{x}" in h for x in ("sitio", "muestra", "cantidad", "responsable", "lote")) and 'name="volver" value="estudio"' in h)
chequear("el segundo estudio no ofrece el lote", f"/estudio/{e2}/lote" not in c.get(f"/estudio/{e2}").get_data(as_text=True) and f"/estudio/{e2}/cantidad" in c.get(f"/estudio/{e2}").get_data(as_text=True))
r = c.post(f"/estudio/{e1}/cantidad", data={"_csrf": csrf, "cantidad": "6", "volver": "estudio"}, follow_redirects=True)
chequear("vuelve a la pantalla del estudio y guarda", r.request.path == f"/estudio/{e1}" and estudio(e1)["cantidad"] == "6" and "Cantidad cambiada a 6" in r.get_data(as_text=True))
r = c.post(f"/estudio/{e1}/lote", data={"_csrf": csrf, "lote_id": f"nuevo:{tipo_lote}", "volver": "estudio"}, follow_redirects=True)
chequear("el lote también vuelve al estudio", r.request.path == f"/estudio/{e1}" and estudio(e1)["lote_id"] is not None)
r = c.post(f"/estudio/{e1}/cantidad", data={"_csrf": csrf, "cantidad": "5"}, follow_redirects=True)
chequear("sin el aviso vuelve al protocolo", r.request.path == f"/protocolo/{pid}")

print("6) permisos")
sin, scsrf = cliente(ids["otro"])
antes = estudio(e1)
for ruta, datos in (("sitio", {"sitio": "Sitio de prueba"}), ("cantidad", {"cantidad": "7"}), ("responsable", {"responsable_id": str(ids["med"])}), ("lote", {"lote_id": f"nuevo:{tipo_lote}"}), ("muestra", {"tipo_muestra": "Reseccion"})):
    sin.post(f"/estudio/{e1}/{ruta}", data=dict(datos, _csrf=scsrf))
chequear("sin el permiso de edición no cambia nada", estudio(e1) == antes)
chequear("y no ve los lápices", f"/estudio/{e1}/sitio" not in sin.get(f"/protocolo/{pid}").get_data(as_text=True))
c.post(f"/estudio/{e2}/anular", data={"_csrf": csrf, "motivo": "prueba"})
t = enviar(f"/estudio/{e2}/cantidad", cantidad="9")
chequear("un estudio anulado no se modifica", estudio(e2)["cantidad"] == "2" and "está anulado" in t)

print()
print("FALLAS:", fallas if fallas else "ninguna")
