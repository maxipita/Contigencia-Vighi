from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.sesion import requiere_admin, requiere_login, usuario_actual
from vighi.servicios.catalogo import tipos_de_muestra_bp

bp = Blueprint("plantillas", __name__)


@bp.route("/api/catalogo/<tipo>")
@requiere_login
def api_catalogo(tipo):
    arbol = {}
    for r in db.q("SELECT subcategoria, sitio, tipo_muestra FROM catalogo WHERE tipo=?", (tipo,)):
        arbol.setdefault(r["subcategoria"], {}).setdefault(r["sitio"], []).append(r["tipo_muestra"])
    return jsonify(arbol)


@bp.route("/templates", methods=["GET", "POST"])
@requiere_admin
def templates_admin():
    yo = usuario_actual()
    catalogo = db.q("SELECT DISTINCT subcategoria, sitio FROM catalogo WHERE tipo='BP' ORDER BY subcategoria, sitio")
    zonas = sorted({r["subcategoria"] for r in catalogo})
    tipos = tipos_de_muestra_bp()
    if request.method == "POST":
        ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
        cambios = {}
        for campo, columna in (("zona", "tipo_biopsia"), ("organo", "organo"), ("tipo", "tipo_muestra")):
            valor = request.form.get(campo, "")
            if valor == "__vaciar__":
                cambios[columna] = None
            elif valor:
                cambios[columna] = valor
        organo = cambios.get("organo")
        if organo and "tipo_biopsia" not in cambios:
            propias = {r["subcategoria"] for r in catalogo if r["sitio"] == organo}
            if len(propias) == 1:
                cambios["tipo_biopsia"] = next(iter(propias))
        if not ids:
            flash("Marcá al menos un template.", "error")
        elif not cambios:
            flash("Elegí qué querés asignar (zona, órgano o tipo).", "error")
        else:
            sets = ", ".join(f"{k}=?" for k in cambios)
            for i in range(0, len(ids), 40):
                db.lote_ex([(f"UPDATE templates SET {sets} WHERE id=?", tuple(cambios.values()) + (tid,)) for tid in ids[i:i + 40]])
            db.auditar(yo["id"], None, "templates", f"{len(ids)} templates: " + ", ".join(f"{k}={v or '(vacío)'}" for k, v in cambios.items()))
            flash(f"Se actualizaron {len(ids)} templates.", "ok")
        return redirect(url_for("plantillas.templates_admin", **{k: v for k, v in request.args.items()}))
    f = {k: request.args.get(k, "") for k in ("clase", "zona", "organo", "tipo", "estado", "q")}
    where, par = ["1=1"], []
    if f["clase"] in ("macro", "micro"):
        where.append("clase=?")
        par.append(f["clase"])
    if f["zona"]:
        where.append("tipo_biopsia=?")
        par.append(f["zona"])
    if f["organo"]:
        where.append("organo=?")
        par.append(f["organo"])
    if f["tipo"]:
        where.append("tipo_muestra=?")
        par.append(f["tipo"])
    if f["estado"] == "sin_organo":
        where.append("(organo IS NULL OR organo='')")
    elif f["estado"] == "sin_tipo":
        where.append("(tipo_muestra IS NULL OR tipo_muestra='')")
    elif f["estado"] == "sin_zona":
        where.append("(tipo_biopsia IS NULL OR tipo_biopsia='')")
    if f["q"]:
        where.append("LOWER(titulo) LIKE ?")
        par.append("%" + f["q"].lower() + "%")
    total = db.uno("SELECT COUNT(*) AS n FROM templates")["n"]
    filas = db.q(f"SELECT id, clase, titulo, tipo_biopsia, organo, tipo_muestra FROM templates WHERE {' AND '.join(where)} ORDER BY clase, titulo LIMIT 400", par)
    sin_clasificar = db.uno("SELECT COUNT(*) AS n FROM templates WHERE organo IS NULL OR organo=''")["n"]
    return render_template("plantillas/templates_admin.html", filas=filas, f=f, zonas=zonas, tipos=tipos, total=total, sin_clasificar=sin_clasificar,
                           organos=[(z, [r["sitio"] for r in catalogo if r["subcategoria"] == z]) for z in zonas])


@bp.route("/api/template/<int:tid>")
@requiere_login
def api_template(tid):
    t = db.uno("SELECT titulo, texto, conclusion FROM templates WHERE id=?", (tid,))
    return jsonify(dict(t)) if t else (jsonify({}), 404)


@bp.route("/api/medicos")
@requiere_login
def api_medicos():
    r = jsonify([m["nombre"] for m in db.q("SELECT nombre FROM medicos ORDER BY nombre")])
    r.headers["Cache-Control"] = "private, max-age=60"
    return r
