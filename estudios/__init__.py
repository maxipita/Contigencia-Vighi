from . import bp, ct, pap
from .base import ETAPAS, GINECOLOGICA, NOMBRE_ETAPA, SECTORES

REGISTRO = {m.ESTUDIO.clave: m.ESTUDIO for m in (pap, bp, ct)}
TIPOS = {k: e.nombre for k, e in REGISTRO.items()}
PASOS_IHQ = bp.ESTUDIO.pasos_ihq


def validar_combinacion(lista):
    activos = [e for e in lista if not e.get("anulado")]
    if any(e["tipo"] == "PAP" for e in activos):
        otras = [e for e in activos if e["tipo"] != "PAP" and e.get("subcategoria") != GINECOLOGICA]
        if otras:
            detalle = ", ".join(f"{TIPOS[e['tipo']]} {e.get('subcategoria') or '(sin subcategoría)'}" for e in otras)
            return f"Con un PAP solo pueden ir muestras ginecológicas: revisá {detalle}."
    return None


__all__ = ["ETAPAS", "GINECOLOGICA", "NOMBRE_ETAPA", "PASOS_IHQ", "REGISTRO", "SECTORES", "TIPOS", "validar_combinacion"]
