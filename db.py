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
CREATE INDEX IF NOT EXISTS ix_estudios_protocolo ON estudios(protocolo_id);
CREATE INDEX IF NOT EXISTS ix_estudios_lote ON estudios(lote_id);
CREATE INDEX IF NOT EXISTS ix_etapas_estudio ON etapas(estudio_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_protocolo ON auditoria(protocolo_id);
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


def auditar(usuario_id, protocolo_id, accion, detalle="", estudio_id=None):
    ex("INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, estudio_id, accion, detalle) VALUES (?,?,?,?,?,?)",
       (ahora(), usuario_id, protocolo_id, estudio_id, accion, detalle))


# ---------------------------------------------------------------- inicialización
def inicializar():
    c = _conectar()
    # versión anterior (un "caso" por tipo de estudio, solo datos de prueba): se respalda y se arranca limpio
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='casos'").fetchone():
        os.makedirs(os.path.join(DATA, "respaldos"), exist_ok=True)
        copia = sqlite3.connect(os.path.join(DATA, "respaldos", f"antes_de_protocolos_{datetime.now():%Y%m%d_%H%M}.db"))
        c.backup(copia)
        copia.close()
        c.execute("PRAGMA foreign_keys = OFF")
        for tabla in ("ihq", "micro", "macro", "etapas", "casos", "lotes", "auditoria"):
            c.execute(f"DROP TABLE IF EXISTS {tabla}")
        c.commit()
        c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
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
