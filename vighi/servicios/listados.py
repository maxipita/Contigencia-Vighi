from vighi.servicios.protocolos import limpiar_valor, sin_repetidos


LISTADOS = {"tecnicas_especiales": ("Técnicas especiales", "Se tildan al agregar un estudio (biopsias y citologías) y se pueden elegir al informar la microscopía."),
            "ihq_marcadores": ("Marcadores de IHQ", "Se eligen al cargar la IHQ de una biopsia, cuando el diagnóstico la solicita.")}


def limpiar_listado(texto):
    return sin_repetidos(limpiar_valor(linea) for linea in (texto or "").splitlines())
