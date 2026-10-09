import json
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime

from flask import g

import d1

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
DB_PATH = os.environ.get("CONTINGENCIA_DB", os.path.join(DATA, "contingencia.db"))
MODO_D1 = os.environ.get("CONTINGENCIA_D1") == "1"
ARCHIVO_CLOUDFLARE = os.path.join(DATA, "cloudflare.env")
DESCRIPCION = "Cloudflare D1" if MODO_D1 else DB_PATH
_credenciales = {}


def credenciales_d1():
    if not _credenciales:
        valores = {k: os.environ.get(k, "") for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_D1_ID", "CLOUDFLARE_API_TOKEN")}
        if os.path.exists(ARCHIVO_CLOUDFLARE):
            with open(ARCHIVO_CLOUDFLARE, encoding="utf-8") as f:
                for linea in f:
                    clave, _, valor = linea.strip().partition("=")
                    if clave in valores and not valores[clave]:
                        valores[clave] = valor.strip().strip('"').strip("'")
        faltan = [k for k, v in valores.items() if not v]
        if faltan:
            raise RuntimeError(f"Faltan datos de Cloudflare D1: {', '.join(faltan)}. Definilos como variables de entorno o en {ARCHIVO_CLOUDFLARE}.")
        _credenciales.update(valores)
    return _credenciales

SCHEMA = """
CREATE TABLE IF NOT EXISTS perfiles (
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
    permisos_mas VARCHAR(500) NOT NULL DEFAULT '',
    permisos_menos VARCHAR(500) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo VARCHAR(40) NOT NULL UNIQUE,
    tipo_lote VARCHAR(20) NOT NULL,
    fecha VARCHAR(10) NOT NULL,
    numero INTEGER NOT NULL,
    cerrado INTEGER NOT NULL DEFAULT 0,
    observaciones TEXT,
    creado_por INTEGER REFERENCES usuarios(id), creado_en VARCHAR(19),
    cerrado_por INTEGER REFERENCES usuarios(id), cerrado_en VARCHAR(19),
    UNIQUE (tipo_lote, fecha, numero)
);
CREATE TABLE IF NOT EXISTS protocolos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero VARCHAR(30) NOT NULL UNIQUE,
    fecha_recoleccion VARCHAR(10),
    dni VARCHAR(20), cobertura VARCHAR(80), n_afiliado VARCHAR(40),
    nombre VARCHAR(80), apellido VARCHAR(80), sexo VARCHAR(10), exento VARCHAR(3),
    fecha_nacimiento VARCHAR(10), email VARCHAR(120), telefono VARCHAR(40),
    medico VARCHAR(150), lugar_recoleccion VARCHAR(120), lugar_entrega VARCHAR(120),
    observaciones TEXT,
    protocolo_sistema VARCHAR(40), cargado_sistema INTEGER NOT NULL DEFAULT 0,
    borrador INTEGER NOT NULL DEFAULT 0,
    etiqueta_lote_id INTEGER,
    creado_por INTEGER REFERENCES usuarios(id), creado_en VARCHAR(19)
);
CREATE TABLE IF NOT EXISTS estudios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo_id INTEGER NOT NULL REFERENCES protocolos(id),
    tipo VARCHAR(3) NOT NULL,
    categoria VARCHAR(40), subcategoria VARCHAR(60), sitio VARCHAR(80), tipo_muestra VARCHAR(80),
    cantidad VARCHAR(5), citologia_hormonal VARCHAR(3), observaciones TEXT,
    responsable_id INTEGER REFERENCES usuarios(id),
    lote_id INTEGER REFERENCES lotes(id),
    anulado INTEGER NOT NULL DEFAULT 0, motivo_anulacion VARCHAR(200),
    lab_etiquetado_en VARCHAR(19),
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
CREATE TABLE IF NOT EXISTS bloqueos (nombre VARCHAR(40) PRIMARY KEY, vence REAL NOT NULL);
CREATE TABLE IF NOT EXISTS firmas (usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id), imagen BLOB NOT NULL, actualizada_en VARCHAR(19));
CREATE TABLE IF NOT EXISTS informes_emitidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo_id INTEGER NOT NULL REFERENCES protocolos(id), version INTEGER NOT NULL,
    usuario_id INTEGER, firmante_id INTEGER, creado_en VARCHAR(19) NOT NULL,
    comentario TEXT, archivo VARCHAR(120), pdf BLOB NOT NULL,
    estudios VARCHAR(500)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_informes_protocolo ON informes_emitidos(protocolo_id);
CREATE INDEX IF NOT EXISTS ix_estudios_protocolo ON estudios(protocolo_id);
CREATE INDEX IF NOT EXISTS ix_estudios_lote ON estudios(lote_id);
CREATE INDEX IF NOT EXISTS ix_etapas_estudio ON etapas(estudio_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_protocolo ON auditoria(protocolo_id);
CREATE TABLE IF NOT EXISTS comentarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo_id INTEGER NOT NULL REFERENCES protocolos(id),
    usuario_id INTEGER REFERENCES usuarios(id),
    fecha_hora VARCHAR(19) NOT NULL,
    texto TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_comentarios_protocolo ON comentarios(protocolo_id);
CREATE TABLE IF NOT EXISTS etiquetas_lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo VARCHAR(10) NOT NULL,
    desde INTEGER, hasta INTEGER,
    lote_id INTEGER REFERENCES lotes(id),
    n INTEGER NOT NULL, por_proto INTEGER NOT NULL, etiquetas INTEGER NOT NULL,
    params TEXT NOT NULL,
    creado_por INTEGER REFERENCES usuarios(id), creado_en VARCHAR(19) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_etiquetas_tipo ON etiquetas_lotes(tipo, desde);
"""


IntegrityError = sqlite3.IntegrityError


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conectar():
    if MODO_D1:
        c = credenciales_d1()
        return d1.Conexion(c["CLOUDFLARE_ACCOUNT_ID"], c["CLOUDFLARE_D1_ID"], c["CLOUDFLARE_API_TOKEN"])
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def con():
    if "db" not in g:
        g.db = _conectar()
    return g.db


def cerrar(_=None):
    c = g.pop("db", None)
    if c is not None:
        c.close()


REFERENCIA = ("feriados", "listas", "templates", "catalogo", "perfiles")
VIGENCIA_REFERENCIA = 120
_fijas = {}


def olvidar_cache():
    g.pop("cache_d1", None)


def _solo_referencia(sql):
    tablas = re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.I)
    return bool(tablas) and all(t.lower() in REFERENCIA for t in tablas)


def _fija_vigente(clave):
    hit = _fijas.get(clave)
    return hit is not None and hit[0] > time.time()


def _guardar(clave, filas, cache):
    if _solo_referencia(clave[0]):
        _fijas[clave] = (time.time() + VIGENCIA_REFERENCIA, filas)
    else:
        cache[clave] = filas


def precargar(consultas):
    if not MODO_D1:
        return
    cache = g.setdefault("cache_d1", {})
    faltan, vistos = [], set()
    for sql, params in consultas:
        clave = (sql, tuple(params))
        if clave in vistos or clave in cache or (_solo_referencia(sql) and _fija_vigente(clave)):
            continue
        vistos.add(clave)
        faltan.append(clave)
    for i in range(0, len(faltan), d1.DECLARACIONES_POR_PEDIDO):
        trozo = faltan[i:i + d1.DECLARACIONES_POR_PEDIDO]
        try:
            resultados = con().lote(trozo)
        except (sqlite3.Error, d1.ErrorSQL):
            return
        for clave, cur in zip(trozo, resultados):
            _guardar(clave, cur.fetchall(), cache)


def q(sql, params=()):
    if not MODO_D1:
        return con().execute(sql, params).fetchall()
    cache = g.setdefault("cache_d1", {})
    clave = (sql, tuple(params))
    if _solo_referencia(sql):
        if not _fija_vigente(clave):
            _fijas[clave] = (time.time() + VIGENCIA_REFERENCIA, con().execute(sql, params).fetchall())
        return _fijas[clave][1]
    if clave not in cache:
        cache[clave] = con().execute(sql, params).fetchall()
    return cache[clave]


def uno(sql, params=()):
    if not MODO_D1:
        return con().execute(sql, params).fetchone()
    filas = q(sql, params)
    return filas[0] if filas else None


def ex(sql, params=()):
    c = con()
    cur = c.execute(sql, params)
    c.commit()
    if MODO_D1:
        olvidar_cache()
        escrita = re.match(r"\s*(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+(\w+)", sql, re.I)
        if escrita and escrita.group(1).lower() in REFERENCIA:
            _fijas.clear()
    return cur.lastrowid


def feriados():
    from datetime import date
    return {date.fromisoformat(r["fecha"]) for r in q("SELECT fecha FROM feriados")}


def auditar(usuario_id, protocolo_id, accion, detalle="", estudio_id=None):
    ex("INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, estudio_id, accion, detalle) VALUES (?,?,?,?,?,?)",
       (ahora(), usuario_id, protocolo_id, estudio_id, accion, detalle))


def unificar_etapas(c):
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


def unificar_lotes(c):
    activos = {}
    for r in c.execute("SELECT id, protocolo_id, lote_id FROM estudios WHERE anulado=0 ORDER BY id"):
        activos.setdefault(r["protocolo_id"], []).append(r)
    for filas in activos.values():
        destino = filas[0]["lote_id"] if filas[0]["lote_id"] is not None else next((f["lote_id"] for f in filas if f["lote_id"] is not None), None)
        for f in filas:
            if f["lote_id"] != destino:
                c.execute("UPDATE estudios SET lote_id=? WHERE id=?", (destino, f["id"]))
    c.commit()


def preparar_esquema(c):
    if not MODO_D1 and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='casos'").fetchone():
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
    cols = lambda t: {r["name"] for r in c.execute(f"PRAGMA table_info({t})")}
    antes_de_informes = "titulo" not in cols("usuarios")
    for tabla, col, definicion in (("usuarios", "perfil_id", "INTEGER REFERENCES perfiles(id)"),
                                   ("usuarios", "permisos_mas", "VARCHAR(500) NOT NULL DEFAULT ''"),
                                   ("usuarios", "permisos_menos", "VARCHAR(500) NOT NULL DEFAULT ''"),
                                   ("usuarios", "titulo", "VARCHAR(10)"),
                                   ("usuarios", "mn", "VARCHAR(20)"),
                                   ("usuarios", "mp", "VARCHAR(20)"),
                                   ("protocolos", "borrador", "INTEGER NOT NULL DEFAULT 0"),
                                   ("protocolos", "etiqueta_lote_id", "INTEGER"),
                                   ("informes_emitidos", "estudios", "VARCHAR(500)"),
                                   ("protocolos", "firmante_id", "INTEGER"),
                                   ("estudios", "lab_etiquetado_en", "VARCHAR(19)")):
        if col not in cols(tabla):
            c.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {definicion}")
    c.execute("CREATE INDEX IF NOT EXISTS ix_protocolos_borrador ON protocolos(borrador)")
    return antes_de_informes


def inicializar():
    c = _conectar()
    antes_de_informes = preparar_esquema(c)
    if not MODO_D1:
        unificar_etapas(c)
        unificar_lotes(c)
    if antes_de_informes:
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


def respaldar(destinos, conservar=48):
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
    if MODO_D1:
        return
    destinos = [os.path.join(DATA, "respaldos")]
    extra = os.environ.get("CONTINGENCIA_RESPALDO")
    if extra:
        destinos.append(extra)

    def ciclo():
        while True:
            try:
                respaldar(destinos)
            except Exception as e:
                print("Respaldo fallido:", e)
            time.sleep(minutos * 60)

    threading.Thread(target=ciclo, daemon=True).start()


def copiar_archivo_db(destino):
    shutil.copy2(DB_PATH, destino)


def _lote_abierto(c, tipo_lote, fecha, usuario_id):
    f = c.execute("SELECT id, codigo FROM lotes WHERE tipo_lote=? AND fecha=? AND cerrado=0 ORDER BY numero DESC LIMIT 1",
                  (tipo_lote, fecha)).fetchone()
    if f:
        return {"id": f["id"], "codigo": f["codigo"], "nuevo": False}
    n = (c.execute("SELECT MAX(numero) AS m FROM lotes WHERE tipo_lote=? AND fecha=?", (tipo_lote, fecha)).fetchone()["m"] or 0) + 1
    codigo = f"{tipo_lote}-{fecha[5:7]}{fecha[8:10]}.{n}"
    lid = c.execute("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_por, creado_en) VALUES (?,?,?,?,?,?)",
                    (codigo, tipo_lote, fecha, n, usuario_id, ahora())).lastrowid
    return {"id": lid, "codigo": codigo, "nuevo": True}


def _bloquear(c, nombre="etiquetas"):
    for _ in range(150):
        ahora_ = time.time()
        try:
            c.execute("INSERT INTO bloqueos (nombre, vence) VALUES (?,?)", (nombre, ahora_ + 30))
            return
        except sqlite3.IntegrityError:
            c.execute("DELETE FROM bloqueos WHERE nombre=? AND vence<?", (nombre, ahora_))
            time.sleep(0.2)
    raise RuntimeError("Otra PC está confirmando etiquetas. Probá de nuevo en unos segundos.")


def _etiquetas_confirmar_d1(tipo, grupo, desde, hasta, n, por_proto, etiquetas, params_json, usuario_id, borradores, etiquetados):
    c = con()
    _bloquear(c)
    try:
        if desde is not None:
            marcas = ",".join("?" * len(grupo))
            choque = c.execute(f"SELECT id, tipo, desde, hasta FROM etiquetas_lotes WHERE tipo IN ({marcas}) "
                               "AND desde IS NOT NULL AND desde <= ? AND hasta >= ? ORDER BY id LIMIT 1",
                               list(grupo) + [hasta, desde]).fetchone()
            if choque:
                return {"error": "choque", "fila": dict(choque)}
        declaraciones, lote, ahora_ = [], None, ahora()
        lote_sql, lote_param = "NULL", []
        if borradores:
            pedidos = borradores["protocolos"]
            repetidos = []
            for i in range(0, len(pedidos), 90):
                trozo = pedidos[i:i + 90]
                repetidos += [r["numero"] for r in c.execute(f"SELECT numero FROM protocolos WHERE numero IN ({','.join('?' * len(trozo))})", trozo).fetchall()]
            if repetidos:
                return {"error": "existentes", "protocolos": repetidos, "estudio": borradores["estudio"]}
            fila = c.execute("SELECT id, codigo FROM lotes WHERE tipo_lote=? AND fecha=? AND cerrado=0 ORDER BY numero DESC LIMIT 1",
                             (borradores["tipo_lote"], borradores["fecha_lote"])).fetchone()
            if fila:
                lote = {"id": fila["id"], "codigo": fila["codigo"], "nuevo": False}
                lote_sql, lote_param = "?", [fila["id"]]
            else:
                numero_lote = (c.execute("SELECT MAX(numero) AS m FROM lotes WHERE tipo_lote=? AND fecha=?",
                                         (borradores["tipo_lote"], borradores["fecha_lote"])).fetchone()["m"] or 0) + 1
                fecha = borradores["fecha_lote"]
                codigo = f"{borradores['tipo_lote']}-{fecha[5:7]}{fecha[8:10]}.{numero_lote}"
                declaraciones.append(("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_por, creado_en) VALUES (?,?,?,?,?,?)",
                                      (codigo, borradores["tipo_lote"], fecha, numero_lote, usuario_id, ahora_)))
                lote = {"id": None, "codigo": codigo, "nuevo": True}
                lote_sql, lote_param = "(SELECT id FROM lotes WHERE codigo=?)", [codigo]
        pos_lote = 0 if lote and lote["nuevo"] else None
        pos_etiquetas = len(declaraciones)
        declaraciones.append((f"INSERT INTO etiquetas_lotes (tipo, desde, hasta, lote_id, n, por_proto, etiquetas, params, creado_por, creado_en) "
                              f"VALUES (?,?,?,{lote_sql},?,?,?,?,?,?)",
                              [tipo, desde, hasta] + lote_param + [n, por_proto, etiquetas, params_json, usuario_id, ahora_]))
        if borradores:
            fila_sql = "(?,?,1,(SELECT MAX(id) FROM etiquetas_lotes),?,?)"
            por_sentencia = 22
            pedidos = borradores["protocolos"]
            for i in range(0, len(pedidos), por_sentencia):
                trozo = pedidos[i:i + por_sentencia]
                declaraciones.append(("INSERT INTO protocolos (numero, fecha_recoleccion, borrador, etiqueta_lote_id, creado_por, creado_en) VALUES "
                                      + ",".join([fila_sql] * len(trozo)),
                                      [v for p in trozo for v in (p, borradores["fecha_rec"], usuario_id, ahora_)]))
            declaraciones.append((f"INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, responsable_id, lote_id, creado_por, creado_en) "
                                  f"SELECT p.id, ?, ?, ?, ?, ?, {lote_sql}, ?, ? FROM protocolos p WHERE p.etiqueta_lote_id=(SELECT MAX(id) FROM etiquetas_lotes)",
                                  [borradores["estudio"], borradores["categoria"], borradores["subcategoria"], borradores["sitio"], borradores["responsable_id"]]
                                  + lote_param + [usuario_id, ahora_]))
        if etiquetados:
            for i in range(0, len(etiquetados), 89):
                trozo = list(etiquetados)[i:i + 89]
                declaraciones.append((f"UPDATE estudios SET lab_etiquetado_en=? WHERE id IN ({','.join('?' * len(trozo))})", [ahora_] + trozo))
        resultados = c.lote(declaraciones)
        olvidar_cache()
        if pos_lote is not None:
            lote["id"] = resultados[pos_lote].lastrowid
        return {"id": resultados[pos_etiquetas].lastrowid, "lote": lote}
    finally:
        c.execute("DELETE FROM bloqueos WHERE nombre='etiquetas'")


def etiquetas_confirmar(tipo, grupo, desde, hasta, n, por_proto, etiquetas, params_json, usuario_id,
                        borradores=None, etiquetados=None):
    if MODO_D1:
        return _etiquetas_confirmar_d1(tipo, grupo, desde, hasta, n, por_proto, etiquetas, params_json, usuario_id, borradores, etiquetados)
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
