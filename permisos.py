PERMISOS = {
    "protocolo_crear": ("Ingreso", "Crear y completar protocolos"),
    "protocolo_editar": ("Ingreso", "Editar protocolos y estudios, agregar estudios"),
    "estudio_anular": ("Ingreso", "Anular y reactivar estudios"),
    "sistema": ("Ingreso", "Marcar \"cargado en sistema\""),
    "etiquetas_recepcion": ("Etiquetas", "Recepción (genera numeración y protocolos)"),
    "etiquetas_lab": ("Etiquetas", "Laboratorio (PAP y BP)"),
    "lotes_armar": ("Lotes", "Armar lotes (crear, agregar, quitar, observaciones)"),
    "lotes_cerrar": ("Lotes", "Cerrar, reabrir y eliminar lotes"),
    "macro": ("Diagnóstico", "Cargar macroscopía"),
    "micro": ("Diagnóstico", "Cargar microscopía e IHQ"),
    "informe": ("Diagnóstico", "Generar informes en PDF (llevan la firma del médico)"),
    "etapas": ("Etapas", "Marcar etapas como listas (las de su sector)"),
    "etapas_deshacer": ("Etapas", "Deshacer etapas registradas por otros"),
    "exportar": ("Consultas", "Exportar a Excel"),
    "feriados": ("Administración", "Feriados"),
}

GRUPOS = list(dict.fromkeys(g for g, _ in PERMISOS.values()))

PERFILES_INICIALES = {
    "Ingreso": ("ingreso", ["protocolo_crear", "protocolo_editar", "estudio_anular", "sistema", "etiquetas_recepcion",
                            "lotes_armar", "etapas", "exportar"]),
    "Laboratorio": ("laboratorio", ["etiquetas_lab", "lotes_armar", "lotes_cerrar", "etapas"]),
    "Macroscopía": ("macroscopia", ["macro", "lotes_armar", "etapas"]),
    "Traslados": ("traslados", ["etapas"]),
    "Citotécnico": ("citotecnico", ["etiquetas_lab", "lotes_armar", "etapas"]),
    "Médico firmante": ("firmante", ["micro", "informe", "etapas", "exportar"]),
}


def lista(texto):
    return {p for p in (texto or "").split(",") if p in PERMISOS}


def texto(conjunto):
    return ",".join(p for p in PERMISOS if p in conjunto)


def efectivos(usuario, perfil_permisos):
    if usuario["admin"]:
        return set(PERMISOS)
    return (lista(perfil_permisos) | lista(usuario["permisos_mas"])) - lista(usuario["permisos_menos"])


def perfil_por_sectores(sectores, perfiles):
    por_sector = {sector: (pid, permisos) for pid, sector, permisos in perfiles.values()}
    suyos = [s for s in (sectores or "").split(",") if s in por_sector]
    if not suyos:
        return None, set()
    pid, base = por_sector[suyos[0]]
    extra = set().union(*(por_sector[s][1] for s in suyos[1:])) - base if len(suyos) > 1 else set()
    return pid, extra
