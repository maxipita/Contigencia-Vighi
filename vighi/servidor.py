import os
import socket

from vighi.core import d1, db
from vighi.core.config import PUERTO


def ips_locales():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def ejecutar(app):
    try:
        db.inicializar()
    except (RuntimeError, d1.ErrorD1) as error:
        print(f"No se puede iniciar el sistema: {error}")
        raise SystemExit(1)
    if os.environ.get("CONTINGENCIA_DESARROLLO") == "1":
        app.jinja_env.auto_reload = True
        recarga = os.environ.get("CONTINGENCIA_SIN_RECARGA") != "1"
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not recarga:
            print("=" * 64)
            print(" MODO DESARROLLO — " + ("recarga automática al guardar" if recarga else "con depurador, SIN recarga (reiniciar tras cambiar un .py)"))
            print(f" Abrir:             http://localhost:{PUERTO}")
            print(f" Base de datos:     {db.nombre_base()}")
            print("=" * 64)
        app.run(host="127.0.0.1", port=PUERTO, debug=True, use_reloader=recarga)
        raise SystemExit
    from waitress import serve
    print("=" * 64)
    print(" Sistema de contingencia CAP Vighi")
    print(f" En esta PC:        http://localhost:{PUERTO}")
    for ip in ips_locales():
        print(f" Desde otras PCs:   http://{ip}:{PUERTO}")
    print(f" Base de datos:     {db.nombre_base()}")
    print(" Para detenerlo: cerrar esta ventana.")
    print("=" * 64)
    serve(app, host="0.0.0.0", port=PUERTO, threads=12)
