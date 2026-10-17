import io

from flask import abort, redirect, request, send_file, url_for

from vighi.core import almacen, db


SQL_IMAGENES = """SELECT i.id, i.protocolo_id, i.nombre, i.descripcion, i.tipo, i.creado_en, u.iniciales FROM imagenes i
                  LEFT JOIN usuarios u ON u.id=i.usuario_id WHERE i.protocolo_id=? ORDER BY i.id"""
MAX_IMAGENES = 30
PERMISOS_IMAGENES = ("protocolo_editar", "macro", "micro")


def procesar_imagen(contenido):
    from PIL import Image, ImageOps
    if len(contenido) > 15 * 1024 * 1024:
        raise ValueError("pesa más de 15 MB")
    try:
        img = Image.open(io.BytesIO(contenido))
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            fondo = Image.new("RGB", img.size, (255, 255, 255))
            fondo.paste(img, mask=img.split()[-1])
            img = fondo
        else:
            img = img.convert("RGB")
    except Exception:
        raise ValueError("no es una imagen JPG, PNG o WEBP válida")

    return reducir_a_jpeg(img)


def reducir_a_jpeg(img):
    def jpeg(lado, calidad):
        chica = img.copy()
        chica.thumbnail((lado, lado))
        salida = io.BytesIO()
        chica.save(salida, "JPEG", quality=calidad, optimize=True)
        return salida.getvalue()

    for lado, calidad in ((2000, 85), (1800, 80), (1600, 72), (1400, 65), (1200, 55), (1000, 45), (800, 40)):
        grande = jpeg(lado, calidad)
        if len(grande) <= 1_200_000:
            break
    return grande, jpeg(360, 78)


def imagenes_de(pid):
    return db.q(SQL_IMAGENES, (pid,))


def volver_a_imagenes(pid):
    destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for("protocolos.protocolo", pid=pid)
    return redirect(destino.split("#")[0] + "#imagenes")


def enviar_imagen(iid, columna):
    r = db.uno(f"SELECT {columna} AS datos FROM imagenes WHERE id=?", (iid,)) or abort(404)
    respuesta = send_file(io.BytesIO(almacen.leer(r["datos"])), mimetype="image/jpeg", conditional=False)
    respuesta.headers["Cache-Control"] = "private, max-age=86400"
    return respuesta
