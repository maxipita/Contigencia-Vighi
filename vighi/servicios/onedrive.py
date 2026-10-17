import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from vighi.core import db
from vighi.servicios.ordenes import EXTENSIONES, grupo_de, procesar_archivo

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SIN_CONFIGURAR = "sin-configurar"
NOMBRES = ("GRAPH_TENANT", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_USUARIO", "GRAPH_CARPETA", "GRAPH_INTERVALO")
OBLIGATORIOS = ("GRAPH_TENANT", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_USUARIO")
MAX_INTENTOS = 5
TAMANO_MAXIMO = 60 * 1024 * 1024
LOTE_PENDIENTES = 500
TURNO = 300
_token = {"clave": None, "valor": None, "vence": 0}
_hilo = None


class ErrorGraph(Exception):
    def __init__(self, mensaje, codigo=None):
        super().__init__(mensaje)
        self.codigo = codigo


def config():
    datos = {k: ("" if db.ajuste(k) == SIN_CONFIGURAR else db.ajuste(k).strip()) for k in NOMBRES}
    datos["GRAPH_CARPETA"] = datos["GRAPH_CARPETA"].replace("\\", "/").strip("/") or "Escaneos"
    datos["GRAPH_INTERVALO"] = max(20, int(datos["GRAPH_INTERVALO"])) if datos["GRAPH_INTERVALO"].isdigit() else 60
    return datos


def configurado():
    c = config()
    return all(c[k] for k in OBLIGATORIOS)


def _abrir(pedido, tiempo=120, seguir=True):
    abridor = urllib.request.build_opener() if seguir else urllib.request.build_opener(_SinRedireccion)
    for intento in range(3):
        try:
            with abridor.open(pedido, timeout=tiempo) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            if not seguir and e.code in (301, 302, 303, 307, 308):
                return e.code, dict(e.headers), b""
            cuerpo = e.read()[:300].decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and intento < 2:
                time.sleep(min(int(e.headers.get("Retry-After") or 2 * (intento + 1)), 30))
                continue
            raise ErrorGraph(f"Microsoft respondió {e.code}: {cuerpo}", e.code)
        except (OSError, TimeoutError) as e:
            if intento < 2:
                time.sleep(2)
                continue
            raise ErrorGraph(f"No se pudo hablar con Microsoft: {getattr(e, 'reason', e)}")


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _autorizar(c):
    clave = (c["GRAPH_TENANT"], c["GRAPH_CLIENT_ID"])
    if _token["clave"] == clave and _token["vence"] > time.time() + 60:
        return _token["valor"]
    cuerpo = urllib.parse.urlencode({"client_id": c["GRAPH_CLIENT_ID"], "client_secret": c["GRAPH_CLIENT_SECRET"],
                                     "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}).encode("utf-8")
    base = db.ajuste("GRAPH_LOGIN_URL") or LOGIN
    pedido = urllib.request.Request(f"{base}/{urllib.parse.quote(c['GRAPH_TENANT'])}/oauth2/v2.0/token", data=cuerpo, method="POST",
                                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    datos = json.loads(_abrir(pedido)[2].decode("utf-8"))
    if not datos.get("access_token"):
        raise ErrorGraph("Microsoft no entregó el acceso: " + str(datos.get("error_description") or datos.get("error") or "")[:200])
    _token.update(clave=clave, valor=datos["access_token"], vence=time.time() + int(datos.get("expires_in") or 3600))
    return _token["valor"]


def _graph():
    return db.ajuste("GRAPH_URL") or GRAPH


def _get(url, c):
    pedido = urllib.request.Request(url, headers={"Authorization": "Bearer " + _autorizar(c), "Accept": "application/json"})
    return json.loads(_abrir(pedido)[2].decode("utf-8"))


def _descargar(c, item_id):
    url = f"{_graph()}/users/{urllib.parse.quote(c['GRAPH_USUARIO'], safe='@')}/drive/items/{urllib.parse.quote(item_id, safe='')}/content"
    estado, cabeceras, cuerpo = _abrir(urllib.request.Request(url, headers={"Authorization": "Bearer " + _autorizar(c)}), seguir=False)
    if estado in (301, 302, 303, 307, 308):
        destino = next((v for k, v in cabeceras.items() if k.lower() == "location"), "")
        if not destino:
            raise ErrorGraph("Microsoft no indicó dónde descargar el archivo.")
        return _abrir(urllib.request.Request(destino))[2]
    return cuerpo


def estado(clave):
    fila = db.uno("SELECT valor FROM onedrive_estado WHERE clave=?", (clave,))
    return fila["valor"] if fila else None


def fijar(clave, valor):
    db.lote_ex([("DELETE FROM onedrive_estado WHERE clave=?", (clave,)), ("INSERT INTO onedrive_estado (clave, valor) VALUES (?,?)", (clave, valor))])


def _aplicar_pagina(items):
    ahora = db.ahora()
    cambios = []
    for it in items:
        item_id = it.get("id")
        if not item_id:
            continue
        padre = (it.get("parentReference") or {}).get("id")
        if "root" in it:
            fijar("raiz", item_id)
        elif it.get("deleted") is not None:
            cambios.append(("DELETE FROM onedrive_carpetas WHERE id=?", (item_id,)))
            cambios.append(("DELETE FROM onedrive_archivos WHERE id=? AND estado='pendiente'", (item_id,)))
        elif "folder" in it:
            cambios.append(("DELETE FROM onedrive_carpetas WHERE id=?", (item_id,)))
            cambios.append(("INSERT INTO onedrive_carpetas (id, nombre, padre) VALUES (?,?,?)", (item_id, (it.get("name") or "")[:255], padre)))
        elif "file" in it:
            nombre = it.get("name") or ""
            if not nombre.lower().endswith(EXTENSIONES) or nombre.startswith(("~", ".")):
                continue
            modificado = (it.get("lastModifiedDateTime") or "")[:40]
            previo = db.uno("SELECT modificado FROM onedrive_archivos WHERE id=?", (item_id,))
            if previo is None:
                cambios.append(("INSERT INTO onedrive_archivos (id, nombre, padre, tamano, modificado, estado, intentos, descubierto_en) VALUES (?,?,?,?,?,'pendiente',0,?)",
                                (item_id, nombre[:255], padre, it.get("size"), modificado, ahora)))
            elif previo["modificado"] != modificado:
                cambios.append(("UPDATE onedrive_archivos SET nombre=?, padre=?, tamano=?, modificado=?, estado='pendiente', intentos=0, detalle=NULL WHERE id=?",
                                (nombre[:255], padre, it.get("size"), modificado, item_id)))
    if cambios:
        db.lote_ex(cambios)


def sincronizar_cambios(c):
    for _ in range(2):
        url = estado("delta") or f"{_graph()}/users/{urllib.parse.quote(c['GRAPH_USUARIO'], safe='@')}/drive/root/delta"
        enlace_final = None
        try:
            while url:
                datos = _get(url, c)
                _aplicar_pagina(datos.get("value") or [])
                enlace_final = datos.get("@odata.deltaLink") or enlace_final
                url = datos.get("@odata.nextLink")
        except ErrorGraph as error:
            if error.codigo == 410 and estado("delta"):
                fijar("delta", "")
                continue
            raise
        if enlace_final:
            fijar("delta", enlace_final)
        return


def ruta_de(carpetas, raiz, padre, nombre, base):
    partes, actual, saltos = [nombre], padre, 0
    while actual and actual != raiz and saltos < 60:
        carpeta = carpetas.get(actual)
        if not carpeta:
            return None
        partes.append(carpeta["nombre"])
        actual = carpeta["padre"]
        saltos += 1
    if actual != raiz:
        return None
    partes.reverse()
    prefijo = [p.lower() for p in base.split("/")]
    if [p.lower() for p in partes[:len(prefijo)]] != prefijo or len(partes) <= len(prefijo):
        return None
    return "/" + "/".join(partes)


def _resumen(paginas):
    adjuntas = sum(1 for p in paginas if p["estado"] == "adjunta")
    pendientes = sum(1 for p in paginas if p["estado"] == "pendiente")
    repetidas = sum(1 for p in paginas if p["estado"] == "repetida")
    return f"{adjuntas} adjuntas, {pendientes} sin identificar, {repetidas} repetidas"


def _marcar(item_id, nuevo, detalle=None, intento=False):
    db.ex("UPDATE onedrive_archivos SET estado=?, detalle=?, intentos=intentos+?, procesado_en=? WHERE id=?",
          (nuevo, (detalle or "")[:300] or None, 1 if intento else 0, db.ahora(), item_id))


def _fallo(item_id, intentos, detalle):
    _marcar(item_id, "error" if intentos + 1 >= MAX_INTENTOS else "pendiente", detalle, intento=True)


def procesar_pendientes(c, extender=lambda: None):
    carpetas = {r["id"]: r for r in db.q("SELECT id, nombre, padre FROM onedrive_carpetas")}
    raiz = estado("raiz")
    hechos = 0
    for f in db.q("SELECT id, nombre, padre, tamano, intentos FROM onedrive_archivos WHERE estado='pendiente' ORDER BY descubierto_en, id LIMIT ?", (LOTE_PENDIENTES,)):
        extender()
        ruta = ruta_de(carpetas, raiz, f["padre"], f["nombre"], c["GRAPH_CARPETA"])
        if ruta is None:
            _marcar(f["id"], "fuera")
            continue
        if (f["tamano"] or 0) > TAMANO_MAXIMO:
            _marcar(f["id"], "descartado", "El archivo es demasiado grande")
            continue
        try:
            contenido = _descargar(c, f["id"])
        except ErrorGraph as error:
            _fallo(f["id"], f["intentos"], str(error))
            continue
        try:
            paginas = procesar_archivo(f["nombre"], contenido, None, grupo=grupo_de(ruta))
        except ValueError as error:
            _marcar(f["id"], "descartado", str(error))
            continue
        except Exception as error:
            _fallo(f["id"], f["intentos"], f"{type(error).__name__}: {error}")
            continue
        _marcar(f["id"], "listo", _resumen(paginas))
        hechos += 1
    return hechos


def ciclo(extender=lambda: None):
    c = config()
    if not configurado():
        return None
    try:
        sincronizar_cambios(c)
        hechos = procesar_pendientes(c, extender)
    except ErrorGraph as error:
        fijar("error", f"{db.ahora()}  {error}"[:300])
        return None
    fijar("ultimo", db.ahora())
    fijar("error", "")
    return hechos


def _tomar_turno():
    db.ex("DELETE FROM bloqueos WHERE nombre='onedrive' AND vence<?", (time.time(),))
    try:
        db.ex("INSERT INTO bloqueos (nombre, vence) VALUES ('onedrive', ?)", (time.time() + TURNO,))
        return True
    except db.IntegrityError:
        return False


def _extender_turno():
    db.ex("UPDATE bloqueos SET vence=? WHERE nombre='onedrive'", (time.time() + TURNO,))


def _soltar_turno():
    db.ex("DELETE FROM bloqueos WHERE nombre='onedrive'")


def vuelta():
    if not _tomar_turno():
        return None
    try:
        return ciclo(_extender_turno)
    finally:
        _soltar_turno()


def iniciar(app):
    global _hilo
    if _hilo or not configurado():
        return False

    def bucle():
        while True:
            try:
                with app.app_context():
                    vuelta()
            except Exception as error:
                print(f"OneDrive: {type(error).__name__}: {error}", flush=True)
            time.sleep(config()["GRAPH_INTERVALO"])

    _hilo = threading.Thread(target=bucle, name="onedrive", daemon=True)
    _hilo.start()
    return True


def estado_onedrive():
    if not configurado():
        return {"configurado": False}
    conteo = {r["estado"]: r["n"] for r in db.q("SELECT estado, COUNT(*) AS n FROM onedrive_archivos GROUP BY estado")}
    return {"configurado": True, "carpeta": config()["GRAPH_CARPETA"], "ultimo": estado("ultimo"), "error": estado("error") or None,
            "pendientes": conteo.get("pendiente", 0), "listos": conteo.get("listo", 0), "con_error": conteo.get("error", 0), "descartados": conteo.get("descartado", 0)}
