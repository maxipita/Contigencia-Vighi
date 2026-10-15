import os
import secrets

from flask import Flask

from vighi.core import db, fechas, sesion
from vighi.features import (auth, envios, estudios, etiquetas, facturacion, imagenes, informes, listados, lotes, plantillas, protocolos, sistema,
                            tablero, tareas, ubicaciones, usuarios)

BLUEPRINTS = (sistema, auth, tablero, protocolos, estudios, informes, imagenes, lotes, etiquetas, plantillas, usuarios, facturacion, listados, envios, ubicaciones, tareas)
FILTROS = (("fh", fechas.fecha_hora), ("larga", fechas.fecha_larga), ("edad", fechas.edad), ("dh", fechas.fecha_hora_dt), ("f", fechas.fecha),
           ("peso", fechas.peso), ("peso0", fechas.peso_entero))


def clave_secreta():
    de_entorno = db.ajuste("CONTINGENCIA_SECRET_KEY")
    if de_entorno:
        return de_entorno
    ruta = os.path.join(db.DATA, "secret.key")
    os.makedirs(db.DATA, exist_ok=True)
    if not os.path.exists(ruta):
        with open(ruta, "w") as f:
            f.write(secrets.token_hex(32))
    with open(ruta) as f:
        return f.read().strip()


def crear_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
    app.secret_key = clave_secreta()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    if os.environ.get("CONTINGENCIA_HTTPS") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["SESSION_COOKIE_SECURE"] = True
    app.teardown_appcontext(db.cerrar)
    app.before_request(sesion.adelantar_lecturas)
    app.before_request(sesion.verificar_csrf)
    app.before_request(sesion.modo_vista)
    app.context_processor(sesion.globales)
    for nombre, funcion in FILTROS:
        app.add_template_filter(funcion, nombre)
    for modulo in BLUEPRINTS:
        app.register_blueprint(modulo.bp)
    return app
