"""Registro de los tipos de estudio. Un protocolo (paciente) puede tener varios estudios de distinto tipo.
Para sumar un tipo nuevo: crear su módulo con ESTUDIO = ... y agregarlo a REGISTRO."""
from . import bp, ct, pap
from .base import ETAPAS, GINECOLOGICA, NOMBRE_ETAPA, SECTORES

REGISTRO = {m.ESTUDIO.clave: m.ESTUDIO for m in (pap, bp, ct)}
TIPOS = {k: e.nombre for k, e in REGISTRO.items()}
PASOS_IHQ = bp.ESTUDIO.pasos_ihq


def validar_combinacion(lista):
    """Reglas para los estudios de un mismo protocolo (lista de dicts con tipo, subcategoria y anulado).
    Con un PAP solo pueden ir muestras ginecológicas; las demás se combinan libremente (ej. biopsia + CT de líquido)."""
    activos = [e for e in lista if not e.get("anulado")]
    if any(e["tipo"] == "PAP" for e in activos):
        otras = [e for e in activos if e["tipo"] != "PAP" and e.get("subcategoria") != GINECOLOGICA]
        if otras:
            detalle = ", ".join(f"{TIPOS[e['tipo']]} {e.get('subcategoria') or '(sin subcategoría)'}" for e in otras)
            return f"Con un PAP solo pueden ir muestras ginecológicas: revisá {detalle}."
    return None


__all__ = ["ETAPAS", "GINECOLOGICA", "NOMBRE_ETAPA", "PASOS_IHQ", "REGISTRO", "SECTORES", "TIPOS", "validar_combinacion"]
