"""Biopsias (con IHQ opcional)."""
from .base import Estudio


class Biopsia(Estudio):
    clave = "BP"
    nombre = "Biopsia"
    categoria = "Biopsias"
    pasos = ["macroscopia", "procesamiento", "inclusion", "corte", "coloreado", "microscopia"]
    pasos_ihq = ["corte_ihq", "envio_ihq", "proc_ihq", "interp_ihq"]
    plazos = {"ingreso": (1, 20), "macroscopia": (2, 20), "procesamiento": (3, 20), "inclusion": (3, 20),
              "corte": (4, 20), "coloreado": (5, 20), "microscopia": (6, 20),
              "corte_ihq": (7, 20), "envio_ihq": (8, 18), "proc_ihq": (9, 20), "interp_ihq": (13, 20)}
    secciones = ["macro", "micro", "ihq"]
    sector_responsable = "firmante"
    etiqueta_responsable = "Médico firmante"
    etiqueta_cantidad = "frascos"
    lotes = ["NO ONCO", "ENDO", "ONCO", "PAPURG", "TACOS", "HPM"]


ESTUDIO = Biopsia()
