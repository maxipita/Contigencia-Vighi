import argparse
import json
import mimetypes
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime

EXTENSIONES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
ESPERA_ESTABLE = 5


def registrar(texto, archivo_log=None):
    linea = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {texto}"
    print(linea, flush=True)
    if archivo_log:
        try:
            with open(archivo_log, "a", encoding="utf-8") as f:
                f.write(linea + "\n")
        except OSError:
            pass


def cuerpo_multipart(nombre, contenido):
    limite = uuid.uuid4().hex
    tipo = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    cabecera = f'--{limite}\r\nContent-Disposition: form-data; name="archivo"; filename="{nombre}"\r\nContent-Type: {tipo}\r\n\r\n'.encode("utf-8")
    return cabecera + contenido + f"\r\n--{limite}--\r\n".encode("utf-8"), f"multipart/form-data; boundary={limite}"


def enviar(url, clave, ruta, tiempo=180):
    nombre = os.path.basename(ruta)
    with open(ruta, "rb") as f:
        cuerpo, tipo = cuerpo_multipart(nombre, f.read())
    pedido = urllib.request.Request(url.rstrip("/") + "/api/ordenes/automatico", data=cuerpo, method="POST",
                                    headers={"Authorization": "Bearer " + clave, "Content-Type": tipo, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=tiempo) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            return e.code, {"ok": False, "error": f"respuesta {e.code} del servidor"}


def mover(ruta, destino):
    os.makedirs(destino, exist_ok=True)
    nombre = os.path.basename(ruta)
    final = os.path.join(destino, nombre)
    if os.path.exists(final):
        base, ext = os.path.splitext(nombre)
        final = os.path.join(destino, f"{base}-{datetime.now():%Y%m%d-%H%M%S}{ext}")
    shutil.move(ruta, final)
    return final


def resumen(paginas):
    adjuntas = [p for p in paginas if p["estado"] == "adjunta"]
    pendientes = [p for p in paginas if p["estado"] == "pendiente"]
    repetidas = [p for p in paginas if p["estado"] == "repetida"]
    partes = []
    if adjuntas:
        partes.append(", ".join(sorted({p["numero"] for p in adjuntas})) + " (" + str(len(adjuntas)) + " pág.)")
    if pendientes:
        partes.append(f"{len(pendientes)} sin identificar")
    if repetidas:
        partes.append(f"{len(repetidas)} ya estaba(n)")
    return " · ".join(partes) or "sin páginas"


def candidatos(carpeta, vistos, espera=ESPERA_ESTABLE):
    nuevos = []
    for nombre in sorted(os.listdir(carpeta)):
        ruta = os.path.join(carpeta, nombre)
        if not os.path.isfile(ruta) or os.path.splitext(nombre)[1].lower() not in EXTENSIONES or nombre.startswith(("~", ".")):
            continue
        try:
            info = os.stat(ruta)
        except OSError:
            continue
        firma = (info.st_size, info.st_mtime)
        anterior = vistos.get(ruta)
        vistos[ruta] = (firma, time.time() if not anterior or anterior[0] != firma else anterior[1])
        if info.st_size > 0 and time.time() - vistos[ruta][1] >= espera:
            nuevos.append(ruta)
    return nuevos


def procesar_carpeta(carpeta, url, clave, vistos, log=None, enviar_archivo=enviar, espera=ESPERA_ESTABLE):
    hechos = 0
    for ruta in candidatos(carpeta, vistos, espera):
        nombre = os.path.basename(ruta)
        try:
            estado, datos = enviar_archivo(url, clave, ruta)
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            registrar(f"{nombre}: sin conexión con el sistema ({getattr(error, 'reason', error)}); se reintenta", log)
            return hechos
        if estado == 200 and datos.get("ok"):
            mover(ruta, os.path.join(carpeta, "Procesadas"))
            registrar(f"{nombre}: {resumen(datos['paginas'])}", log)
            hechos += 1
        elif estado == 401:
            registrar("La clave no es válida o fue revocada: se detiene el envío hasta que se corrija", log)
            return hechos
        elif estado == 400:
            mover(ruta, os.path.join(carpeta, "Con error"))
            registrar(f"{nombre}: el sistema no pudo leerlo ({datos.get('error')}); pasó a «Con error»", log)
        else:
            registrar(f"{nombre}: error del sistema ({estado}); se reintenta", log)
            return hechos
        vistos.pop(ruta, None)
    return hechos


def principal(argumentos=None):
    p = argparse.ArgumentParser(description="Sube al sistema las órdenes escaneadas que aparecen en una carpeta.")
    p.add_argument("--carpeta", default=os.environ.get("VIGHI_CARPETA"), help="carpeta que se vigila (la de OneDrive donde cae el escáner)")
    p.add_argument("--url", default=os.environ.get("VIGHI_URL"), help="dirección del sistema, por ejemplo https://contingencia.sistemacapvighi.com")
    p.add_argument("--clave", default=os.environ.get("VIGHI_CLAVE"), help="clave de integración (mejor por la variable VIGHI_CLAVE)")
    p.add_argument("--intervalo", type=int, default=20, help="segundos entre revisiones")
    p.add_argument("--una-vez", action="store_true", help="revisa una sola vez y termina")
    a = p.parse_args(argumentos)
    if not (a.carpeta and a.url and a.clave):
        p.error("faltan la carpeta, la dirección o la clave (--carpeta, --url, --clave o las variables VIGHI_CARPETA, VIGHI_URL, VIGHI_CLAVE)")
    if not os.path.isdir(a.carpeta):
        p.error(f"la carpeta {a.carpeta} no existe")
    log = os.path.join(a.carpeta, "vigilar_ordenes.log")
    registrar(f"Vigilando {a.carpeta} → {a.url}", log)
    vistos = {}
    if a.una_vez:
        procesar_carpeta(a.carpeta, a.url, a.clave, vistos, log)
        time.sleep(ESPERA_ESTABLE + 1)
        procesar_carpeta(a.carpeta, a.url, a.clave, vistos, log)
        return 0
    while True:
        procesar_carpeta(a.carpeta, a.url, a.clave, vistos, log)
        time.sleep(a.intervalo)


if __name__ == "__main__":
    sys.exit(principal())
