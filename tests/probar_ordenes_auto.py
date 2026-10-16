import io
import os
import re
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
import segno
from PIL import Image, ImageDraw, ImageFont
from werkzeug.serving import make_server
from vighi.herramientas import vigilar_ordenes as vig

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


def hoja(numero=None, n=0):
    img = Image.new("RGB", (1654, 2339), "white")
    d = ImageDraw.Draw(img)
    d.text((120, 150), "ORDEN DE ESTUDIO", fill="black", font=ImageFont.load_default(size=40))
    d.text((120, 400 + n * 3), "hoja " + str(n), fill="black", font=ImageFont.load_default(size=30))
    if numero:
        b = io.BytesIO()
        segno.make(numero, error="m").save(b, kind="png", scale=6, border=1)
        img.paste(Image.open(b).convert("RGB").resize((146, 146)), (1480, 1690))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


with A.app.app_context():
    p1 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000123','2026-10-14','Uno','Ana',?,?)", (admin, db.ahora()))
    p2 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000124','2026-10-14','Dos','Beto',?,?)", (admin, db.ahora()))

c, csrf = cliente(admin)

print("1) claves de integración")
chequear("la pantalla es solo para administradores", cliente(ids["otro"])[0].get("/claves").status_code in (302, 403))
r = c.post("/claves", data={"_csrf": csrf, "nombre": "PC del escáner"})
h = r.get_data(as_text=True)
m = re.search(r'value="(vgh_[^"]+)"', h)
token = m.group(1) if m else ""
chequear("crea una clave y la muestra una sola vez", bool(token) and "no se vuelve a mostrar" in h)
chequear("la clave no queda guardada en claro", token not in c.get("/claves").get_data(as_text=True) and "PC del escáner" in c.get("/claves").get_data(as_text=True))
with A.app.app_context():
    fila = db.uno("SELECT huella FROM claves_api WHERE nombre='PC del escáner'")
chequear("solo se guarda su huella", fila and fila["huella"] != token and len(fila["huella"]) == 64)
r = c.post("/claves", data={"_csrf": csrf, "nombre": "  "}, follow_redirects=True)
chequear("exige un nombre", "Escribí un nombre" in r.get_data(as_text=True))
chequear("aparece en Configuraciones", "Claves de integración" in c.get("/configuraciones").get_data(as_text=True))

print("2) el endpoint automático")
anonimo = A.app.test_client()


def subir(cliente_http, datos, clave=None, nombre="a.png"):
    cab = {"Authorization": "Bearer " + clave} if clave else {}
    return cliente_http.post("/api/ordenes/automatico", data={"archivo": (io.BytesIO(datos), nombre)}, headers=cab, content_type="multipart/form-data")


chequear("sin clave responde 401", subir(anonimo, hoja("C000123")).status_code == 401)
chequear("con una clave equivocada responde 401", subir(anonimo, hoja("C000123"), "vgh_equivocada").status_code == 401)
chequear("no hace falta el token de formulario ni la sesión", subir(anonimo, hoja("C000123"), token).status_code == 200)
with A.app.app_context():
    o = db.uno("SELECT protocolo_id, usuario_id, metodo FROM ordenes")
    uso = db.uno("SELECT ultimo_uso FROM claves_api WHERE nombre='PC del escáner'")["ultimo_uso"]
chequear("adjunta la orden al protocolo, sin usuario, y anota el uso de la clave", o["protocolo_id"] == p1 and o["usuario_id"] is None and o["metodo"] == "qr" and uso)
chequear("se ve como automático en la ficha", "Automático" in c.get(f"/protocolo/{p1}").get_data(as_text=True))
r = subir(anonimo, b"no es una imagen", token, "x.png")
chequear("un archivo ilegible responde 400", r.status_code == 400 and not r.get_json()["ok"])
r = anonimo.post("/api/ordenes/automatico?nombre=C%3A%5Cescaneos%5Cdesde-onedrive.png", data=hoja("C000123"), headers={"Authorization": "Bearer " + token, "Content-Type": "application/octet-stream"})
chequear("acepta el archivo como cuerpo del pedido (como lo manda OneDrive) y usa el nombre sin la ruta", r.status_code == 200 and r.get_json()["archivo"] == "desde-onedrive.png" and len(r.get_json()["paginas"]) == 1, r.get_data(as_text=True)[:150])
r = anonimo.post("/api/ordenes/automatico", data=hoja("C000123"), headers={"Authorization": "Bearer " + token, "Content-Type": "application/octet-stream"})
chequear("sin nombre de archivo avisa cómo mandarlo", r.status_code == 400 and "nombre=" in r.get_json()["error"])
r = anonimo.post("/api/ordenes/automatico?nombre=vacio.png", data=b"", headers={"Authorization": "Bearer " + token, "Content-Type": "application/octet-stream"})
chequear("un cuerpo vacío se rechaza", r.status_code == 400)
chequear("un formulario común sin token de seguridad sigue rechazado", anonimo.post("/api/ordenes/subir", data={"archivo": (io.BytesIO(hoja()), "a.png")}, content_type="multipart/form-data").status_code == 400)

print("2b) hojas sueltas del mismo lote (Capture Pro entrega una imagen por archivo)")


def lote(ruta, nombre, datos):
    r = anonimo.post("/api/ordenes/automatico?nombre=" + nombre + "&ruta=" + ruta + "/" + nombre, data=datos,
                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/octet-stream"})
    return r.status_code, r.get_json()


def destino(grupo):
    with A.app.app_context():
        return {r["nombre"]: (r["protocolo_id"], r["metodo"]) for r in db.q("SELECT nombre, protocolo_id, metodo FROM ordenes WHERE grupo=?", (grupo,))}


G = "/Escaneos/Batch1"
estado, j = lote(G, "00000001.png", hoja("C000123", 11))
chequear("la primera hoja con QR abre el grupo", j["paginas"][0]["estado"] == "adjunta" and j["paginas"][0]["numero"] == "C000123", str(j))
estado, j = lote(G, "00000002.png", hoja(None, 12))
chequear("la hoja siguiente sin número se suma al mismo protocolo, sea cual sea la cantidad", j["paginas"][0]["estado"] == "adjunta" and j["paginas"][0]["metodo"] == "continuacion" and j["paginas"][0]["numero"] == "C000123", str(j))
lote(G, "00000003.png", hoja(None, 13))
lote(G, "00000004.png", hoja(None, 14))
estado, j = lote(G, "00000005.png", hoja("C000124", 15))
chequear("un QR con otro número cierra el grupo anterior y abre uno nuevo", j["paginas"][0]["numero"] == "C000124")
lote(G, "00000006.png", hoja(None, 16))
d = destino(G.strip("/"))
chequear("quedan agrupadas: 1 a 4 en el primer protocolo, 5 y 6 en el segundo",
         [d[n][0] for n in ("00000001.png", "00000002.png", "00000003.png", "00000004.png")] == [p1] * 4 and [d[n][0] for n in ("00000005.png", "00000006.png")] == [p2] * 2, str(d))

G2 = "/Escaneos/Batch2"
lote(G2, "00000003.png", hoja(None, 23))
lote(G2, "00000005.png", hoja(None, 25))
d = destino(G2.strip("/"))
chequear("las hojas que llegan antes que su QR esperan sin identificar", all(v[0] is None for v in d.values()), str(d))
lote(G2, "00000004.png", hoja("C000124", 24))
d = destino(G2.strip("/"))
chequear("al llegar el QR se suman las que siguen en el orden del lote, no las que lo preceden", d["00000003.png"][0] is None and d["00000004.png"][0] == p2 and d["00000005.png"][0] == p2, str(d))
lote(G2, "00000001.png", hoja("C000123", 21))
lote(G2, "00000002.png", hoja(None, 22))
d = destino(G2.strip("/"))
chequear("llegando desordenadas el resultado es el mismo que si llegaran en orden", [d[n][0] for n in ("00000001.png", "00000002.png", "00000003.png", "00000004.png", "00000005.png")] == [p1, p1, p1, p2, p2], str(d))
chequear("las que siguen a otro protocolo quedan como continuación", d["00000003.png"][1] == "continuacion" and d["00000004.png"][1] == "qr")

G3 = "/Escaneos/Batch3"
lote(G3, "00000001.png", hoja("C000123", 31))
lote(G3, "00000002.png", hoja("C000999", 32))
estado, j = lote(G3, "00000003.png", hoja(None, 33))
chequear("tras un número que no existe, las hojas siguientes no se pegan al protocolo anterior", j["paginas"][0]["estado"] == "pendiente" and destino(G3.strip("/"))["00000003.png"][0] is None, str(j))

estado, j = lote("/Escaneos", "suelta.png", hoja(None, 41))
chequear("un archivo directo en la carpeta vigilada (sin subcarpeta de lote) no se agrupa con otros", j["paginas"][0]["estado"] == "pendiente", str(j))

r = anonimo.post("/api/ordenes/automatico?nombre=INDEX.DAT&ruta=/Escaneos/Batch1/INDEX.DAT", data=b"INDEX interno de Capture Pro",
                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/octet-stream"})
chequear("los archivos que no son imagen ni PDF (INDEX.DAT) se ignoran sin error", r.status_code == 200 and r.get_json().get("ignorado") is True)
with A.app.app_context():
    fila = db.uno("SELECT COUNT(*) AS n FROM auditoria WHERE accion='orden' AND detalle LIKE '%continuación%'")
chequear("las hojas agregadas por continuación quedan en el historial del protocolo", fila["n"] >= 3)

print("3) el programa que mira la carpeta")
servidor = make_server("127.0.0.1", 0, A.app, threaded=True)
puerto = servidor.server_port
hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
hilo.start()
url = f"http://127.0.0.1:{puerto}"
carpeta = tempfile.mkdtemp()
try:
    def poner(nombre, datos):
        with open(os.path.join(carpeta, nombre), "wb") as f:
            f.write(datos)

    poner("bien.png", hoja("C000123"))
    poner("sin-numero.png", hoja())
    poner("roto.pdf", b"%PDF-1.4 roto")
    poner("notas.txt", b"no es un escaneo")
    vistos = {}
    hechos = vig.procesar_carpeta(carpeta, url, token, vistos, None, espera=60)
    chequear("no toca archivos que recién aparecieron (todavía pueden estar copiándose)", hechos == 0 and os.path.exists(os.path.join(carpeta, "bien.png")))
    hechos = vig.procesar_carpeta(carpeta, url, "vgh_equivocada", {}, None, espera=0)
    chequear("con una clave inválida no mueve nada", hechos == 0 and os.path.exists(os.path.join(carpeta, "bien.png")))
    with A.app.app_context():
        antes = db.uno("SELECT COUNT(*) AS n FROM ordenes")["n"]
    hechos = vig.procesar_carpeta(carpeta, url, token, {}, None, espera=0)
    with A.app.app_context():
        despues = db.uno("SELECT COUNT(*) AS n FROM ordenes")["n"]
    chequear("sube los escaneos y los mueve a Procesadas", hechos == 2 and sorted(os.listdir(os.path.join(carpeta, "Procesadas"))) == ["bien.png", "sin-numero.png"], str(os.listdir(carpeta)))
    chequear("el que el sistema no puede leer pasa a «Con error»", os.listdir(os.path.join(carpeta, "Con error")) == ["roto.pdf"])
    chequear("lo que no es un escaneo no se toca", os.path.exists(os.path.join(carpeta, "notas.txt")))
    chequear("la hoja sin número queda en «Sin identificar» del sistema", despues - antes == 1 and "sin-numero.png" in c.get("/ordenes").get_data(as_text=True))
    poner("bien.png", hoja("C000123"))
    hechos = vig.procesar_carpeta(carpeta, url, token, {}, None, espera=0)
    chequear("un archivo repetido no se duplica pero igual se archiva", hechos == 1 and not os.path.exists(os.path.join(carpeta, "bien.png")) and len(os.listdir(os.path.join(carpeta, "Procesadas"))) == 3)
    sub = os.path.join(carpeta, "Batch9", "00000001")
    os.makedirs(sub)
    for nombre_hoja, datos_hoja in (("00000001.png", hoja("C000124", 51)), ("00000002.png", hoja(None, 52)), ("info", b"[Default] document.doc_id = 1")):
        with open(os.path.join(sub, nombre_hoja), "wb") as f:
            f.write(datos_hoja)
    enviados = {}
    hechos = vig.procesar_carpeta(carpeta, url, token, {}, None, espera=0, enviados=enviados)
    d = destino(os.path.basename(carpeta) + "/Batch9/00000001")
    chequear("recorre las subcarpetas del lote y sube sus hojas", hechos == 2 and sorted(enviados) == ["Batch9/00000001/00000001.png", "Batch9/00000001/00000002.png"], str((hechos, enviados)))
    chequear("manda la ruta: las hojas de la subcarpeta quedan agrupadas bajo el protocolo de la primera", d.get("00000001.png") == (p2, "qr") and d.get("00000002.png") == (p2, "continuacion"), str(d))
    chequear("las de las subcarpetas se quedan donde están y lo que no es un escaneo no se toca", os.path.exists(os.path.join(sub, "00000001.png")) and os.path.exists(os.path.join(sub, "info")))
    chequear("no vuelve a subir lo ya enviado ni entra en Procesadas", vig.procesar_carpeta(carpeta, url, token, {}, None, espera=0, enviados=enviados) == 0)
    estado_json = os.path.join(carpeta, "estado.json")
    vig.guardar_estado(estado_json, enviados)
    chequear("el registro de enviados se guarda y se vuelve a leer", vig.cargar_estado(estado_json) == enviados and vig.cargar_estado(os.path.join(carpeta, "no-existe.json")) == {})
    chequear("--desde ignora lo modificado antes de esa fecha", vig.candidatos(carpeta, {}, 0, {}, desde=time.time() + 3600) == [] and len(vig.candidatos(carpeta, {}, 0, {})) >= 2)
    poner("otra.png", hoja("C000123"))
    with A.app.app_context():
        kid = db.uno("SELECT id FROM claves_api WHERE nombre='PC del escáner'")["id"]
    c.post(f"/claves/{kid}/revocar", data={"_csrf": csrf})
    hechos = vig.procesar_carpeta(carpeta, url, token, {}, None, espera=0)
    chequear("con la clave revocada deja el archivo donde está", hechos == 0 and os.path.exists(os.path.join(carpeta, "otra.png")))
finally:
    servidor.shutdown()
    shutil.rmtree(carpeta, ignore_errors=True)

carpeta = tempfile.mkdtemp()
try:
    with open(os.path.join(carpeta, "pendiente.png"), "wb") as f:
        f.write(hoja("C000123"))
    hechos = vig.procesar_carpeta(carpeta, "http://127.0.0.1:9", token, {}, None, espera=0)
    chequear("sin conexión con el sistema deja el archivo para reintentar", hechos == 0 and os.path.exists(os.path.join(carpeta, "pendiente.png")))
finally:
    shutil.rmtree(carpeta, ignore_errors=True)

print("4) revocar")
with A.app.app_context():
    activa = db.uno("SELECT activa FROM claves_api WHERE nombre='PC del escáner'")["activa"]
with A.app.app_context():
    historial = [r["detalle"] for r in db.q("SELECT detalle FROM auditoria WHERE accion='clave_api' ORDER BY id")]
chequear("revocar la clave la desactiva y queda en el historial", activa == 0 and len(historial) == 2 and "revocó" in historial[1], str(historial))
chequear("la clave revocada ya no sirve", subir(anonimo, hoja("C000123"), token).status_code == 401)

print()
print("FALLAS:", fallas if fallas else "ninguna")
