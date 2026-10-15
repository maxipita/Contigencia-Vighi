import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
import segno
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from vighi.servicios import ordenes as srv

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


def hoja(numero=None, qr=True, texto=True, sombra=0):
    img = Image.new("RGB", (1654, 2339), "white")
    d = ImageDraw.Draw(img)
    d.text((120, 150), "ORDEN DE ESTUDIO ANATOMIA PATOLOGICA", fill="black", font=ImageFont.load_default(size=40))
    for i in range(10):
        d.text((120, 400 + i * 70), f"Paciente de prueba {sombra}   DNI 30.111.222   Diagnostico presuntivo", fill=(60, 60, 60), font=ImageFont.load_default(size=30))
    if numero:
        etiqueta = Image.new("RGB", (560, 110), "white")
        e = ImageDraw.Draw(etiqueta)
        e.rectangle([0, 0, 559, 109], outline="black", width=2)
        if texto:
            e.text((12, 8), "#" + numero, fill="black", font=ImageFont.load_default(size=46))
            e.text((12, 62), "ENDO-1014.1  14/10/2026", fill="black", font=ImageFont.load_default(size=26))
        img.paste(etiqueta, (900, 1700))
        if qr:
            b = io.BytesIO()
            segno.make(numero, error="m").save(b, kind="png", scale=6, border=1)
            img.paste(Image.open(b).convert("RGB").resize((146, 146)), (1480, 1690))
    return img.filter(ImageFilter.GaussianBlur(0.6)).rotate(1.2, expand=True, fillcolor="white")


def png(img):
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def pdf(*imagenes):
    b = io.BytesIO()
    imagenes[0].save(b, "PDF", save_all=True, append_images=list(imagenes[1:]), resolution=200)
    return b.getvalue()


with A.app.app_context():
    p1 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000123','2026-10-14','Uno','Ana',?,?)", (admin, db.ahora()))
    p2 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000124','2026-10-14','Dos','Beto',?,?)", (admin, db.ahora()))

c, csrf = cliente(admin)
H = {"X-CSRF": csrf, "Accept": "application/json"}
lect = srv.lectores()


def subir(nombre, datos):
    r = c.post("/api/ordenes/subir", data={"archivo": (io.BytesIO(datos), nombre)}, headers=H, content_type="multipart/form-data")
    return r.status_code, r.get_json()


def filas():
    with A.app.app_context():
        return [dict(r) for r in db.q("SELECT id, protocolo_id, nombre, pagina, metodo, leido, motivo FROM ordenes ORDER BY id")]


print("0) lectores disponibles")
chequear("están instaladas la lectura de QR y de PDF", lect["qr"] and lect["pdf"], str(lect))

print("1) lectura del número")
chequear("el texto del QR se normaliza a un número de protocolo", srv.numeros_del_texto("C000123") == ["C000123"] and srv.numeros_del_texto("#C000123") == ["C000123"])
chequear("tolera las confusiones habituales del OCR (O por 0, l por 1, S por 5)", srv.numeros_del_texto("#COOO12S") == ["C000125"] and srv.numeros_del_texto("Cl00O23") == ["C100023"])
chequear("ignora el QR institucional y otros textos", srv.numeros_del_texto("https://qr.codes/cU6CvE") == [] and srv.numeros_del_texto("Cobertura 1234") == [])
chequear("acepta el número escrito a mano en varios formatos", srv.numero_escrito("124") == "C000124" and srv.numero_escrito(" #c000124 ") == "C000124" and srv.numero_escrito("hola") is None)

print("2) subir un escaneo con QR")
estado, j = subir("orden1.png", png(hoja("C000123")))
chequear("se adjunta al protocolo por el QR", estado == 200 and j["ok"] and j["paginas"][0]["estado"] == "adjunta" and j["paginas"][0]["metodo"] == "qr" and j["paginas"][0]["numero"] == "C000123", str(j))
f = filas()
chequear("queda guardada y ligada al protocolo", len(f) == 1 and f[0]["protocolo_id"] == p1 and f[0]["metodo"] == "qr")
estado, j = subir("orden1-copia.png", png(hoja("C000123")))
chequear("el mismo escaneo subido otra vez no se duplica", j["paginas"][0]["estado"] == "repetida" and len(filas()) == 1, str(j))

print("3) sin QR: lectura del número impreso")
if lect["ocr"]:
    estado, j = subir("orden2.png", png(hoja("C000124", qr=False, sombra=2)))
    chequear("lo identifica leyendo el texto de la etiqueta", j["paginas"][0]["estado"] == "adjunta" and j["paginas"][0]["metodo"] == "ocr" and j["paginas"][0]["numero"] == "C000124", str(j))
else:
    print("  (OCR no instalado: se omite)")

print("4) lo que no se puede identificar")
estado, j = subir("sin-etiqueta.png", png(hoja(None, sombra=3)))
chequear("una hoja sin número queda pendiente", j["paginas"][0]["estado"] == "pendiente" and "No se encontró" in j["paginas"][0]["motivo"], str(j))
estado, j = subir("inexistente.png", png(hoja("C000999", sombra=4)))
chequear("un número que no existe queda pendiente y lo dice", j["paginas"][0]["estado"] == "pendiente" and "C000999" in j["paginas"][0]["motivo"] and "no existe" in j["paginas"][0]["motivo"], str(j))
estado, j = subir("basura.txt", b"esto no es una imagen")
chequear("un archivo que no sirve da error claro", estado == 400 and not j["ok"] and "ni una imagen" in j["error"], str(j))
estado, j = subir("roto.pdf", b"%PDF-1.4 roto")
chequear("un PDF roto da error claro", estado == 400 and not j["ok"], str(j))

print("5) PDF de varias hojas")
antes = len(filas())
estado, j = subir("lote.pdf", pdf(hoja("C000124", sombra=5), hoja(None, sombra=6), hoja("C000123", sombra=7)))
r = j["paginas"] if j and j.get("ok") else []
chequear("separa las hojas y las identifica", [x["estado"] for x in r] == ["adjunta", "adjunta", "adjunta"] and [x["numero"] for x in r] == ["C000124", "C000124", "C000123"], str(j))
chequear("la hoja sin número se toma como continuación de la anterior", r and r[1]["metodo"] == "continuacion")
chequear("se guardaron las tres páginas", len(filas()) - antes == 3)

print("6) asignar a mano")
pend = [x for x in filas() if x["protocolo_id"] is None]
chequear("las dos pendientes aparecen en la pantalla", all(x in c.get("/ordenes").get_data(as_text=True) for x in ("Sin identificar", "sin-etiqueta.png", "inexistente.png")) and len(pend) == 2, str(pend))
r = c.post(f"/orden/{pend[0]['id']}/asignar", data={"_csrf": csrf, "numero": "999999"}, follow_redirects=True)
chequear("rechaza un protocolo que no existe", "no existe" in r.get_data(as_text=True) and filas()[[x["id"] for x in filas()].index(pend[0]["id"])]["protocolo_id"] is None)
r = c.post(f"/orden/{pend[0]['id']}/asignar", data={"_csrf": csrf, "numero": "xx"}, follow_redirects=True)
chequear("rechaza un número mal escrito", "Escribí el número" in r.get_data(as_text=True))
r = c.post(f"/orden/{pend[0]['id']}/asignar", data={"_csrf": csrf, "numero": "124"}, follow_redirects=True)
asignada = [x for x in filas() if x["id"] == pend[0]["id"]][0]
chequear("la asigna con solo los dígitos", asignada["protocolo_id"] == p2 and asignada["metodo"] == "manual" and asignada["motivo"] is None and "asignada" in r.get_data(as_text=True))
chequear("queda en el historial del protocolo", "asignada a mano" in c.get(f"/protocolo/{p2}").get_data(as_text=True))

print("7) en la ficha del protocolo")
h = c.get(f"/protocolo/{p1}").get_data(as_text=True)
chequear("la tarjeta muestra las órdenes del protocolo", 'id="ordenes"' in h and "Órdenes escaneadas" in h and "orden1.png" in h and "por QR" in h)
oid = [x for x in filas() if x["protocolo_id"] == p1][0]["id"]
r = c.get(f"/orden/{oid}")
chequear("se puede ver la imagen y su miniatura", r.status_code == 200 and r.mimetype == "image/jpeg" and r.data[:2] == b"\xff\xd8" and c.get(f"/orden/{oid}/mini").status_code == 200)
r = c.post(f"/protocolo/{p1}/ordenes", data={"_csrf": csrf, "archivos": (io.BytesIO(png(hoja("C000124", sombra=8))), "manual.png")}, content_type="multipart/form-data", follow_redirects=True)
manual = [x for x in filas() if x["nombre"] == "manual.png"]
chequear("adjuntar a mano a un protocolo no lee el número: va a ese protocolo", manual and manual[0]["protocolo_id"] == p1 and manual[0]["metodo"] == "manual", str(manual))
r = c.post(f"/orden/{oid}/borrar", data={"_csrf": csrf}, follow_redirects=True)
chequear("se puede borrar y queda en el historial", oid not in [x["id"] for x in filas()] and "orden_borrada" in c.get(f"/protocolo/{p1}").get_data(as_text=True))

print("8) permisos")
otro, ocsrf = cliente(ids["otro"])
chequear("cualquiera con sesión ve la pantalla", otro.get("/ordenes").status_code == 200)
antes = len(filas())
r = otro.post("/api/ordenes/subir", data={"archivo": (io.BytesIO(png(hoja("C000123", sombra=9))), "x.png")}, headers={"X-CSRF": ocsrf}, content_type="multipart/form-data")
chequear("sin permiso de edición no sube", r.status_code in (302, 403) and len(filas()) == antes)
r = otro.post(f"/orden/{pend[1]['id']}/borrar", data={"_csrf": ocsrf})
chequear("ni borra", r.status_code in (302, 403) and pend[1]["id"] in [x["id"] for x in filas()])
chequear("el menú Más la ofrece", 'href="/ordenes"' in c.get("/").get_data(as_text=True))

print("9) QR propio en la etiqueta de Recepción")
r = c.get("/api/etiquetas/qr?inicio=5&n=3")
j = r.get_json()
chequear("devuelve un QR por protocolo", r.status_code == 200 and sorted(j) == ["C000005", "C000006", "C000007"] and len(set(j.values())) == 3 and all(v.startswith("data:image/svg+xml") for v in j.values()))
chequear("valida el rango", c.get("/api/etiquetas/qr?inicio=0&n=3").status_code == 400 and c.get("/api/etiquetas/qr?inicio=5&n=5000").status_code == 400 and c.get("/api/etiquetas/qr?inicio=999999&n=2").status_code == 400)
chequear("la pantalla de etiquetas lo usa", "bpQrProtocolo" in c.get("/etiquetas").get_data(as_text=True))
b = io.BytesIO()
segno.make("C000007", error="m").save(b, kind="png", scale=3, border=1)
chica = Image.open(b).convert("RGB")
fondo = Image.new("RGB", (1654, 2339), "white")
fondo.paste(chica.resize((146, 146)), (1480, 1690))
chequear("y el sistema lo lee como un número de protocolo", srv.leer_qr(fondo) == ["C000007"])

print()
print("FALLAS:", fallas if fallas else "ninguna")
