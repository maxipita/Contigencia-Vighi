SECTORES = {
    "ingreso": "Ingreso",
    "laboratorio": "Laboratorio",
    "macroscopia": "Macroscopía",
    "traslados": "Traslados",
    "citotecnico": "Citotécnicos",
    "firmante": "Médicos firmantes",
}

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
    clave = ""
    nombre = ""
    categoria = ""
    pasos = []
    pasos_ihq = []
    plazos = {}
    secciones = ["micro"]
    sector_responsable = "citotecnico"
    etiqueta_responsable = "Citotécnico responsable"
    cantidades = [str(n) for n in range(1, 11)]
    etiqueta_cantidad = "vidrios"
    subcategoria_fija = None
    sitio_fijo = None
    citologia_hormonal = False
    bethesda = False
    lotes = []
    lote_por_citotecnico = False

    def flujo(self, solicita_ihq=False):
        claves = self.pasos + (self.pasos_ihq if solicita_ihq else [])
        return [(k, ETAPAS[k][0], ETAPAS[k][1]) for k in claves]

    def estado(self, hechas, solicita_ihq=False, anulado=False):
        if anulado:
            return "ANULADO", None
        for paso in self.flujo(solicita_ihq):
            if paso[0] not in hechas:
                return f"Pend. {paso[1]}", paso
        return ("INFORMADO (con IHQ)" if solicita_ihq else "INFORMADO"), None

    def ultima_etapa(self, solicita_ihq=False):
        return self.flujo(solicita_ihq)[-1][0]

    def requisito(self, etapa, macro, micro, ihq):
        if etapa == "macroscopia" and not _texto(macro, "descripcion"):
            return "Falta la descripción macroscópica."
        if etapa == "microscopia" and not (_texto(micro, "descripcion") or _texto(micro, "conclusion")):
            return "Falta el diagnóstico (descripción o conclusión)."
        if etapa == "interp_ihq" and not _texto(ihq, "resultado"):
            return "Falta el resultado de la IHQ."
        return None

    def tipos_lote(self, fijos, citotecnicos):
        if self.lote_por_citotecnico:
            return list(citotecnicos)
        return [t for t in fijos if t in self.lotes]
