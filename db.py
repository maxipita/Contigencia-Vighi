"""Acceso a datos. Todo el SQL de la app pasa por acá (SQL estándar) para poder migrar a MySQL
cambiando solo este módulo: conexión, placeholders (? -> %s) y los tipos del esquema."""
import json
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime

from flask import g

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
DB_PATH = os.environ.get("CONTINGENCIA_DB", os.path.join(DATA, "contingencia.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS perfiles (           -- conjunto de permisos que se asigna a los usuarios (permisos.py)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre VARCHAR(60) NOT NULL UNIQUE,
    permisos VARCHAR(500) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciales VARCHAR(10) NOT NULL UNIQUE,
    nombre VARCHAR(100),
    sectores VARCHAR(200) NOT NULL DEFAULT '',
    admin INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    clave_hash VARCHAR(255),
    debe_cambiar_clave INTEGER NOT NULL DEFAULT 1,
    perfil_id INTEGER REFERENCES perfiles(id),
    permisos_mas VARCHAR(500) NOT NULL DEFAULT '',      -- permisos que se le suman a su perfil (claves separadas por coma)
    permisos_menos VARCHAR(500) NOT NULL DEFAULT ''     -- permisos que se le quitan a su perfil
);
CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo VARCHAR(40) NOT NULL UNIQUE,          -- TIPO-MMDD.N, ej. ONCO-0930.2
    tipo_lote VARCHAR(20) NOT NULL,
    fecha VARCHAR(10) NOT NULL,                  -- YYYY-MM-DD
    numero INTEGER NOT NULL,
    cerrado INTEGER NOT NULL DEFAULT 0,
    observaciones TEXT,
    creado_por INTEGER REFERENCES usuarios(id), creado_en VARCHAR(19),
    cerrado_por INTEGER REFERENCES usuarios(id), cerrado_en VARCHAR(19),
    UNIQUE (tipo_lote, fecha, numero)
);
CREATE TABLE IF NOT EXISTS protocolos (         -- un paciente / una solicitud: datos que comparten sus estudios
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero VARCHAR(30) NOT NULL UNIQUE,
    fecha_recoleccion VARCHAR(10),
    dni VARCHAR(20), cobertura VARCHAR(80), n_afiliado VARCHAR(40),
    nombre VARCHAR(80), apellido VARCHAR(80), sexo VARCHAR(10), exento VARCHAR(3),
    fecha_nacimiento VARCHAR(10), email VARCHAR(120), telefono VARCHAR(40),
    medico VARCHAR(150), lugar_recoleccion VARCHAR(120), lugar_entrega VARCHAR(120),
    observaciones TEXT,
    protocolo_sistema VARCHAR(40), cargado_sistema INTEGER NOT NULL DEFAULT 0,
    borrador INTEGER NOT NULL DEFAULT 0,             -- 1 = generado desde Recepción (etiquetas), faltan los datos del paciente
    etiqueta_lote_id INTEGER,                        -- lote de etiquetas de Recepción que lo generó (etiquetas_lotes)
    creado_por INTEGER REFERENCES usuarios(id), creado_en VARCHAR(19)
);
CREATE TABLE IF NOT EXISTS estudios (           -- PAP / BP / CT de un protocolo, cada uno con su flujo
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo_id INTEGER NOT NULL REFERENCES protocolos(id),
    tipo VARCHAR(3) NOT NULL,
    categoria VARCHAR(40), subcategoria VARCHAR(60), sitio VARCHAR(80), tipo_muestra VARCHAR(80),
    cantidad VARCHAR(5), citologia_hormonal VARCHAR(3), observaciones TEXT,
    responsable_id INTEGER REFERENCES usuarios(id),
    lote_id INTEGER REFERENCES lotes(id),
    anulado INTEGER NOT NULL DEFAULT 0, motivo_anulacion VARCHAR(200),
    lab_etiquetado_en VARCHAR(19),                   -- cuándo se imprimieron sus etiquetas de laboratorio
    creado_por INTEGER REFERENCES usuarios(id), creado_en VARCHAR(19)
);
CREATE TABLE IF NOT EXISTS etapas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estudio_id INTEGER NOT NULL REFERENCES estudios(id),
    etapa VARCHAR(30) NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    fecha_hora VARCHAR(19) NOT NULL,
    UNIQUE (estudio_id, etapa)
);
CREATE TABLE IF NOT EXISTS macro (
    estudio_id INTEGER PRIMARY KEY REFERENCES estudios(id),
    template VARCHAR(120), descripcion TEXT, cassettes INTEGER
);
CREATE TABLE IF NOT EXISTS micro (
    estudio_id INTEGER PRIMARY KEY REFERENCES estudios(id),
    template VARCHAR(120), descripcion TEXT, conclusion TEXT,
    bethesda VARCHAR(40), tecnicas_especiales VARCHAR(200), solicita_ihq INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ihq (
    estudio_id INTEGER PRIMARY KEY REFERENCES estudios(id),
    marcadores TEXT, resultado TEXT
);
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clase VARCHAR(10) NOT NULL, titulo VARCHAR(120) NOT NULL, tipo_biopsia VARCHAR(40),
    texto TEXT, conclusion TEXT,
    UNIQUE (clase, titulo)
);
CREATE TABLE IF NOT EXISTS catalogo (
    tipo VARCHAR(3) NOT NULL, categoria VARCHAR(40), subcategoria VARCHAR(60),
    sitio VARCHAR(80), tipo_muestra VARCHAR(80)
);
CREATE TABLE IF NOT EXISTS listas (nombre VARCHAR(30) NOT NULL, orden INTEGER, valor VARCHAR(80));
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora VARCHAR(19) NOT NULL, usuario_id INTEGER, protocolo_id INTEGER, estudio_id INTEGER,
    accion VARCHAR(40) NOT NULL, detalle TEXT
);
CREATE TABLE IF NOT EXISTS feriados (fecha VARCHAR(10) PRIMARY KEY, descripcion VARCHAR(100));
CREATE TABLE IF NOT EXISTS medicos (id INTEGER PRIMARY KEY, nombre VARCHAR(150) NOT NULL);
-- firma de cada médico para los informes en PDF (PNG). Va en una tabla aparte para no cargarla en cada consulta de usuarios.
CREATE TABLE IF NOT EXISTS firmas (usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id), imagen BLOB NOT NULL, actualizada_en VARCHAR(19));
-- Informe en PDF emitido de cada PROTOCOLO (junta todos sus estudios): se guarda tal como salió (al volver a verlo no se rearma). Una sola
-- fila por protocolo: generarlo de nuevo reemplaza el PDF anterior para no acumular archivos (la constancia de cada generación queda en
-- auditoria). version = cuántas veces se generó. usuario_id = quien lo generó la última vez; firmante_id = el médico que lleva la firma.
CREATE TABLE IF NOT EXISTS informes_emitidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo_id INTEGER NOT NULL REFERENCES protocolos(id), version INTEGER NOT NULL,
    usuario_id INTEGER, firmante_id INTEGER, creado_en VARCHAR(19) NOT NULL,
    comentario TEXT, archivo VARCHAR(120), pdf BLOB NOT NULL,
    estudios VARCHAR(500)              -- ids de los estudios que incluye (si cambian, el informe deja de valer)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_informes_protocolo ON informes_emitidos(protocolo_id);
CREATE INDEX IF NOT EXISTS ix_estudios_protocolo ON estudios(protocolo_id);
CREATE INDEX IF NOT EXISTS ix_estudios_lote ON estudios(lote_id);
CREATE INDEX IF NOT EXISTS ix_etapas_estudio ON etapas(estudio_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_protocolo ON auditoria(protocolo_id);
-- Lotes de etiquetas confirmados (generador de etiquetas). tipo: bp = Recepción, pap = PAP-Laboratorio,
-- lab = BP-Laboratorio. desde/hasta = rango de números C000001...; quedan en NULL cuando las etiquetas
-- salen de un lote del sistema (lote_id) con sus protocolos reales.
CREATE TABLE IF NOT EXISTS etiquetas_lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo VARCHAR(10) NOT NULL,
    desde INTEGER, hasta INTEGER,
    lote_id INTEGER REFERENCES lotes(id),
    n INTEGER NOT NULL, por_proto INTEGER NOT NULL, etiquetas INTEGER NOT NULL,
    params TEXT NOT NULL,                         -- JSON con lo confirmado, para poder reimprimir igual
    creado_por INTEGER REFERENCES usuarios(id), creado_en VARCHAR(19) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_etiquetas_tipo ON etiquetas_lotes(tipo, desde);
"""


IntegrityError = sqlite3.IntegrityError      # app.py no importa el motor: captura esta excepción cuando una restricción falla


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conectar():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")      # varios usuarios leyendo mientras uno escribe
    return con


def con():
    if "db" not in g:
        g.db = _conectar()
    return g.db


def cerrar(_=None):
    c = g.pop("db", None)
    if c is not None:
        c.close()


def q(sql, params=()):
    return con().execute(sql, params).fetchall()


def uno(sql, params=()):
    return con().execute(sql, params).fetchone()


def ex(sql, params=()):
    c = con()
    cur = c.execute(sql, params)
    c.commit()
    return cur.lastrowid


def feriados():
    from datetime import date
    return {date.fromisoformat(r["fecha"]) for r in q("SELECT fecha FROM feriados")}


def auditar(usuario_id, protocolo_id, accion, detalle="", estudio_id=None):
    ex("INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, estudio_id, accion, detalle) VALUES (?,?,?,?,?,?)",
       (ahora(), usuario_id, protocolo_id, estudio_id, accion, detalle))


# ---------------------------------------------------------------- inicialización
def unificar_etapas(c):
    """El flujo (etapas) es de cada TIPO de estudio dentro del protocolo, no de cada estudio: los estudios activos del mismo tipo comparten
    etapas (la app las marca en todos a la vez). Si una base vieja los tiene desparejos, queda lo que tienen todos en común: así no se da por
    hecha una etapa que a alguno le falta. Con datos ya parejos no hace nada."""
    grupos = {}
    for r in c.execute("SELECT id, protocolo_id, tipo FROM estudios WHERE anulado=0 ORDER BY id"):
        grupos.setdefault((r["protocolo_id"], r["tipo"]), []).append(r["id"])
    hechas = {}
    for r in c.execute("SELECT estudio_id, etapa FROM etapas"):
        hechas.setdefault(r["estudio_id"], set()).add(r["etapa"])
    for ids in grupos.values():
        if len(ids) < 2:
            continue
        comun = set.intersection(*(hechas.get(i, set()) for i in ids))
        for i in ids:
            for etapa in hechas.get(i, set()) - comun:
                c.execute("DELETE FROM etapas WHERE estudio_id=? AND etapa=?", (i, etapa))
    c.commit()


def inicializar():
    c = _conectar()
    # versión anterior (un "caso" por tipo de estudio, solo datos de prueba): se respalda y se arranca limpio
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='casos'").fetchone():
        os.makedirs(os.path.join(DATA, "respaldos"), exist_ok=True)
        copia = sqlite3.connect(os.path.join(DATA, "respaldos", f"antes_de_protocolos_{datetime.now():%Y%m%d_%H%M}.db"))
        c.backup(copia)
        copia.close()
        c.execute("PRAGMA foreign_keys = OFF")
        for tabla in ("ihq", "micro", "macro", "etapas", "casos", "etiquetas_lotes", "lotes", "auditoria"):
            c.execute(f"DROP TABLE IF EXISTS {tabla}")
        c.commit()
        c.execute("PRAGMA foreign_keys = ON")
    vieja = [r["name"] for r in c.execute("PRAGMA table_info(informes_emitidos)")]
    if vieja and "protocolo_id" not in vieja:
        # el informe se guardaba por estudio: pasa a ser uno por protocolo (queda el último de cada uno)
        c.execute("DROP INDEX IF EXISTS ux_informes_estudio_version")
        c.execute("DROP INDEX IF EXISTS ux_informes_estudio")
        c.execute("ALTER TABLE informes_emitidos RENAME TO informes_por_estudio")
        c.executescript(SCHEMA)
        c.execute("""INSERT INTO informes_emitidos (protocolo_id, version, usuario_id, firmante_id, creado_en, comentario, archivo, pdf)
                     SELECT e.protocolo_id, i.version, i.usuario_id, i.firmante_id, i.creado_en, i.comentario, i.archivo, i.pdf
                     FROM informes_por_estudio i JOIN estudios e ON e.id=i.estudio_id
                     WHERE i.id IN (SELECT MAX(i2.id) FROM informes_por_estudio i2 JOIN estudios e2 ON e2.id=i2.estudio_id GROUP BY e2.protocolo_id)""")
        c.execute("DROP TABLE informes_por_estudio")
        c.commit()
    c.executescript(SCHEMA)
    # columnas sumadas después de crear la tabla
    cols = lambda t: {r["name"] for r in c.execute(f"PRAGMA table_info({t})")}
    antes_de_informes = "titulo" not in cols("usuarios")      # primera vez que arranca con los informes en PDF
    for tabla, col, definicion in (("usuarios", "perfil_id", "INTEGER REFERENCES perfiles(id)"),
                                   ("usuarios", "permisos_mas", "VARCHAR(500) NOT NULL DEFAULT ''"),
                                   ("usuarios", "permisos_menos", "VARCHAR(500) NOT NULL DEFAULT ''"),
                                   ("usuarios", "titulo", "VARCHAR(10)"),           # Dr. / Dra. (informes en PDF)
                                   ("usuarios", "mn", "VARCHAR(20)"),               # matrícula nacional
                                   ("usuarios", "mp", "VARCHAR(20)"),               # matrícula provincial
                                   ("protocolos", "borrador", "INTEGER NOT NULL DEFAULT 0"),
                                   ("protocolos", "etiqueta_lote_id", "INTEGER"),
                                   ("informes_emitidos", "estudios", "VARCHAR(500)"),
                                   ("protocolos", "firmante_id", "INTEGER"),        # quien pasó a su nombre la firma del informe (si no, firma el responsable)
                                   ("estudios", "lab_etiquetado_en", "VARCHAR(19)")):
        if col not in cols(tabla):
            c.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {definicion}")
    c.execute("CREATE INDEX IF NOT EXISTS ix_protocolos_borrador ON protocolos(borrador)")
    unificar_etapas(c)
    if antes_de_informes:
        # Una sola vez, al actualizar: el perfil de los médicos firmantes ya existente recibe el permiso nuevo de generar informes.
        # Después se administra desde Perfiles (si alguien se lo quita, no se vuelve a agregar).
        c.execute("UPDATE perfiles SET permisos = CASE WHEN permisos = '' THEN 'informe' ELSE permisos || ',informe' END "
                  "WHERE nombre = 'Médico firmante' AND (',' || permisos || ',') NOT LIKE '%,informe,%'")
    seed = os.path.join(BASE, "seed")

    def cargar(nombre):
        with open(os.path.join(seed, nombre), encoding="utf-8") as f:
            return json.load(f)

    if not c.execute("SELECT 1 FROM feriados LIMIT 1").fetchone():
        from trazabilidad import FERIADOS_2026
        c.executemany("INSERT INTO feriados VALUES (?,?)", FERIADOS_2026)
    if not c.execute("SELECT 1 FROM medicos LIMIT 1").fetchone() and os.path.exists(os.path.join(seed, "medicos.json")):
        c.executemany("INSERT INTO medicos (id, nombre) VALUES (?,?)", [(m["id"], m["nombre"]) for m in cargar("medicos.json")])
    if not c.execute("SELECT 1 FROM catalogo LIMIT 1").fetchone():
        c.executemany("INSERT INTO catalogo VALUES (?,?,?,?,?)",
                      [(x["tipo"], x["categoria"], x["subcategoria"], x["sitio"], x["tipo_muestra"])
                       for x in cargar("catalogo.json")])
    if not c.execute("SELECT 1 FROM listas LIMIT 1").fetchone():
        c.executemany("INSERT INTO listas VALUES (?,?,?)",
                      [(n, i, v) for n, vals in cargar("listas.json").items() for i, v in enumerate(vals)])
    # coberturas: reemplaza la lista genérica inicial (Particular / Obra Social / Prepaga) por las del sistema
    actuales = [r[0] for r in c.execute("SELECT valor FROM listas WHERE nombre='cobertura' ORDER BY orden")]
    if actuales in ([], ["Particular", "Obra Social", "Prepaga"]):
        c.execute("DELETE FROM listas WHERE nombre='cobertura'")
        c.executemany("INSERT INTO listas VALUES (?,?,?)",
                      [("cobertura", i, v) for i, v in enumerate(cargar("listas.json")["cobertura"])])
    if not c.execute("SELECT 1 FROM templates LIMIT 1").fetchone():
        for clase in ("macro", "micro"):
            c.executemany("INSERT INTO templates (clase, titulo, tipo_biopsia, texto, conclusion) VALUES (?,?,?,?,?)",
                          [(t["clase"], t["titulo"], t["tipo_biopsia"], t["texto"], t["conclusion"])
                           for t in cargar(f"templates_{clase}.json")])
    if not c.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
        c.executemany("INSERT INTO usuarios (iniciales, nombre, sectores) VALUES (?,?,?)",
                      [(u["iniciales"], u["iniciales"], ",".join(u["sectores"])) for u in cargar("usuarios.json")])
    # perfiles iniciales; los usuarios que ya existen arrancan con el perfil de su sector
    if not c.execute("SELECT 1 FROM perfiles LIMIT 1").fetchone():
        import permisos
        perfiles = {}
        for nombre, (sector, lista) in permisos.PERFILES_INICIALES.items():
            pid = c.execute("INSERT INTO perfiles (nombre, permisos) VALUES (?,?)", (nombre, permisos.texto(lista))).lastrowid
            perfiles[nombre] = (pid, sector, set(lista))
        for uid, sectores in c.execute("SELECT id, sectores FROM usuarios WHERE perfil_id IS NULL").fetchall():
            pid, extra = permisos.perfil_por_sectores(sectores, perfiles)
            c.execute("UPDATE usuarios SET perfil_id=?, permisos_mas=? WHERE id=?", (pid, permisos.texto(extra), uid))
    c.commit()
    c.close()


# ---------------------------------------------------------------- respaldos
def respaldar(destinos, conservar=48):
    """Copia consistente de la base (API de backup de SQLite) a cada carpeta destino."""
    marca = datetime.now().strftime("%Y%m%d_%H%M")
    origen = sqlite3.connect(DB_PATH)
    try:
        for carpeta in destinos:
            os.makedirs(carpeta, exist_ok=True)
            archivo = os.path.join(carpeta, f"contingencia_{marca}.db")
            dst = sqlite3.connect(archivo)
            origen.backup(dst)
            dst.close()
            viejos = sorted(f for f in os.listdir(carpeta) if f.startswith("contingencia_") and f.endswith(".db"))
            for f in viejos[:-conservar]:
                os.remove(os.path.join(carpeta, f))
    finally:
        origen.close()


def iniciar_respaldos(minutos=10):
    destinos = [os.path.join(DATA, "respaldos")]
    extra = os.environ.get("CONTINGENCIA_RESPALDO")          # ej. carpeta de SharePoint sincronizada
    if extra:
        destinos.append(extra)

    def ciclo():
        while True:
            try:
                respaldar(destinos)
            except Exception as e:                            # un respaldo fallido no debe tirar la app
                print("Respaldo fallido:", e)
            time.sleep(minutos * 60)

    threading.Thread(target=ciclo, daemon=True).start()


def copiar_archivo_db(destino):
    shutil.copy2(DB_PATH, destino)


# ---------------------------------------------------------------- etiquetas
def _lote_abierto(c, tipo_lote, fecha, usuario_id):
    """Lote abierto del día para ese tipo (el último) o, si no hay, uno nuevo con el próximo número.
    Mismo criterio de código que app.crear_lote(): TIPO-MMDD.N"""
    f = c.execute("SELECT id, codigo FROM lotes WHERE tipo_lote=? AND fecha=? AND cerrado=0 ORDER BY numero DESC LIMIT 1",
                  (tipo_lote, fecha)).fetchone()
    if f:
        return {"id": f["id"], "codigo": f["codigo"], "nuevo": False}
    n = (c.execute("SELECT MAX(numero) AS m FROM lotes WHERE tipo_lote=? AND fecha=?", (tipo_lote, fecha)).fetchone()["m"] or 0) + 1
    codigo = f"{tipo_lote}-{fecha[5:7]}{fecha[8:10]}.{n}"
    lid = c.execute("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_por, creado_en) VALUES (?,?,?,?,?,?)",
                    (codigo, tipo_lote, fecha, n, usuario_id, ahora())).lastrowid
    return {"id": lid, "codigo": codigo, "nuevo": True}


def etiquetas_confirmar(tipo, grupo, desde, hasta, n, por_proto, etiquetas, params_json, usuario_id,
                        borradores=None, etiquetados=None):
    """Registra un lote de etiquetas en una sola transacción.
    - Recepción (desde/hasta): reserva el rango de números y crea los protocolos a completar (borradores) dentro del
      lote abierto del día. borradores = {estudio, categoria, subcategoria, sitio, tipo_lote, fecha_lote, fecha_rec, responsable_id, protocolos}.
    - Laboratorio: marca como etiquetados los estudios (etiquetados = ids).
    Devuelve {"id", "lote"} o {"error": "choque" | "existentes", ...}.
    Bloquea las escrituras mientras verifica e inserta, así dos PCs no pueden tomar el mismo rango a la vez.
    (BEGIN IMMEDIATE es de SQLite; en MySQL sería una transacción con SELECT ... FOR UPDATE.)"""
    c = con()
    c.execute("BEGIN IMMEDIATE")
    try:
        if desde is not None:
            marcas = ",".join("?" * len(grupo))
            choque = c.execute(f"SELECT id, tipo, desde, hasta FROM etiquetas_lotes WHERE tipo IN ({marcas}) "
                               "AND desde IS NOT NULL AND desde <= ? AND hasta >= ? ORDER BY id LIMIT 1",
                               list(grupo) + [hasta, desde]).fetchone()
            if choque:
                c.rollback()
                return {"error": "choque", "fila": dict(choque)}
        lote = None
        if borradores:
            ya = {r["numero"] for r in c.execute("SELECT numero FROM protocolos WHERE numero LIKE 'C%'")}
            repetidos = [p for p in borradores["protocolos"] if p in ya]
            if repetidos:
                c.rollback()
                return {"error": "existentes", "protocolos": repetidos, "estudio": borradores["estudio"]}
            lote = _lote_abierto(c, borradores["tipo_lote"], borradores["fecha_lote"], usuario_id)
        cur = c.execute("INSERT INTO etiquetas_lotes (tipo, desde, hasta, lote_id, n, por_proto, etiquetas, params, "
                        "creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (tipo, desde, hasta, lote["id"] if lote else None, n, por_proto, etiquetas, params_json,
                         usuario_id, ahora()))
        nuevo = cur.lastrowid
        if borradores:
            # cada número es un protocolo a completar con un estudio del tipo que corresponde al lote
            est, ahora_ = borradores["estudio"], ahora()
            for p in borradores["protocolos"]:
                pid = c.execute("INSERT INTO protocolos (numero, fecha_recoleccion, borrador, etiqueta_lote_id, creado_por, creado_en) "
                                "VALUES (?,?,1,?,?,?)", (p, borradores["fecha_rec"], nuevo, usuario_id, ahora_)).lastrowid
                c.execute("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, responsable_id, lote_id, "
                          "creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
                          (pid, est, borradores["categoria"], borradores["subcategoria"], borradores["sitio"],
                           borradores["responsable_id"], lote["id"], usuario_id, ahora_))
        if etiquetados:
            c.execute(f"UPDATE estudios SET lab_etiquetado_en=? WHERE id IN ({','.join('?' * len(etiquetados))})",
                      [ahora()] + list(etiquetados))
        c.commit()
        return {"id": nuevo, "lote": lote}
    except Exception:
        c.rollback()
        raise
