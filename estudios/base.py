"""Piezas comunes a todos los tipos de estudio: sectores, etapas y la clase que describe un tipo.
Cada tipo (PAP, BP, CT) vive en su propio módulo y se registra en estudios/__init__.py."""

SECTORES = {
    "ingreso": "Ingreso",
    "laboratorio": "Laboratorio",
    "macroscopia": "Macroscopía",
    "traslados": "Traslados",
    "citotecnico": "Citotécnicos",
    "firmante": "Médicos firmantes",
}

# etapa -> (nombre, sector que la realiza, proceso, actividad, acción) — los tres últimos como los muestra
# la trazabilidad de southernbits
ETAPAS = {
    "ingreso": ("Ingreso", "ingreso", "INGRESO", "Cargar protocolo", "Protocolo > Cargar"),
    "macroscopia": ("Macroscopía", "macroscopia", "DIAGNÓSTICOS", "Macroscopía", "Macro > Informar"),
    "procesamiento": ("Procesamiento", "laboratorio", "LABORATORIO", "Procesamiento", "Histo > Procesar"),
    "inclusion": ("Inclusión", "laboratorio", "LABORATORIO", "Inclusión", "Cassette > Incluir"),
    "corte": ("Corte PH", "laboratorio", "LABORATORIO", "Corte PH", "Taco > Cortar"),
    "coloreado": ("Coloreado", "laboratorio", "LABORATORIO", "Coloreado", "Porta > Colorear"),
    "citotecnicos": ("Citotécnicos", "traslados", "TRASLADOS", "Citotécnicos", "Cito > Informar"),
    "microscopia": ("Microscopía", "firmante", "DIAGNÓSTICOS", "Microscopía", "Micro > Informar"),
    "corte_ihq": ("Corte IHQ", "laboratorio", "LABORATORIO", "Corte PH", "Taco IHQ > Cortar"),
    "envio_ihq": ("Envío lab. externo", "traslados", "TRASLADOS", "Laboratorio", "Lab Ext > Procesar"),
    "proc_ihq": ("Procesamiento IHQ", "laboratorio", "LABORATORIO", "Procesamiento", "IHQ > Procesar"),
    "interp_ihq": ("Interpretación IHQ", "firmante", "DIAGNÓSTICOS", "Microscopía", "Micro > Interpretar"),
}
NOMBRE_ETAPA = {k: v[0] for k, v in ETAPAS.items()}
GINECOLOGICA = "Ginecológica"


def _texto(fila, campo):
    return ((fila[campo] if fila else "") or "").strip()


class Estudio:
    """Describe un tipo de estudio. Los módulos pap.py, bp.py y ct.py crean una instancia cada uno."""
    clave = ""                     # PAP, BP, CT
    nombre = ""                    # como se muestra
    categoria = ""                 # Biopsias / Citologías
    pasos = []                     # claves de ETAPAS, en orden (sin el ingreso)
    pasos_ihq = []                 # se agregan si el médico solicita IHQ
    plazos = {}                    # etapa -> (días hábiles desde la recolección, hora límite)
    secciones = ["micro"]          # partes de la ficha: macro, micro, ihq
    sector_responsable = "citotecnico"
    etiqueta_responsable = "Citotécnico responsable"
    cantidades = [str(n) for n in range(1, 11)]
    etiqueta_cantidad = "vidrios"
    subcategoria_fija = None       # si el tipo siempre es de la misma subcategoría / sitio
    sitio_fijo = None
    citologia_hormonal = False     # pregunta propia del PAP
    bethesda = False               # el diagnóstico lleva resultado Bethesda (PAP)
    lotes = []                     # tipos de lote fijos que le corresponden
    lote_por_citotecnico = False   # lote con las iniciales del citotécnico (PAP)

    def flujo(self, solicita_ihq=False):
        """[(clave, nombre, sector)] de las etapas del estudio."""
        claves = self.pasos + (self.pasos_ihq if solicita_ihq else [])
        return [(k, ETAPAS[k][0], ETAPAS[k][1]) for k in claves]

    def estado(self, hechas, solicita_ihq=False, anulado=False):
        """(texto de estado, próxima etapa o None)."""
        if anulado:
            return "ANULADO", None
        for paso in self.flujo(solicita_ihq):
            if paso[0] not in hechas:
                return f"Pend. {paso[1]}", paso
        return ("INFORMADO (con IHQ)" if solicita_ihq else "INFORMADO"), None

    def ultima_etapa(self, solicita_ihq=False):
        return self.flujo(solicita_ihq)[-1][0]

    def requisito(self, etapa, macro, micro, ihq):
        """Qué tiene que estar cargado antes de completar la etapa (None = nada)."""
        if etapa == "macroscopia" and not _texto(macro, "descripcion"):
            return "Falta la descripción macroscópica."
        if etapa == "microscopia" and not (_texto(micro, "descripcion") or _texto(micro, "conclusion")):
            return "Falta el diagnóstico (descripción o conclusión)."
        if etapa == "interp_ihq" and not _texto(ihq, "resultado"):
            return "Falta el resultado de la IHQ."
        return None

    def tipos_lote(self, fijos, citotecnicos):
        """Tipos de lote que se pueden elegir para este estudio."""
        if self.lote_por_citotecnico:
            return list(citotecnicos)
        return [t for t in fijos if t in self.lotes]
