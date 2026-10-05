from .base import Estudio


class Citologia(Estudio):
    clave = "CT"
    nombre = "Citología"
    categoria = "Citologías"
    pasos = ["coloreado", "microscopia"]
    plazos = {"ingreso": (1, 20), "coloreado": (2, 20), "microscopia": (3, 20)}
    lotes = ["CT"]
    sector_responsable = "firmante"
    etiqueta_responsable = "Médico firmante"


ESTUDIO = Citologia()
