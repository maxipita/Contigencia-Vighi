import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
import segno
from PIL import Image, ImageDraw, ImageFont
from vighi.servicios import onedrive

fallas = []


def chequear(nombre, ok, detalle=""):
    print(("  OK   " if ok else "  FALLA"), nombre, "" if ok else detalle)
    if not ok:
        fallas.append(nombre)


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


CARPETAS = [("E", "Escaneos", "R"), ("EO", "Escaneo ordenes", "E"), ("B1", "Batch1", "EO"), ("D1", "00000001", "B1"), ("P", "Personal", "R")]
CONTENIDO = {"f1": hoja("C000123", 1), "f2": hoja(None, 2), "f3": b"[Default]", "f4": hoja("C000123", 4), "f6": hoja(None, 6), "f7": hoja("C000124", 7)}
S = {"pedidos": [], "blob_con_clave": 0, "tokens": 0, "falla_f7": True, "delta_viejo": 0}


def item_carpeta(i, nombre, padre):
    return {"id": i, "name": nombre, "folder": {"childCount": 1}, "parentReference": {"id": padre}}


def item_archivo(i, nombre, padre, tamano=100, mod="2026-10-16T20:00:00Z"):
    return {"id": i, "name": nombre, "size": tamano, "file": {"mimeType": "image/png"}, "parentReference": {"id": padre}, "lastModifiedDateTime": mod}


class Falso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def responder(self, codigo, datos=None, cabeceras=None, crudo=None):
        cuerpo = crudo if crudo is not None else json.dumps(datos or {}).encode("utf-8")
        self.send_response(codigo)
        for k, v in (cabeceras or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self):
        longitud = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(longitud).decode("utf-8"))
        S["tokens"] += 1
        if form.get("client_secret") != ["secreto-bueno"] or form.get("grant_type") != ["client_credentials"]:
            return self.responder(401, {"error": "invalid_client", "error_description": "secreto equivocado"})
        self.responder(200, {"access_token": "tok", "expires_in": 3600})

    def do_GET(self):
        url = urlparse(self.path)
        consulta = parse_qs(url.query)
        S["pedidos"].append(self.path)
        if url.path.startswith("/blob/"):
            if self.headers.get("Authorization"):
                S["blob_con_clave"] += 1
            return self.responder(200, crudo=CONTENIDO[url.path.rsplit("/", 1)[1]], cabeceras={"Content-Type": "application/octet-stream"})
        if self.headers.get("Authorization") != "Bearer tok":
            return self.responder(401, {"error": {"code": "InvalidAuthenticationToken"}})
        if url.path.endswith("/drive/root/delta"):
            token = (consulta.get("token") or [""])[0]
            if token == "VIEJO":
                S["delta_viejo"] += 1
                return self.responder(410, {"error": {"code": "resyncRequired"}})
            base = f"http://127.0.0.1:{self.server.server_port}/v1.0/users/escaner@vighi.com/drive/root/delta"
            if token == "T1":
                valores = [item_archivo("f6", "00000003.png", "D1"), item_archivo("f7", "00000004.png", "D1"), item_archivo("f1", "00000001.png", "D1"), {"id": "f5", "deleted": {}}]
                return self.responder(200, {"value": valores, "@odata.deltaLink": base + "?token=T2"})
            if token == "T2":
                return self.responder(200, {"value": [], "@odata.deltaLink": base + "?token=T2"})
            if (consulta.get("pagina") or [""])[0] == "2":
                valores = [item_archivo("f1", "00000001.png", "D1"), item_archivo("f2", "00000002.png", "D1"), item_archivo("f3", "info", "D1"),
                           item_archivo("f4", "foto.png", "P"), item_archivo("f5", "~temporal.png", "D1"), item_archivo("f8", "notas.txt", "D1")]
                return self.responder(200, {"value": valores, "@odata.deltaLink": base + "?token=T1"})
            valores = [{"id": "R", "name": "root", "root": {}, "folder": {}}] + [item_carpeta(*c) for c in CARPETAS]
            return self.responder(200, {"value": valores, "@odata.nextLink": base + "?pagina=2"})
        if "/drive/items/" in url.path and url.path.endswith("/content"):
            item = url.path.split("/drive/items/")[1].split("/")[0]
            if item == "f7" and S["falla_f7"]:
                S["falla_f7"] = False
                return self.responder(403, {"error": {"code": "accessDenied"}})
            return self.responder(302, cabeceras={"Location": f"http://127.0.0.1:{self.server.server_port}/blob/{item}"})
        self.responder(404, {"error": "no existe"})


servidor = ThreadingHTTPServer(("127.0.0.1", 0), Falso)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
puerto = servidor.server_port

with A.app.app_context():
    p1 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000123','2026-10-14','Uno','Ana',?,?)", (admin, db.ahora()))
    p2 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000124','2026-10-14','Dos','Beto',?,?)", (admin, db.ahora()))

for k in onedrive.NOMBRES:
    os.environ.pop(k, None)

print("1) sin configurar no hace nada")
with A.app.app_context():
    chequear("sin datos de Microsoft no está configurado", not onedrive.configurado() and onedrive.ciclo() is None)
    chequear("la pantalla no muestra nada de OneDrive", onedrive.estado_onedrive() == {"configurado": False})
    os.environ["GRAPH_TENANT"] = "sin-configurar"
    chequear("el valor provisorio de Terraform cuenta como sin configurar", not onedrive.configurado())

os.environ.update(GRAPH_URL=f"http://127.0.0.1:{puerto}/v1.0", GRAPH_LOGIN_URL=f"http://127.0.0.1:{puerto}", GRAPH_TENANT="inquilino", GRAPH_CLIENT_ID="aplicacion",
                  GRAPH_CLIENT_SECRET="secreto-malo", GRAPH_USUARIO="escaner@vighi.com", GRAPH_CARPETA="Escaneos")

print("2) credenciales equivocadas")
with A.app.app_context():
    chequear("con un secreto malo no se procesa nada y queda el error a la vista", onedrive.ciclo() is None and "secreto equivocado" in (onedrive.estado("error") or ""), str(onedrive.estado("error")))
c = A.app.test_client()
with c.session_transaction() as s:
    s["uid"] = admin
chequear("el aviso aparece en la pantalla de órdenes", "secreto equivocado" in c.get("/ordenes").get_data(as_text=True))
os.environ["GRAPH_CLIENT_SECRET"] = "secreto-bueno"

print("3) primera revisión (todo lo que ya hay)")
with A.app.app_context():
    hechos = onedrive.ciclo()
    filas = {r["nombre"]: dict(r) for r in db.q("SELECT nombre, estado, detalle FROM onedrive_archivos")}
    ordenes = {r["nombre"]: (r["protocolo_id"], r["metodo"], r["grupo"]) for r in db.q("SELECT nombre, protocolo_id, metodo, grupo FROM ordenes")}
chequear("lee las dos hojas de la carpeta vigilada", hechos == 2, str((hechos, filas)))
chequear("ignora lo que no es imagen, lo temporal y lo que está fuera de la carpeta vigilada", sorted(filas) == ["00000001.png", "00000002.png", "foto.png"] and filas["foto.png"]["estado"] == "fuera", str(filas))
chequear("la primera hoja se adjunta por QR y la siguiente la sigue como continuación", ordenes.get("00000001.png", (0, 0, 0))[:2] == (p1, "qr") and ordenes.get("00000002.png", (0, 0, 0))[:2] == (p1, "continuacion"), str(ordenes))
chequear("agrupa por la carpeta del documento con la ruta de OneDrive", ordenes.get("00000001.png", (0, 0, ""))[2] == "Escaneos/Escaneo ordenes/Batch1/00000001", str(ordenes))
chequear("descarga sin mandar la clave de Microsoft al servidor de archivos", S["blob_con_clave"] == 0 and S["tokens"] >= 2)
with A.app.app_context():
    chequear("guarda el punto de partida para pedir solo lo nuevo", (onedrive.estado("delta") or "").endswith("token=T1") and onedrive.estado("ultimo") and onedrive.estado("error") == "")
pagina = c.get("/ordenes").get_data(as_text=True)
chequear("la pantalla de órdenes cuenta lo leído", "Lectura automática de OneDrive" in pagina and "2 archivo(s) leído(s)" in pagina and "secreto equivocado" not in pagina, pagina[:0])

print("4) revisión siguiente (solo lo nuevo)")
with A.app.app_context():
    S["pedidos"].clear()
    hechos = onedrive.ciclo()
    filas = {r["nombre"]: dict(r) for r in db.q("SELECT nombre, estado, intentos FROM onedrive_archivos")}
    o3 = db.uno("SELECT protocolo_id, metodo FROM ordenes WHERE nombre='00000003.png'")
chequear("pide los cambios desde el punto guardado y no relee todo", any("token=T1" in p for p in S["pedidos"]) and not any("pagina=2" in p for p in S["pedidos"]), str(S["pedidos"]))
chequear("procesa la hoja nueva y no vuelve a leer la que no cambió", hechos == 1 and o3 and o3["protocolo_id"] == p1 and o3["metodo"] == "continuacion", str((hechos, o3)))
chequear("si Microsoft rechaza la descarga, el archivo queda en espera para reintentar", filas["00000004.png"]["estado"] == "pendiente" and filas["00000004.png"]["intentos"] == 1, str(filas))
with A.app.app_context():
    hechos = onedrive.ciclo()
    f7 = db.uno("SELECT estado FROM onedrive_archivos WHERE nombre='00000004.png'")
    o4 = db.uno("SELECT protocolo_id, metodo FROM ordenes WHERE nombre='00000004.png'")
chequear("en la vuelta siguiente lo reintenta y lo adjunta", hechos == 1 and f7["estado"] == "listo" and o4["protocolo_id"] == p2 and o4["metodo"] == "qr", str((hechos, f7, o4)))
with A.app.app_context():
    cuenta = db.uno("SELECT COUNT(*) AS n FROM ordenes")["n"]
    onedrive.ciclo()
    chequear("una vuelta sin novedades no duplica nada", db.uno("SELECT COUNT(*) AS n FROM ordenes")["n"] == cuenta)

print("5) el punto de partida vencido")
with A.app.app_context():
    onedrive.fijar("delta", f"http://127.0.0.1:{puerto}/v1.0/users/escaner@vighi.com/drive/root/delta?token=VIEJO")
    antes = db.uno("SELECT COUNT(*) AS n FROM ordenes")["n"]
    onedrive.ciclo()
    chequear("si Microsoft lo da por vencido (410) vuelve a empezar sin duplicar hojas", S["delta_viejo"] == 1 and (onedrive.estado("delta") or "").endswith("token=T1") and db.uno("SELECT COUNT(*) AS n FROM ordenes")["n"] == antes, str(S))

print("6) un solo proceso a la vez")
with A.app.app_context():
    chequear("toma el turno", onedrive._tomar_turno())
    chequear("otro proceso no puede entrar mientras tanto", not onedrive._tomar_turno() and onedrive.vuelta() is None)
    onedrive._soltar_turno()
    chequear("al soltarlo se puede volver a tomar", onedrive._tomar_turno())
    onedrive._soltar_turno()

print("7) rutas")
carpetas = {"E": {"nombre": "Escaneos", "padre": "R"}, "EO": {"nombre": "Escaneo ordenes", "padre": "E"}, "P": {"nombre": "Personal", "padre": "R"}}
chequear("arma la ruta completa de un archivo", onedrive.ruta_de(carpetas, "R", "EO", "a.png", "Escaneos") == "/Escaneos/Escaneo ordenes/a.png")
chequear("ignora lo que está fuera de la carpeta vigilada", onedrive.ruta_de(carpetas, "R", "P", "a.png", "Escaneos") is None)
chequear("acepta una carpeta vigilada de varios niveles", onedrive.ruta_de(carpetas, "R", "EO", "a.png", "escaneos/escaneo ordenes") == "/Escaneos/Escaneo ordenes/a.png")
chequear("una carpeta que no se conoce no se toma", onedrive.ruta_de(carpetas, "R", "X", "a.png", "Escaneos") is None)

for k in onedrive.NOMBRES:
    os.environ.pop(k, None)
chequear("no arranca el hilo si no está configurado", onedrive.iniciar(A.app) is False)
servidor.shutdown()
print()
print("FALLAS:", fallas if fallas else "ninguna")
