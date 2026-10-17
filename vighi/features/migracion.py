from flask import Blueprint, jsonify, render_template, request

from vighi.core import db
from vighi.core.sesion import requiere_admin, usuario_actual
from vighi.servicios import migracion_anterior, migracion_imagenes

bp = Blueprint("migracion", __name__)
MAX_POR_PEDIDO = 25
MAX_IMAGENES = 60
SQL_RESUMEN = "SELECT COUNT(*) AS n FROM protocolos WHERE origen='anterior'"
SQL_USUARIOS = ("SELECT id, iniciales FROM usuarios WHERE nombre IS NULL AND clave_hash IS NULL AND iniciales<>? ORDER BY iniciales")
SQL_TIPOS = ("SELECT f.tipo, COUNT(*) AS n FROM flujos f JOIN protocolos p ON p.id=f.protocolo_id WHERE p.origen='anterior' GROUP BY f.tipo ORDER BY f.tipo")


def registro_valido(r):
    return isinstance(r, dict) and isinstance(r.get("numero"), str) and r["numero"] and isinstance(r.get("flujos"), list) and r["flujos"]


@bp.route("/migracion")
@requiere_admin
def migracion():
    db.precargar([(SQL_RESUMEN, ()), (SQL_TIPOS, ()), (SQL_USUARIOS, (migracion_anterior.INICIALES_SISTEMA,))])
    return render_template("migracion/migracion.html", importados=db.uno(SQL_RESUMEN)["n"], tipos=db.q(SQL_TIPOS),
                           usuarios=db.q(SQL_USUARIOS, (migracion_anterior.INICIALES_SISTEMA,)), por_pedido=MAX_POR_PEDIDO)


@bp.route("/api/migracion/lote", methods=["POST"])
@requiere_admin
def migracion_lote():
    datos = request.get_json(silent=True) or {}
    registros = datos.get("registros")
    if not isinstance(registros, list) or not 0 < len(registros) <= MAX_POR_PEDIDO or not all(registro_valido(r) for r in registros):
        return jsonify({"error": f"Mandá entre 1 y {MAX_POR_PEDIDO} protocolos con número y flujos."}), 400
    ensayo = bool(datos.get("ensayo", True))
    resultado = migracion_anterior.importar(registros, ensayo=ensayo)
    if not ensayo and resultado["importados"]:
        db.auditar(usuario_actual()["id"], None, "migracion", f"Importó {resultado['importados']} protocolo(s) del sistema anterior ({resultado['existentes']} ya estaban)")
    return jsonify(resultado)


@bp.route("/api/migracion/imagenes", methods=["POST"])
@requiere_admin
def migracion_imagenes_lote():
    datos = request.get_json(silent=True) or {}
    numero, imagenes = datos.get("numero"), datos.get("imagenes")
    if not isinstance(numero, str) or not isinstance(imagenes, list) or not 0 < len(imagenes) <= MAX_IMAGENES or not all(isinstance(i, dict) and isinstance(i.get("url"), str) for i in imagenes):
        return jsonify({"error": f"Mandá el número de protocolo y entre 1 y {MAX_IMAGENES} imágenes con su dirección."}), 400
    return jsonify(migracion_imagenes.importar_imagenes(numero, imagenes, ensayo=bool(datos.get("ensayo", True))))
