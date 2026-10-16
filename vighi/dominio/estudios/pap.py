from .base import GINECOLOGICA, Estudio, _texto

ESCALA = (("[-]", "No se observan"), ("[+]", "Escasa cantidad"), ("[++]", "Moderada cantidad"), ("[+++]", "Abundante cantidad"))
SIMPLES = (("leucocitos", "Leucocitos"), ("hematies", "Hematíes"))
HORMONAL = (("flora", "Flora"), ("aspecto", "Aspecto"), ("otros", "Otros"))
ONCOLOGICA = (("pavimentosas", "Pavimentosas"), ("endocervicales", "Endocervicales"), ("metaplasicas", "Metaplásicas"), ("endometriales", "Endometriales"))
RESULTADO = ("resultado", "Resultado")
CAMPOS = tuple(k for k, _ in SIMPLES + HORMONAL + ONCOLOGICA + (RESULTADO,))
TECNICA = "Coloración de Papanicolaou"


def resultado_de(micro):
    return _texto(micro, "resultado") or _texto(micro, "bethesda")


def tiene_estructura(micro):
    return any(_texto(micro, k) for k in CAMPOS)


def hallazgos(micro):
    def filas(campos):
        return [(rotulo, _texto(micro, k)) for k, rotulo in campos if _texto(micro, k)]
    bloques = [("", [("Técnica", TECNICA)] + filas(SIMPLES)), ("Citología hormonal", filas(HORMONAL)), ("Citología oncológica", filas(ONCOLOGICA))]
    return [{"titulo": t, "filas": f} for t, f in bloques if f]


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
    micro_pap = True
    lote_por_citotecnico = True
    lotes = ["PAPURG"]

    def requisito(self, etapa, macro, micro, ihq):
        if etapa == "microscopia":
            return None if resultado_de(micro) else "Falta el resultado."
        return super().requisito(etapa, macro, micro, ihq)


ESTUDIO = Pap()
