import json
import logging
import sqlite3
import threading

from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response

logging.getLogger('werkzeug').setLevel(logging.ERROR)
TOKEN, CUENTA, BASE = "token-de-prueba", "cuenta-de-prueba", "base-de-prueba"


class ErrorD1(Exception):
    pass


class FalsoD1:
    def __init__(self):
        self.con = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        self.pedidos = 0
        self.sentencias = 0
        self.max_cuerpo = 0
        self.cerrojo = threading.Lock()
        self.ruta = f"/accounts/{CUENTA}/d1/database/{BASE}/query"
        self.latencia = 0.0
        self.fallos = 0
        self.servidor = None

    def ejecutar(self, sql, params):
        if len(sql.encode("utf-8")) > 100_000:
            raise ErrorD1("D1_ERROR: statement too long: SQLITE_TOOBIG")
        if len(params) > 100:
            raise ErrorD1("D1_ERROR: too many SQL variables: SQLITE_ERROR")
        try:
            cur = self.con.execute(sql, params)
            filas = [dict(r) for r in cur.fetchall()]
        except sqlite3.IntegrityError as e:
            raise ErrorD1(f"D1_ERROR: {e}: SQLITE_CONSTRAINT")
        except sqlite3.Error as e:
            raise ErrorD1(f"D1_ERROR: {e}: SQLITE_ERROR")
        for fila in filas:
            for k, v in fila.items():
                if isinstance(v, bytes):
                    raise ErrorD1("D1_ERROR: BLOB no soportado en este simulador")
        self.sentencias += 1
        return {"results": filas, "success": True, "meta": {"last_row_id": cur.lastrowid, "changes": max(cur.rowcount, 0), "rows_read": len(filas)}}

    def app(self, entorno, inicio):
        peticion = Request(entorno)
        if peticion.path != self.ruta:
            return Response(json.dumps({"success": False, "errors": [{"code": 7003, "message": "ruta desconocida"}]}), 404, content_type="application/json")(entorno, inicio)
        if peticion.headers.get("Authorization") != f"Bearer {TOKEN}":
            return Response(json.dumps({"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}), 401, content_type="application/json")(entorno, inicio)
        if self.fallos > 0:
            self.fallos -= 1
            return Response(json.dumps({"success": False}), 503, content_type="application/json")(entorno, inicio)
        cuerpo = peticion.get_data()
        self.max_cuerpo = max(self.max_cuerpo, len(cuerpo))
        datos = json.loads(cuerpo)
        with self.cerrojo:
            self.pedidos += 1
            try:
                if "batch" in datos:
                    self.con.execute("BEGIN")
                    try:
                        resultado = [self.ejecutar(b["sql"], b.get("params", [])) for b in datos["batch"]]
                        self.con.execute("COMMIT")
                    except Exception:
                        self.con.execute("ROLLBACK")
                        raise
                else:
                    resultado = [self.ejecutar(datos["sql"], datos.get("params", []))]
                salida, codigo = {"success": True, "errors": [], "messages": [], "result": resultado}, 200
            except ErrorD1 as e:
                salida, codigo = {"success": False, "errors": [{"code": 7500, "message": str(e)}], "messages": [], "result": []}, 400
        return Response(json.dumps(salida), codigo, content_type="application/json")(entorno, inicio)

    def iniciar(self):
        self.servidor = make_server("127.0.0.1", 0, self.app, threaded=True)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.servidor.server_port}"

    def detener(self):
        self.servidor.shutdown()
