import argparse
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CARPETA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "migracion_anterior")
CERROJO = threading.Lock()


def crear_manejador(carpeta):
    class Manejador(BaseHTTPRequestHandler):
        def cabeceras(self, codigo=200):
            self.send_response(codigo)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()

        def nombre(self):
            return re.sub(r"[^A-Za-z0-9_.-]", "_", self.path.strip("/").split("/")[-1] or "x")

        def do_OPTIONS(self):
            self.cabeceras()

        def do_GET(self):
            ruta = os.path.join(carpeta, self.nombre())
            self.cabeceras()
            if self.path.startswith("/f/") and os.path.exists(ruta):
                with open(ruta, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"ok")

        def do_POST(self):
            cuerpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            with CERROJO, open(os.path.join(carpeta, self.nombre()), "ab") as f:
                f.write(cuerpo.replace(b"\r", b"").replace(b"\n", b" ") + b"\n")
            self.cabeceras()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *a):
            pass

    return Manejador


def main():
    ap = argparse.ArgumentParser(description="Recibe lo que la extracción de southernbits (corriendo en el navegador) manda y lo guarda en data/migracion_anterior.")
    ap.add_argument("--carpeta", default=CARPETA)
    ap.add_argument("--puerto", type=int, default=8765)
    args = ap.parse_args()
    os.makedirs(args.carpeta, exist_ok=True)
    print(f"Escuchando en 127.0.0.1:{args.puerto}, guardando en {args.carpeta}")
    ThreadingHTTPServer(("127.0.0.1", args.puerto), crear_manejador(args.carpeta)).serve_forever()


if __name__ == "__main__":
    main()
