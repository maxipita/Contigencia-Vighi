import os

from vighi.core import almacen, db

EXTENSIONES = {
    "pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xls": "application/vnd.ms-excel", "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "doc": "application/msword", "txt": "text/plain",
}
VISIBLES = ("pdf", "jpg", "jpeg", "png", "webp")
MAX_BYTES = 15 * 1024 * 1024
MAX_BYTES_EN_BASE = 1_000_000
MAX_POR_FACTURA = 30

SQL_ARCHIVOS = """SELECT a.id, a.factura_id, a.nombre, a.extension, a.tamano, a.subido_en, u.iniciales AS subio
                  FROM factura_archivos a LEFT JOIN usuarios u ON u.id=a.subido_por WHERE a.factura_id=? ORDER BY a.id"""


def extension(nombre):
    return os.path.splitext(nombre or "")[1].lower().lstrip(".")


def nombre_seguro(nombre):
    base = os.path.basename((nombre or "").replace("\\", "/")).strip()
    return "".join(c for c in base if c.isprintable() and c not in '<>:"|?*')[:150] or "archivo"


def _contenido_valido(ext, datos):
    if ext == "pdf":
        return datos.startswith(b"%PDF-")
    if ext in ("jpg", "jpeg"):
        return datos.startswith(b"\xff\xd8\xff")
    if ext == "png":
        return datos.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == "webp":
        return datos[:4] == b"RIFF" and datos[8:12] == b"WEBP"
    if ext in ("xlsx", "docx"):
        return datos.startswith(b"PK\x03\x04") or datos.startswith(b"PK\x05\x06")
    if ext in ("xls", "doc"):
        return datos.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    return True


def archivos_de(fid):
    return db.q(SQL_ARCHIVOS, (fid,))


def archivo_o_none(aid):
    return db.uno("SELECT * FROM factura_archivos WHERE id=?", (aid,))


def validar(nombre, datos):
    ext = extension(nombre)
    if ext not in EXTENSIONES:
        return f"«{nombre}»: tipo no admitido (se aceptan PDF, imágenes, Excel, CSV, Word y texto)."
    if not datos:
        return f"«{nombre}» está vacío."
    if len(datos) > MAX_BYTES:
        return f"«{nombre}» pesa más de {MAX_BYTES // (1024 * 1024)} MB."
    if not almacen.activo() and len(datos) > MAX_BYTES_EN_BASE:
        return f"«{nombre}» es muy grande para guardarlo sin almacenamiento de archivos (máximo 1 MB)."
    if not _contenido_valido(ext, datos):
        return f"«{nombre}»: el contenido no coincide con la extensión declarada."
    return None


def guardar(fid, nombre, datos, usuario_id):
    ext = extension(nombre)
    db.ex("INSERT INTO factura_archivos (factura_id, nombre, extension, tamano, datos, subido_por, subido_en) VALUES (?,?,?,?,?,?,?)",
          (fid, nombre_seguro(nombre), ext, len(datos), almacen.guardar("facturas", datos, EXTENSIONES[ext]), usuario_id, db.ahora()))


def cantidad(fid):
    return db.uno("SELECT COUNT(*) AS n FROM factura_archivos WHERE factura_id=?", (fid,))["n"]


def quitar(fila):
    almacen.borrar(fila["datos"])
    db.ex("DELETE FROM factura_archivos WHERE id=?", (fila["id"],))


def tamano_legible(n):
    return f"{n / (1024 * 1024):.1f} MB" if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"
