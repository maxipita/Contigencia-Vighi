import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from flask import url_for
from vighi.dominio import informes
from vighi.dominio.estudios import REGISTRO
from vighi.servicios.facturas import facturacion_buscar

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


def crear_borrador(numero, tipo="PAP", dni=None):
    with A.app.app_context():
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, dni, borrador, creado_por, creado_en) VALUES (?,?,?,1,?,?)", (numero, "2026-10-16", dni, admin, db.ahora()))
        if tipo == "PAP":
            eid = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?)",
                        (pid, "PAP", "Citologías", "Ginecológica", "Vagina", ids["cito"], admin, db.ahora()))
        else:
            eid = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
                        (pid, "BP", "Biopsias", "Digestiva", "Estómago", "Biopsia", ids["med"], admin, db.ahora()))
    return pid, eid


def proto(pid):
    with A.app.app_context():
        return dict(db.uno("SELECT * FROM protocolos WHERE id=?", (pid,)))


def datos(pid, eid, tk, token, **extra):
    d = {"_csrf": tk, "edicion": token, "medico": "Dr. Prueba", "cobertura": "OSDE", "lugar_recoleccion": "", "lugar_entrega": "", "fecha_recoleccion": "2026-10-16",
         "e-0-id": str(eid), "e-0-tipo": "PAP", "e-0-categoria": "Citologías", "e-0-subcategoria": "Ginecológica", "e-0-sitio": "Vagina",
         "e-0-tipo_muestra": "Citología exocervical", "e-0-cantidad": "1", "e-0-responsable_id": str(ids["cito"])}
    d.update(extra)
    return {k: v for k, v in d.items() if v is not None}


def token_de(html):
    m = re.search(r'name="edicion" value="([0-9a-f]+)"', html)
    return m.group(1) if m else None


c, tk = cliente(admin)
pid, eid = crear_borrador("C000901")

print("1) Por completar: el PAP se activa con médico, cobertura y muestras")
h = c.get("/completar").get_data(as_text=True)
chequear("la lista ofrece «Activar» para el PAP", "Activar" in h and "C000901" in h)
h = c.get(f"/protocolo/{pid}/editar").get_data(as_text=True)
chequear("el formulario pide médico, cobertura y muestras, sin datos del paciente", all(x in h for x in ('name="medico"', 'name="cobertura"', "Activar protocolo")) and 'name="apellido"' not in h and 'name="dni"' not in h)
chequear("solo se pueden sumar más PAP", 'data-agregar-estudio="PAP"' in h and 'data-agregar-estudio="BP"' not in h)
token = token_de(h)
c.post(f"/protocolo/{pid}/editar", data=datos(pid, eid, tk, token, medico=""))
chequear("sin médico no se activa", proto(pid)["borrador"] == 1)
h = c.get(f"/protocolo/{pid}/editar").get_data(as_text=True)
c.post(f"/protocolo/{pid}/editar", data=datos(pid, eid, tk, token_de(h), **{"e-0-cantidad": ""}))
chequear("sin cantidad tampoco", proto(pid)["borrador"] == 1)
h = c.get(f"/protocolo/{pid}/editar").get_data(as_text=True)
r = c.post(f"/protocolo/{pid}/editar", data=datos(pid, eid, tk, token_de(h)), follow_redirects=True)
p = proto(pid)
chequear("con los tres datos queda activo", p["borrador"] == 0 and p["pendiente_validacion"] == 1, p)
chequear("el paciente queda como «IA EnProceso»", (p["apellido"], p["nombre"]) == ("IA", "EnProceso") and not p["dni"])
chequear("lo avisa", "activado" in r.get_data(as_text=True))
with A.app.app_context():
    chequear("queda en el historial", db.uno("SELECT 1 FROM auditoria WHERE protocolo_id=? AND accion='activar_pap'", (pid,)) is not None)

print("2) el laboratorio sigue su curso")
h = c.get("/?ver=todos").get_data(as_text=True)
chequear("aparece en el tablero, con la marca «A validar»", "C000901" in h and "A validar" in h and "IA, EnProceso" in h)
with A.app.test_request_context():
    ruta = url_for("estudios.marcar_listo", eid=eid, etapa="coloreado")
r = c.post(ruta, data={"_csrf": tk})
with A.app.app_context():
    chequear("se puede marcar la primera etapa", db.uno("SELECT 1 FROM etapas WHERE etapa='coloreado' AND flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (eid,)) is not None, r.status_code)
    for clave, _, _ in REGISTRO["PAP"].flujo(0):
        db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) SELECT flujo_id, ?, ?, ? FROM estudios WHERE id=? AND NOT EXISTS (SELECT 1 FROM etapas x WHERE x.flujo_id=estudios.flujo_id AND x.etapa=?)",
              (clave, admin, "2026-10-16 12:00:00", eid, clave))
    chequear("las etiquetas de laboratorio ven el protocolo", db.uno("SELECT 1 FROM protocolos p JOIN estudios e ON e.protocolo_id=p.id WHERE p.id=? AND p.borrador=0 AND e.cantidad<>''", (pid,)) is not None)

print("3) lo que queda frenado mientras faltan los datos")
with A.app.app_context():
    try:
        informes.armar(pid)
        mensaje = ""
    except informes.InformeError as e:
        mensaje = str(e)
chequear("el informe no se puede generar", "validar los datos del paciente" in mensaje, mensaje)
h = c.get(f"/protocolo/{pid}").get_data(as_text=True)
chequear("la ficha avisa que faltan validar los datos y ofrece validarlos", "pendientes de validación" in h and f"/protocolo/{pid}/validar" in h)
with A.app.app_context():
    f = collections.defaultdict(str, desde="", hasta="", q="C000901")
    filas = [r for r in facturacion_buscar(f) if r["numero"] == "C000901"]
chequear("no se puede facturar", filas and not filas[0]["tarifa"] and "sin validar" in filas[0]["motivo"], filas)

print("4) pantalla de validación")
h = c.get("/completar").get_data(as_text=True)
chequear("«Por completar» tiene la pestaña «Por validar»", "Por validar (" in h)
h = c.get("/validacion").get_data(as_text=True)
chequear("la lista muestra el caso", "C000901" in h and "Por validar" in h and "Validar" in h)
with A.app.app_context():
    sin_permiso = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZSP','Sin Permiso','',0,1,0)")
cs, tks = cliente(sin_permiso)
chequear("quien no tiene el permiso no entra", cs.get("/validacion").status_code == 302 and cs.get(f"/protocolo/{pid}/validar").status_code == 302)
h = c.get(f"/protocolo/{pid}/validar").get_data(as_text=True)
chequear("el formulario viene con apellido y nombre vacíos y la orden al lado", 'name="apellido" value=""' in h and 'name="nombre" value=""' in h and "Órdenes escaneadas" in h)
r = c.post(f"/protocolo/{pid}/validar", data={"_csrf": tk, "apellido": "IA", "nombre": "EnProceso", "dni": ""}, follow_redirects=True)
chequear("no acepta el nombre provisorio", proto(pid)["pendiente_validacion"] == 1 and "provisorio" in r.get_data(as_text=True))
r = c.post(f"/protocolo/{pid}/validar", data={"_csrf": tk, "apellido": "", "nombre": "", "dni": ""}, follow_redirects=True)
chequear("ni vacío", proto(pid)["pendiente_validacion"] == 1)

otro_pid, _ = crear_borrador("C000902")
with A.app.app_context():
    db.ex("UPDATE protocolos SET borrador=0, pendiente_validacion=1, apellido='IA', nombre='EnProceso' WHERE id=?", (otro_pid,))
    previo = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, dni, sexo, creado_por, creado_en) VALUES ('C000800','2026-09-01','Viejo','Nombre','30999888','F',?,?)", (admin, db.ahora()))
r = c.post(f"/protocolo/{pid}/validar", data={"_csrf": tk, "apellido": "Gómez", "nombre": "Laura", "dni": "30999888", "sexo": "F", "cobertura": "OSDE", "n_afiliado": "123", "siguiente": "1"})
p = proto(pid)
chequear("con los datos del paciente queda validado", p["pendiente_validacion"] == 0 and (p["apellido"], p["nombre"], p["dni"], p["n_afiliado"]) == ("Gómez", "Laura", "30999888", "123"), p)
chequear("guarda quién y cuándo", p["validado_por"] == admin and p["validado_en"])
chequear("«validar y pasar al siguiente» lleva al próximo pendiente", r.status_code == 302 and f"/protocolo/{otro_pid}/validar" in r.headers["Location"], r.headers.get("Location"))
chequear("un DNI ya cargado comparte los datos del paciente con sus otros protocolos", (proto(previo)["apellido"], proto(previo)["nombre"]) == ("Gómez", "Laura"), proto(previo))
with A.app.app_context():
    chequear("queda en el historial", db.uno("SELECT 1 FROM auditoria WHERE protocolo_id=? AND accion='validar'", (pid,)) is not None)
    try:
        informes.armar(pid)
        mensaje = ""
    except informes.InformeError as e:
        mensaje = str(e)
chequear("validado, el informe ya no queda frenado por esto", "validar los datos" not in mensaje, mensaje)
h = c.get(f"/protocolo/{pid}").get_data(as_text=True)
chequear("y la ficha deja de avisar", "pendientes de validación" not in h)
r = c.get(f"/protocolo/{pid}/validar", follow_redirects=True)
chequear("un protocolo ya validado no vuelve a la pantalla", "no está pendiente" in r.get_data(as_text=True))

print("5) sin DNI no se junta con nadie")
r = c.post(f"/protocolo/{otro_pid}/validar", data={"_csrf": tk, "apellido": "Sin", "nombre": "Documento", "dni": ""})
chequear("se valida sin DNI y no toca a otros pacientes", proto(otro_pid)["pendiente_validacion"] == 0 and proto(previo)["apellido"] == "Gómez" and proto(pid)["apellido"] == "Gómez")
chequear("la lista queda vacía", "No hay protocolos pendientes" in c.get("/validacion").get_data(as_text=True))

print("6) lo demás sigue igual")
bp, _ = crear_borrador("C000903", tipo="BP")
h = c.get(f"/protocolo/{bp}/editar").get_data(as_text=True)
chequear("un protocolo de biopsia se completa con el formulario de siempre", 'name="apellido"' in h and "Activar protocolo" not in h)
print("FALLAS:", fallas or "ninguna")
