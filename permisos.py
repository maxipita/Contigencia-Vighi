"""Permisos del sistema y perfiles iniciales.

Cada usuario tiene un perfil (conjunto de permisos) y, si hace falta, ajustes propios: permisos que se le suman o
se le quitan respecto de su perfil. El administrador puede todo. Las etapas, además del permiso "etapas", las marca
solo el sector que las realiza (ver marcar_listo en app.py)."""

# clave -> (grupo, descripción). El orden es el de la pantalla.
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

# Perfiles con los que arranca el sistema (después se editan desde Administración > Perfiles).
# El sector de cada usuario existente define con qué perfil arranca.
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
    """Permisos que tiene un usuario: los de su perfil más los sumados, menos los quitados. El admin, todos."""
    if usuario["admin"]:
        return set(PERMISOS)
    return (lista(perfil_permisos) | lista(usuario["permisos_mas"])) - lista(usuario["permisos_menos"])


def perfil_por_sectores(sectores, perfiles):
    """Perfil inicial para un usuario existente: el de su primer sector. perfiles = {nombre: (id, sector, permisos)}.
    Devuelve (perfil_id, permisos a sumar por sus otros sectores)."""
    por_sector = {sector: (pid, permisos) for pid, sector, permisos in perfiles.values()}
    suyos = [s for s in (sectores or "").split(",") if s in por_sector]
    if not suyos:
        return None, set()
    pid, base = por_sector[suyos[0]]
    extra = set().union(*(por_sector[s][1] for s in suyos[1:])) - base if len(suyos) > 1 else set()
    return pid, extra
