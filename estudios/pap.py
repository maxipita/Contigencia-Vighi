"""PAP: siempre ginecológico, resultado en Bethesda, lote por citotécnico."""
from .base import GINECOLOGICA, Estudio, _texto


class Pap(Estudio):
    clave = "PAP"
    nombre = "PAP"
    categoria = "Citologías"
    pasos = ["coloreado", "citotecnicos", "microscopia"]
    plazos = {"ingreso": (1, 20), "coloreado": (2, 20), "citotecnicos": (3, 18), "microscopia": (4, 20)}
    cantidades = ["1", "2", "1/2"]
    subcategoria_fija = GINECOLOGICA
    sitio_fijo = "Vagina"
    citologia_hormonal = True
    bethesda = True
    lote_por_citotecnico = True

    def requisito(self, etapa, macro, micro, ihq):
        if etapa == "microscopia":          # en el PAP alcanza con el resultado Bethesda
            return None if _texto(micro, "bethesda") else "Falta el resultado (Bethesda)."
        return super().requisito(etapa, macro, micro, ihq)


ESTUDIO = Pap()
