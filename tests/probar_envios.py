import email
import os
import smtplib
import sys
import tempfile
from email import policy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
db.ARCHIVO_CLOUDFLARE = os.path.join(tempfile.mkdtemp(), "cloudflare.env")
from vighi.servicios import mensajeria

fallas = []
enviados = []


def chequear(nombre, ok, detalle=""):
    print(("  OK   " if ok else "  FALLA"), nombre, "" if ok else detalle)
    if not ok:
        fallas.append(nombre)


class SMTPFalso:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, **k):
        pass

    def login(self, *a):
        pass

    def send_message(self, m):
        enviados.append(m)


smtplib.SMTP = SMTPFalso


def configurar(**valores):
    mensajeria.config()
    mensajeria._config.update(valores)
    mensajeria._marca[0] = mensajeria._fecha_archivo()


def sin_correo():
    mensajeria._config.clear()
    mensajeria._marca[0] = mensajeria._fecha_archivo()
    for k in mensajeria.CLAVES:
        os.environ.pop(k, None)
    mensajeria._config.update({k: "" for k in mensajeria.CLAVES})


c = A.app.test_client()
with c.session_transaction() as s:
    s["uid"] = admin
c.get("/")
with c.session_transaction() as s:
    csrf = s["csrf"]
H = {"X-CSRF": csrf}
P = ids["p_bp"]
sin_correo()

print("1) funciones de apoyo")
chequear("whatsapp con código de área", mensajeria.whatsapp_numero("11 5015-1099") == "5491150151099" and mensajeria.whatsapp_numero("+54911 50151099") == "5491150151099")
chequear("whatsapp con 15", mensajeria.whatsapp_numero("011 15 5015-1099") == "5491150151099" and mensajeria.whatsapp_numero("123") is None)
chequear("e-mail válido", mensajeria.email_valido("a.b@c.com.ar") and not mensajeria.email_valido("a@b") and not mensajeria.email_valido("a b@c.com"))
chequear("alcance y evaluación", mensajeria.alcance_valido(["BP.MALIGNO", "XX.Y", "PAP.NMA"]) == "BP.MALIGNO,PAP.NMA"
         and mensajeria.evaluar("", [("BP", None)]) == "si" and mensajeria.evaluar("BP.MALIGNO", [("BP", None)]) == "falta"
         and mensajeria.evaluar("BP.MALIGNO", [("BP", "NMA")]) == "no" and mensajeria.evaluar("BP.MALIGNO", [("BP", "MALIGNO")]) == "si"
         and mensajeria.evaluar("BP.MALIGNO", [("CT", None)]) == "no")

print("2) ubicaciones")
r = c.post("/ubicaciones/nueva", data={"_csrf": csrf, "abreviatura": "OTAM", "nombre": "Sanatorio Otamendi", "direccion": "Azcuénaga 870", "contactos": "Tel 4000"}, follow_redirects=True)
chequear("crea la ubicación", r.status_code == 200 and "Ubicación creada" in r.get_data(as_text=True))
with A.app.app_context():
    uid = db.uno("SELECT id FROM ubicaciones WHERE abreviatura='OTAM'")["id"]
r = c.post("/ubicaciones/nueva", data={"_csrf": csrf, "abreviatura": "OTAM"}, follow_redirects=True)
chequear("rechaza repetida", "Ya existe una ubicación" in r.get_data(as_text=True))
for datos, ok in ((dict(canal="email", destino="Seguimiento@Otam.com.ar", informes="1"), True), (dict(canal="email", destino="malo"), False),
                  (dict(canal="whatsapp", destino="11 5015 1099", informes="1"), True), (dict(canal="whatsapp", destino="12"), False),
                  (dict(canal="email", destino="maligno@otam.com.ar", informes="1", alcance=["BP.MALIGNO", "BP.SOSPECHOSO"]), True),
                  (dict(canal="email", destino="nma@otam.com.ar", informes="1", alcance=["BP.NMA"]), True), (dict(canal="email", destino="seguimiento@otam.com.ar"), False)):
    c.post(f"/ubicaciones/{uid}/destino", data=dict(datos, _csrf=csrf))
with A.app.app_context():
    filas = {(f["canal"], f["destino"]): f for f in db.q("SELECT * FROM ubicacion_destinos WHERE ubicacion_id=?", (uid,))}
chequear("carga destinos válidos y rechaza los inválidos o repetidos", set(filas) == {("email", "seguimiento@otam.com.ar"), ("whatsapp", "5491150151099"), ("email", "maligno@otam.com.ar"), ("email", "nma@otam.com.ar")}, str(set(filas)))
chequear("guarda el alcance", filas[("email", "maligno@otam.com.ar")]["alcance"] == "BP.SOSPECHOSO,BP.MALIGNO")
did = filas[("email", "seguimiento@otam.com.ar")]["id"]
c.post(f"/ubicaciones/{uid}/destino/{did}", data={"_csrf": csrf, "informes": "1", "alcance": ["PAP.NMA"]})
with A.app.app_context():
    chequear("edita el alcance de un destino", db.uno("SELECT alcance FROM ubicacion_destinos WHERE id=?", (did,))["alcance"] == "PAP.NMA")
c.post(f"/ubicaciones/{uid}/destino/{did}", data={"_csrf": csrf, "informes": "1", "alcance": []})
h = c.get(f"/ubicaciones/{uid}").get_data(as_text=True)
chequear("la ficha muestra la matriz de envío", "Envío de informes" in h and "seguimiento@otam.com.ar" in h and "alcance" in h)
chequear("la lista busca por abreviatura", "OTAM" in c.get("/ubicaciones?q=otamendi").get_data(as_text=True))
chequear("/api/ubicaciones devuelve abreviatura y nombre", {"v": "OTAM", "n": "Sanatorio Otamendi"} in c.get("/api/ubicaciones").get_json())
r = c.post(f"/protocolo/{P}/datos", data={"_csrf": csrf, "lugar_recoleccion": "NO EXISTE"}, follow_redirects=True)
chequear("el protocolo exige una ubicación existente", "elegí una ubicación de la lista" in r.get_data(as_text=True))
r = c.post(f"/protocolo/{P}/datos", data={"_csrf": csrf, "lugar_entrega": "OTAM"}, follow_redirects=True)
chequear("y acepta una existente", "Datos del protocolo actualizados" in r.get_data(as_text=True))
r = c.post(f"/ubicaciones/{uid}/eliminar", data={"_csrf": csrf}, follow_redirects=True)
chequear("no elimina una ubicación con protocolos", "No se puede eliminar" in r.get_data(as_text=True))
csv = "abreviatura,nombre,direccion,medicos,telefonos,emails_informes\nNUEVA1,Clínica Nueva,Calle 1,\"Gomez, Ricardo\",4444-5555,uno@nueva.com;otro@nueva.com\n".encode("utf-8")
import io
r = c.post("/ubicaciones/importar", data={"_csrf": csrf, "archivo": (io.BytesIO(csv), "u.csv")}, follow_redirects=True, content_type="multipart/form-data")
with A.app.app_context():
    nueva = db.uno("SELECT id FROM ubicaciones WHERE abreviatura='NUEVA1'")
    destinos = [f["destino"] for f in db.q("SELECT destino FROM ubicacion_destinos WHERE ubicacion_id=?", (nueva["id"],))] if nueva else []
chequear("importa el CSV con sus e-mails de informes", nueva is not None and sorted(destinos) == ["otro@nueva.com", "uno@nueva.com"], str(destinos))

print("3) pantalla de envío")
r = c.get(f"/protocolo/{P}/enviar")
chequear("sin informe avisa", r.status_code == 200 and "Todavía no hay informe" in r.get_data(as_text=True))
r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "paciente", "paciente_email": "a@b.com"}, headers=H)
chequear("sin informe no prepara nada", r.status_code == 400 and "Primero hay que generar" in r.get_json()["error"])
with A.app.app_context():
    db.ex("INSERT INTO informes_emitidos (protocolo_id, version, usuario_id, firmante_id, creado_en, archivo, pdf) VALUES (?,?,?,?,?,?,?)",
          (P, 1, admin, ids["med"], "2026-10-12 10:00:00", "Informe_C000101.pdf", b"%PDF-1.4 prueba"))
    db.ex("UPDATE protocolos SET email='ana@correo.com' WHERE id=?", (P,))
h = c.get(f"/protocolo/{P}/enviar").get_data(as_text=True)
chequear("con informe vigente y sin correo ofrece el correo propio", "Informe listo para enviar" in h and 'data-correo="mailto"' in h and "Con PDF adjunto" in h and "no tiene cuenta de correo" in h)
chequear("hay una tarjeta por destinatario con su botón", all(f'name="solo" value="{x}"' in h for x in ("paciente", "medico", "ubicacion", "otro")) and 'value="ana@correo.com"' in h)
chequear("vienen tildados los destinos de la entrega que corresponden", 'value="seguimiento@otam.com.ar" data-cuenta checked' in h)
chequear("los de otra malignidad se avisan", "Falta cargar la malignidad" in h and "BP.MALIGNO" not in h)

r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "paciente", "paciente_email": "ana@correo.com", "asunto": "Hola mundo", "cuerpo": "Texto"}, headers=H)
enlace = r.get_json()["enlace"]
chequear("el botón del paciente arma un mailto", enlace.startswith("mailto:?to=ana@correo.com&subject=Hola%20mundo&body=") and "Texto" in enlace, enlace[:120])
r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "ubicacion", "ubic_email": ["seguimiento@otam.com.ar", "maligno@otam.com.ar"], "paciente_email": "malo"}, headers=H)
chequear("varios destinatarios van en copia oculta y se ignoran las otras tarjetas", r.status_code == 200 and "bcc=seguimiento@otam.com.ar,maligno@otam.com.ar" in r.get_json()["enlace"], str(r.get_json()))
r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "ubicacion"}, headers=H)
chequear("ubicación sin tildar avisa", r.status_code == 400 and "Tildá al menos un e-mail" in r.get_json()["error"])
r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "medico"}, headers=H)
chequear("médico sin e-mail avisa", r.status_code == 400 and "e-mail válido para el médico" in r.get_json()["error"])
r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "otro"}, headers=H)
chequear("otro vacío avisa", r.status_code == 400 and "Escribí el e-mail" in r.get_json()["error"])
r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "cualquiera"}, headers=H)
chequear("un destinatario desconocido se rechaza", r.status_code == 400)

r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "medico", "medico_email": "Dr@Kido.com", "guardar_medico": "1"}, headers=H)
with A.app.app_context():
    medico = db.uno("SELECT email FROM medicos WHERE nombre='Dr. Gustavo Kido'")
    chequear("el médico que no está en la lista no se puede guardar", medico is None)
    db.ex("INSERT INTO medicos (nombre) VALUES ('Dr. Gustavo Kido')")
r = c.post(f"/protocolo/{P}/enviar/correo", data={"modo": "mailto", "solo": "medico", "medico_email": "Dr@Kido.com", "guardar_medico": "1"}, headers=H)
with A.app.app_context():
    chequear("guarda el e-mail del médico en su ficha", db.uno("SELECT email FROM medicos WHERE nombre='Dr. Gustavo Kido'")["email"] == "dr@kido.com")
    chequear("audita el cambio del médico", db.uno("SELECT COUNT(*) AS n FROM auditoria WHERE accion='editar_medico'")["n"] == 1)
h = c.get(f"/protocolo/{P}/enviar").get_data(as_text=True)
chequear("el e-mail del médico queda cargado", 'value="dr@kido.com"' in h)

r = c.post(f"/protocolo/{P}/enviar/correo?modo=eml", data={"_csrf": csrf, "solo": "medico", "medico_email": "dr@kido.com", "asunto": "Informe Adjunto : X", "cuerpo": "Intro"})
m = email.message_from_bytes(r.data, policy=policy.default)
adjuntos = list(m.iter_attachments())
chequear("el borrador .eml lleva el PDF adjunto y es un mensaje sin enviar", r.status_code == 200 and r.mimetype == "message/rfc822" and m["X-Unsent"] == "1" and m["To"] == "dr@kido.com"
         and len(adjuntos) == 1 and adjuntos[0].get_content() == b"%PDF-1.4 prueba" and "Intro" in m.get_body(("html",)).get_content())
chequear("sin SMTP_DESDE el borrador no fuerza remitente", m["From"] is None)
configurar(SMTP_DESDE="anatomia.patologica@susanavighi.com.ar", SMTP_NOMBRE="CAP Susana Vighi")
r = c.post(f"/protocolo/{P}/enviar/correo?modo=eml", data={"_csrf": csrf, "solo": "paciente", "paciente_email": "ana@correo.com"})
m = email.message_from_bytes(r.data, policy=policy.default)
chequear("con SMTP_DESDE el borrador sale desde la casilla del laboratorio", "anatomia.patologica@susanavighi.com.ar" in str(m["From"]))
with A.app.app_context():
    filas = db.q("SELECT canal, estado FROM envios")
    chequear("todo lo preparado a mano queda como correo propio abierto", filas and {f["canal"] for f in filas} == {"correo"} and {f["estado"] for f in filas} == {"abierto"})
r = c.post(f"/protocolo/{P}/enviar", data={"_csrf": csrf, "solo": "paciente", "paciente_email": "ana@correo.com"}, follow_redirects=True)
chequear("sin SMTP_HOST el envío desde el sistema se rechaza", "no está configurado" in r.get_data(as_text=True) and not enviados)

print("4) envío desde el sistema")
sin_correo()
configurar(SMTP_HOST="smtp.prueba", SMTP_DESDE="no-reply@susanavighi.com.ar", SMTP_USUARIO="u", SMTP_CLAVE="c", SMTP_NOMBRE="CAP Susana Vighi")
h = c.get(f"/protocolo/{P}/enviar").get_data(as_text=True)
chequear("con correo configurado desaparecen los botones del correo propio", "data-correo" not in h and "Con PDF adjunto" not in h and 'name="solo" value="otro"' in h)
r = c.post(f"/protocolo/{P}/enviar", data={"_csrf": csrf, "solo": "paciente", "paciente_email": "Nueva@Correo.com", "guardar_paciente": "1", "medico_email": "x@x.com", "ubic_email": "seguimiento@otam.com.ar"},
           follow_redirects=True)
chequear("el botón del paciente manda solo al paciente", len(enviados) == 1 and enviados[0]["To"] == "nueva@correo.com" and "Informe enviado a 1 destinatario" in r.get_data(as_text=True).replace("✔ ", ""), str([x["To"] for x in enviados]))
m = enviados[0]
adj = list(m.iter_attachments())
chequear("el mensaje lleva el PDF, el remitente configurado y la parte HTML", len(adj) == 1 and adj[0].get_filename() == "Informe_C000101.pdf" and "no-reply@susanavighi.com.ar" in m["From"] and m.get_body(("html",)) is not None)
with A.app.app_context():
    chequear("guarda el e-mail del paciente en su ficha", db.uno("SELECT email FROM protocolos WHERE id=?", (P,))["email"] == "nueva@correo.com")
r = c.post(f"/protocolo/{P}/enviar", data={"_csrf": csrf, "solo": "ubicacion", "ubic_email": ["seguimiento@otam.com.ar", "maligno@otam.com.ar"]}, follow_redirects=True)
chequear("la tarjeta de la ubicación manda un mensaje por destinatario", len(enviados) == 3 and sorted(x["To"] for x in enviados[1:]) == ["maligno@otam.com.ar", "seguimiento@otam.com.ar"])
with A.app.app_context():
    chequear("el registro guarda cada envío con su rol", sorted(tuple(f) for f in db.q("SELECT rol, estado FROM envios WHERE canal='email'")) == [("paciente", "enviado"), ("ubicacion", "enviado"), ("ubicacion", "enviado")])
h = c.get(f"/protocolo/{P}/enviar").get_data(as_text=True)
chequear("marca lo ya enviado de esta emisión", h.count("✔ Enviado el") >= 3)


class SMTPRechaza(SMTPFalso):
    def login(self, *a):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.139 Authentication unsuccessful, SmtpClientAuthentication is disabled for the Tenant")


smtplib.SMTP = SMTPRechaza
r = c.post(f"/protocolo/{P}/enviar", data={"_csrf": csrf, "solo": "otro", "otro_email": "alguien@x.com"}, follow_redirects=True)
t = r.get_data(as_text=True)
chequear("un rechazo del servidor se muestra con su respuesta y queda como error", "No se pudo enviar a alguien@x.com" in t and "SmtpClientAuthentication is disabled" in t)
with A.app.app_context():
    chequear("el error queda en el registro", db.uno("SELECT COUNT(*) AS n FROM envios WHERE estado='error'")["n"] == 1)
smtplib.SMTP = SMTPFalso

r = c.post(f"/protocolo/{P}/enviar/whatsapp", data={"numero": "11 5015 1099", "rol": "paciente", "texto": "Hola"}, headers=H)
chequear("WhatsApp devuelve el enlace y registra el intento", r.status_code == 200 and r.get_json()["enlace"] == "https://wa.me/5491150151099?text=Hola")
r = c.post(f"/protocolo/{P}/enviar/whatsapp", data={"numero": "12"}, headers=H)
chequear("WhatsApp rechaza un número inválido", r.status_code == 400)

print("5) malignidad")
c.post(f"/ubicaciones/{uid}/destino", data={"_csrf": csrf, "canal": "email", "destino": "nuevo-maligno@otam.com.ar", "informes": "1", "alcance": ["BP.MALIGNO"]})
h = c.get(f"/protocolo/{P}").get_data(as_text=True)
chequear("el panel de malignidad aparece con el estudio informado", 'id="malignidad"' in h and "Maligno" in h and "Sospechoso" in h)
r = c.post(f"/protocolo/{P}/malignidad", data={"_csrf": csrf, "tipo": "BP", "valor": "MALIGNO"}, follow_redirects=True)
with A.app.app_context():
    chequear("asigna la malignidad a los estudios del flujo", {f["malignidad"] for f in db.q("SELECT malignidad FROM estudios WHERE protocolo_id=? AND tipo='BP'", (P,))} == {"MALIGNO"})
r = c.post(f"/protocolo/{P}/malignidad", data={"_csrf": csrf, "tipo": "BP", "valor": "inventado"}, follow_redirects=True)
chequear("rechaza un valor inválido", "malignidad válida" in r.get_data(as_text=True))
h = c.get(f"/protocolo/{P}/enviar").get_data(as_text=True)
chequear("con malignidad MALIGNO se tilda el que lo incluye y no el NMA", 'value="nuevo-maligno@otam.com.ar" data-cuenta checked' in h and 'value="nma@otam.com.ar" data-cuenta checked' not in h
         and "No corresponde: recibe solo Biopsia: no maligno" in h)
c.post(f"/protocolo/{P}/malignidad", data={"_csrf": csrf, "tipo": "BP", "valor": "NMA"})
h = c.get(f"/protocolo/{P}/enviar").get_data(as_text=True)
chequear("al cambiarla cambian los destinos", 'value="nma@otam.com.ar" data-cuenta checked' in h and 'value="nuevo-maligno@otam.com.ar" data-cuenta checked' not in h)
c.post(f"/protocolo/{P}/malignidad", data={"_csrf": csrf, "tipo": "BP", "valor": ""})
with A.app.app_context():
    chequear("se puede quitar", {f["malignidad"] for f in db.q("SELECT malignidad FROM estudios WHERE protocolo_id=? AND tipo='BP'", (ids["p_pendiente"] and P,))} == {None})
r = c.post(f"/protocolo/{ids['p_pendiente']}/malignidad", data={"_csrf": csrf, "tipo": "BP", "valor": "MALIGNO"}, follow_redirects=True)
chequear("no se asigna con el estudio sin informar", "cuando los estudios están informados" in r.get_data(as_text=True))

print("6) página de correo")
h = c.get("/correo").get_data(as_text=True)
chequear("la pantalla Correo muestra el estado sin la clave", "Configurado" in h and "smtp.prueba" in h and ">c<" not in h)
r = c.post("/correo", data={"_csrf": csrf, "destino": "prueba@x.com"})
chequear("manda un mensaje de prueba", "Mensaje enviado a prueba@x.com" in r.get_data(as_text=True) and enviados[-1]["To"] == "prueba@x.com")
cs = A.app.test_client()
with cs.session_transaction() as s:
    s["uid"] = ids["med"]
chequear("solo la administración entra a Correo", cs.get("/correo").status_code == 403)

print()
print("FALLAS:", fallas if fallas else "ninguna")
