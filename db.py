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
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciales VARCHAR(10) NOT NULL UNIQUE,
    nombre VARCHAR(100),
    sectores VARCHAR(200) NOT NULL DEFAULT '',
    admin INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    clave_hash VARCHAR(255),
    debe_cambiar_clave INTEGER NOT NULL DEFAULT 1
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
CREATE TABLE IF NOT EXISTS casos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo VARCHAR(3) NOT NULL,
    protocolo VARCHAR(30) NOT NULL,
    lote VARCHAR(40), tipo_lote VARCHAR(20), n_lote INTEGER,
    lote_id INTEGER REFERENCES lotes(id),
    fecha_recoleccion VARCHAR(10),
    dni VARCHAR(20), cobertura VARCHAR(40), n_afiliado VARCHAR(40),
    nombre VARCHAR(80), apellido VARCHAR(80), sexo VARCHAR(10), exento VARCHAR(3),
    fecha_nacimiento VARCHAR(10), email VARCHAR(120), telefono VARCHAR(40),
    medico VARCHAR(120), lugar_recoleccion VARCHAR(120), lugar_entrega VARCHAR(120),
    categoria VARCHAR(40), subcategoria VARCHAR(60), sitio VARCHAR(80), tipo_muestra VARCHAR(80),
    cantidad INTEGER, citologia_hormonal VARCHAR(3),
    responsable_id INTEGER REFERENCES usuarios(id),
    observaciones TEXT,
    protocolo_sistema VARCHAR(40), cargado_sistema INTEGER NOT NULL DEFAULT 0,
    anulado INTEGER NOT NULL DEFAULT 0,
    borrador INTEGER NOT NULL DEFAULT 0,             -- 1 = protocolo generado desde Recepción, faltan los datos del paciente
    etiqueta_lote_id INTEGER,                        -- lote de etiquetas de Recepción que lo generó (etiquetas_lotes)
    lab_etiquetado_en VARCHAR(19),                   -- cuándo se imprimieron sus etiquetas de laboratorio
    creado_por INTEGER REFERENCES usuarios(id), creado_en VARCHAR(19),
    UNIQUE (tipo, protocolo)
);
CREATE TABLE IF NOT EXISTS etapas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id INTEGER NOT NULL REFERENCES casos(id),
    etapa VARCHAR(30) NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    fecha_hora VARCHAR(19) NOT NULL,
    UNIQUE (caso_id, etapa)
);
CREATE TABLE IF NOT EXISTS macro (
    caso_id INTEGER PRIMARY KEY REFERENCES casos(id),
    template VARCHAR(120), descripcion TEXT, cassettes INTEGER
);
CREATE TABLE IF NOT EXISTS micro (
    caso_id INTEGER PRIMARY KEY REFERENCES casos(id),
    template VARCHAR(120), descripcion TEXT, conclusion TEXT,
    bethesda VARCHAR(40), tecnicas_especiales VARCHAR(200), solicita_ihq INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ihq (
    caso_id INTEGER PRIMARY KEY REFERENCES casos(id),
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
    fecha_hora VARCHAR(19) NOT NULL, usuario_id INTEGER, caso_id INTEGER,
    accion VARCHAR(40) NOT NULL, detalle TEXT
);
CREATE TABLE IF NOT EXISTS feriados (fecha VARCHAR(10) PRIMARY KEY, descripcion VARCHAR(100));
CREATE INDEX IF NOT EXISTS ix_etapas_caso ON etapas(caso_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_caso ON auditoria(caso_id);
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


def auditar(usuario_id, caso_id, accion, detalle=""):
    ex("INSERT INTO auditoria (fecha_hora, usuario_id, caso_id, accion, detalle) VALUES (?,?,?,?,?)",
       (ahora(), usuario_id, caso_id, accion, detalle))


# ---------------------------------------------------------------- inicialización
def inicializar():
    c = _conectar()
    c.executescript(SCHEMA)
    # migraciones de bases creadas con versiones anteriores
    columnas = {r["name"] for r in c.execute("PRAGMA table_info(casos)")}
    if "lote_id" not in columnas:
        c.execute("ALTER TABLE casos ADD COLUMN lote_id INTEGER REFERENCES lotes(id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_casos_lote ON casos(lote_id)")
    for col, definicion in (('borrador', 'INTEGER NOT NULL DEFAULT 0'), ('etiqueta_lote_id', 'INTEGER'),
                            ('lab_etiquetado_en', 'VARCHAR(19)')):
        if col not in columnas:
            c.execute(f"ALTER TABLE casos ADD COLUMN {col} {definicion}")
    c.execute("CREATE INDEX IF NOT EXISTS ix_casos_borrador ON casos(borrador)")
    # lotes de la versión anterior (solo texto "TIPO-MMDD.N") -> lotes reales
    for caso_id, texto, creado_en in c.execute(
            "SELECT id, lote, creado_en FROM casos WHERE lote_id IS NULL AND lote LIKE '%-____.%'").fetchall():
        tipo_lote, _, resto = texto.rpartition("-")
        mmdd, _, numero = resto.partition(".")
        if not (tipo_lote and mmdd.isdigit() and len(mmdd) == 4 and numero.isdigit()):
            continue
        fecha = f"{(creado_en or ahora())[:4]}-{mmdd[:2]}-{mmdd[2:]}"
        fila = c.execute("SELECT id FROM lotes WHERE codigo=?", (texto,)).fetchone()
        if fila:
            lote_id = fila["id"]
        else:
            lote_id = c.execute("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_en) VALUES (?,?,?,?,?)",
                                (texto, tipo_lote, fecha, int(numero), creado_en or ahora())).lastrowid
        c.execute("UPDATE casos SET lote_id=? WHERE id=?", (lote_id, caso_id))
    seed = os.path.join(BASE, "seed")

    def cargar(nombre):
        with open(os.path.join(seed, nombre), encoding="utf-8") as f:
            return json.load(f)

    if not c.execute("SELECT 1 FROM feriados LIMIT 1").fetchone():
        from trazabilidad import FERIADOS_2026
        c.executemany("INSERT INTO feriados VALUES (?,?)", FERIADOS_2026)
    if not c.execute("SELECT 1 FROM catalogo LIMIT 1").fetchone():
        c.executemany("INSERT INTO catalogo VALUES (?,?,?,?,?)",
                      [(x["tipo"], x["categoria"], x["subcategoria"], x["sitio"], x["tipo_muestra"])
                       for x in cargar("catalogo.json")])
    if not c.execute("SELECT 1 FROM listas LIMIT 1").fetchone():
        c.executemany("INSERT INTO listas VALUES (?,?,?)",
                      [(n, i, v) for n, vals in cargar("listas.json").items() for i, v in enumerate(vals)])
    if not c.execute("SELECT 1 FROM templates LIMIT 1").fetchone():
        for clase in ("macro", "micro"):
            c.executemany("INSERT INTO templates (clase, titulo, tipo_biopsia, texto, conclusion) VALUES (?,?,?,?,?)",
                          [(t["clase"], t["titulo"], t["tipo_biopsia"], t["texto"], t["conclusion"])
                           for t in cargar(f"templates_{clase}.json")])
    if not c.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
        c.executemany("INSERT INTO usuarios (iniciales, nombre, sectores) VALUES (?,?,?)",
                      [(u["iniciales"], u["iniciales"], ",".join(u["sectores"])) for u in cargar("usuarios.json")])
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
      lote abierto del día. borradores = {estudio, tipo_lote, fecha_lote, fecha_rec, responsable_id, protocolos}.
    - Laboratorio: marca como etiquetados los casos (etiquetados = ids).
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
            ya = {r["protocolo"] for r in c.execute("SELECT protocolo FROM casos WHERE tipo=? AND protocolo LIKE 'C%'",
                                                    (borradores["estudio"],))}
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
            est = borradores["estudio"]
            c.executemany(
                "INSERT INTO casos (tipo, protocolo, lote, lote_id, fecha_recoleccion, categoria, subcategoria, sitio, "
                "responsable_id, borrador, etiqueta_lote_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?)",
                [(est, p, lote["codigo"], lote["id"], borradores["fecha_rec"], "Biopsias" if est == "BP" else "Citologías",
                  "Ginecológica" if est == "PAP" else None, "Vagina" if est == "PAP" else None,
                  borradores["responsable_id"], nuevo, usuario_id, ahora()) for p in borradores["protocolos"]])
        if etiquetados:
            c.execute(f"UPDATE casos SET lab_etiquetado_en=? WHERE id IN ({','.join('?' * len(etiquetados))})",
                      [ahora()] + list(etiquetados))
        c.commit()
        return {"id": nuevo, "lote": lote}
    except Exception:
        c.rollback()
        raise
