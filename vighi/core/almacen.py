import os
import uuid

from vighi.core import db
MARCA = b"~obj~"
_cliente = {}


def _directorio():
    return db.ajuste("ALMACEN_DIR")


def _bucket():
    return db.ajuste("S3_BUCKET")


def activo():
    return bool(_directorio() or _bucket())


def _s3():
    if "s3" not in _cliente:
        import boto3
        region = db.ajuste("AWS_REGION") or None
        _cliente["s3"] = boto3.client("s3", region_name=region)
    return _cliente["s3"]


def _ruta(clave):
    return os.path.join(_directorio(), *clave.split("/"))


def _poner(clave, datos, tipo):
    if _directorio():
        ruta = _ruta(clave)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(datos)
    else:
        _s3().put_object(Bucket=_bucket(), Key=clave, Body=datos, ContentType=tipo, ServerSideEncryption="AES256")


def _traer(clave):
    if _directorio():
        with open(_ruta(clave), "rb") as f:
            return f.read()
    return _s3().get_object(Bucket=_bucket(), Key=clave)["Body"].read()


def _quitar(clave):
    if _directorio():
        try:
            os.remove(_ruta(clave))
        except FileNotFoundError:
            pass
    else:
        _s3().delete_object(Bucket=_bucket(), Key=clave)


def guardar(prefijo, datos, tipo="application/octet-stream"):
    datos = bytes(datos)
    if not activo():
        return datos
    clave = f"{prefijo}/{uuid.uuid4().hex}"
    _poner(clave, datos, tipo)
    return MARCA + clave.encode("ascii")


def leer(valor):
    valor = bytes(valor)
    if valor.startswith(MARCA):
        return _traer(valor[len(MARCA):].decode("ascii"))
    return valor


def borrar(valor):
    valor = bytes(valor or b"")
    if valor.startswith(MARCA):
        _quitar(valor[len(MARCA):].decode("ascii"))
