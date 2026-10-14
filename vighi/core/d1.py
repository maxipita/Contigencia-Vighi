import base64
import os
import re
import sqlite3
import threading
import time

URL_BASE = os.environ.get("CONTINGENCIA_D1_URL", "https://api.cloudflare.com/client/v4")
PREFIJO_BLOB = "~b64~"
MAX_PARAMETROS = 90
DECLARACIONES_POR_PEDIDO = 40
ESPERA_SEGUNDOS = 30

_hilo = threading.local()


class ErrorD1(Exception):
    pass


class ErrorConexion(ErrorD1):
    pass


class ErrorSQL(ErrorD1):
    pass


class Fila:
    __slots__ = ("_claves", "_valores", "_indice")

    def __init__(self, claves, valores):
        self._claves = claves
        self._valores = valores
        self._indice = {k: i for i, k in enumerate(claves)}

    def keys(self):
        return list(self._claves)

    def __getitem__(self, clave):
        if isinstance(clave, int):
            return self._valores[clave]
        try:
            return self._valores[self._indice[clave]]
        except KeyError:
            raise IndexError(f"No item with that key: {clave}") from None

    def __iter__(self):
        return iter(self._valores)

    def __len__(self):
        return len(self._valores)


class Cursor:
    def __init__(self, filas, ultimo_id=None, cambios=0):
        self._filas = filas
        self._pos = 0
        self.lastrowid = ultimo_id
        self.rowcount = cambios

    def fetchone(self):
        if self._pos >= len(self._filas):
            return None
        fila = self._filas[self._pos]
        self._pos += 1
        return fila

    def fetchall(self):
        resto = self._filas[self._pos:]
        self._pos = len(self._filas)
        return resto

    def __iter__(self):
        return iter(self.fetchall())


def _codificar(valor):
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return PREFIJO_BLOB + base64.b64encode(bytes(valor)).decode("ascii")
    return valor


def _decodificar(valor):
    if isinstance(valor, str) and valor.startswith(PREFIJO_BLOB):
        return base64.b64decode(valor[len(PREFIJO_BLOB):])
    return valor


def _sesion():
    import requests
    s = getattr(_hilo, "sesion", None)
    if s is None:
        s = _hilo.sesion = requests.Session()
    return s


def _es_lectura(sql):
    return sql.lstrip().split(None, 1)[0].upper() in ("SELECT", "PRAGMA", "WITH")


def dividir_script(script):
    sentencias, acumulado = [], ""
    for linea in script.splitlines(keepends=True):
        acumulado += linea
        if sqlite3.complete_statement(acumulado):
            if acumulado.strip():
                sentencias.append(acumulado.strip())
            acumulado = ""
    if acumulado.strip():
        sentencias.append(acumulado.strip())
    return sentencias


class Conexion:
    def __init__(self, cuenta, base, token):
        self._url = f"{URL_BASE}/accounts/{cuenta}/d1/database/{base}/query"
        self._token = token

    def _post(self, cuerpo, reintentar):
        import requests
        intentos = 3 if reintentar else 1
        for intento in range(intentos):
            try:
                r = _sesion().post(self._url, json=cuerpo, headers={"Authorization": f"Bearer {self._token}"}, timeout=ESPERA_SEGUNDOS)
            except requests.RequestException as e:
                if intento + 1 == intentos:
                    raise ErrorConexion(f"No hay conexión con Cloudflare D1: {type(e).__name__}") from None
                time.sleep(0.4 * (intento + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504) and intento + 1 < intentos:
                time.sleep(0.4 * (intento + 1))
                continue
            return r
        raise ErrorConexion("No hay conexión con Cloudflare D1")

    def _enviar(self, declaraciones):
        reintentar = all(_es_lectura(s) for s, _ in declaraciones)
        if len(declaraciones) == 1:
            sql, params = declaraciones[0]
            cuerpo = {"sql": sql, "params": [_codificar(p) for p in params]}
        else:
            cuerpo = {"batch": [{"sql": s, "params": [_codificar(p) for p in ps]} for s, ps in declaraciones]}
        r = self._post(cuerpo, reintentar)
        try:
            datos = r.json()
        except ValueError:
            raise ErrorConexion(f"Respuesta inesperada de Cloudflare D1 (HTTP {r.status_code})") from None
        if not datos.get("success"):
            mensaje = "; ".join(e.get("message", "") for e in datos.get("errors", [])) or f"HTTP {r.status_code}"
            if "constraint failed" in mensaje.lower() or "SQLITE_CONSTRAINT" in mensaje:
                raise sqlite3.IntegrityError(mensaje)
            raise (ErrorConexion if r.status_code >= 500 or r.status_code in (401, 403, 429) else ErrorSQL)(mensaje)
        cursores = []
        for resultado in datos["result"]:
            filas = [Fila(list(f.keys()), [_decodificar(v) for v in f.values()]) for f in resultado.get("results") or []]
            meta = resultado.get("meta") or {}
            cursores.append(Cursor(filas, meta.get("last_row_id"), meta.get("changes", 0)))
        return cursores

    def execute(self, sql, params=()):
        return self._enviar([(sql, tuple(params))])[0]

    def lote(self, declaraciones):
        return self._enviar([(s, tuple(p)) for s, p in declaraciones])

    def executemany(self, sql, filas):
        filas = [tuple(f) for f in filas]
        if not filas:
            return
        m = re.fullmatch(r"(\s*INSERT\s+INTO\s+[^()]+(?:\([^)]*\))?\s*VALUES\s*)\(([^()]*)\)\s*", sql, re.I | re.S)
        if m and len(filas[0]) <= MAX_PARAMETROS:
            por_sentencia = max(1, MAX_PARAMETROS // len(filas[0]))
            grupo = "(" + m.group(2) + ")"
            declaraciones = []
            for i in range(0, len(filas), por_sentencia):
                trozo = filas[i:i + por_sentencia]
                declaraciones.append((m.group(1) + ",".join([grupo] * len(trozo)), [v for f in trozo for v in f]))
        else:
            declaraciones = [(sql, f) for f in filas]
        for i in range(0, len(declaraciones), DECLARACIONES_POR_PEDIDO):
            self._enviar(declaraciones[i:i + DECLARACIONES_POR_PEDIDO])

    def executescript(self, script):
        sentencias = dividir_script(script)
        for i in range(0, len(sentencias), DECLARACIONES_POR_PEDIDO):
            self._enviar([(s, ()) for s in sentencias[i:i + DECLARACIONES_POR_PEDIDO]])

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass
