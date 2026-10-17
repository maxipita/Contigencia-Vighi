import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from vighi.core import almacen, db
from vighi.dominio.anterior import clave
from vighi.servicios.imagenes import procesar_imagen
from vighi.servicios.migracion_anterior import usuario_sistema
from vighi.servicios.ordenes import guardar_pagina

PREFIJO = "https://s3.us-west-2.amazonaws.com/repo.southernbits.com/"
MAX_BYTES = 15 * 1024 * 1024
RE_FECHA_URL = re.compile(r"/svighi/(\d{4})/(\d{1,2})/(\d{1,2})/")
HILOS = 3


def nombre_de(url):
    return url.rsplit("/", 1)[-1][:120]


def fecha_de(url):
    m = RE_FECHA_URL.search(url)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d} 00:00:00" if m else db.ahora()


TIPOS_NUEVOS = {clave(t): t for t in db.TIPOS_IMAGEN_INICIALES} | {"imagen microscopio": "Imagen de microscopio"}


def tipo_nuevo(i):
    anterior = (i.get("tipo") or "").strip()
    return TIPOS_NUEVOS.get(clave(anterior), anterior)[:40]


def es_orden(tipo):
    return clave(tipo).startswith("orden")


def descargar(url):
    if not url.startswith(PREFIJO):
        raise ValueError("origen no permitido")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vighi-migracion"}), timeout=30) as r:
        contenido = r.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        raise ValueError("pesa más de 15 MB")
    return contenido


def bajar(i):
    try:
        return i, descargar(i["url"]), None
    except Exception as e:
        return i, None, f"{nombre_de(i['url'])}: {e}"


def guardar_imagen(pid, i, grande, mini, yo):
    db.ex("INSERT INTO imagenes (protocolo_id, usuario_id, creado_en, nombre, descripcion, tipo, imagen, miniatura) VALUES (?,?,?,?,?,?,?,?)",
          (pid, yo, fecha_de(i["url"]), nombre_de(i["url"]), "", tipo_nuevo(i),
           almacen.guardar("imagenes", grande, "image/jpeg"), almacen.guardar("imagenes", mini, "image/jpeg")))


def importar_imagenes(numero, imagenes, ensayo=False):
    p = db.uno("SELECT id FROM protocolos WHERE numero=? AND origen='anterior'", (numero,))
    resultado = {"importadas": 0, "existentes": 0, "errores": []}
    if not p:
        resultado["errores"].append(f"{numero}: el protocolo no está cargado")
        return resultado
    hechas = {r["nombre"] for r in db.q("SELECT nombre FROM imagenes WHERE protocolo_id=?", (p["id"],))}
    hechas |= {r["nombre"] for r in db.q("SELECT nombre FROM ordenes WHERE protocolo_id=?", (p["id"],))}
    pendientes = [i for i in imagenes if nombre_de(i["url"]) not in hechas]
    resultado["existentes"] = len(imagenes) - len(pendientes)
    if ensayo:
        resultado["importadas"] = len(pendientes)
        return resultado
    yo = usuario_sistema()
    with ThreadPoolExecutor(HILOS) as pool:
        bajadas = list(pool.map(bajar, pendientes))
    for orden, (i, contenido, error) in enumerate(bajadas, start=1):
        try:
            if error:
                raise ValueError(error)
            grande, mini = procesar_imagen(contenido)
            if es_orden(i.get("tipo")):
                ident = {"protocolo_id": p["id"], "metodo": "manual", "leido": None, "numero": None, "motivo": None}
                if guardar_pagina(None, nombre_de(i["url"]), orden, ident, yo, reducida=(grande, mini)) is None:
                    resultado["existentes"] += 1
                    continue
            else:
                guardar_imagen(p["id"], i, grande, mini, yo)
            resultado["importadas"] += 1
        except Exception as e:
            resultado["errores"].append(f"{numero} {e}")
    if resultado["importadas"]:
        db.auditar(yo, p["id"], "migracion_imagenes", f"{resultado['importadas']} imagen(es) del sistema anterior")
    return resultado
