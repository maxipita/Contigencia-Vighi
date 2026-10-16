import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.sesion import puede, requiere_login, requiere_permiso, usuario_actual
from vighi.dominio.estudios import REGISTRO, TIPOS, validar_combinacion
from vighi.servicios import mensajeria
from vighi.servicios.consultas import cargar_estudios, consultas_estudios, flujos_de, listas
from vighi.servicios.entrega import malignidad_por_flujo
from vighi.servicios.etiquetas import numero_emitido, numero_protocolo
from vighi.servicios.fichas import SQL_INFORME_EMITIDO, informe_emitido, informe_vigente
from vighi.servicios.imagenes import SQL_IMAGENES, imagenes_de
from vighi.servicios.lotes import asignar_lote, avisar_lote_lleno, concretar_lote, lote_del_protocolo, ubicar_en_lote, validar_lote
from vighi.servicios.ordenes import SQL_ORDENES, ordenes_de
from vighi.servicios.tareas import SQL_TAREAS, SQL_USUARIOS_SECTORES, tareas_de, usuarios_con_sectores
from vighi.servicios.protocolos import CAMPOS_ESTUDIO, CAMPOS_PACIENTE, CAMPOS_PROTOCOLO, CAMPOS_RAPIDOS, SQL_COMENTARIOS, SQL_HISTORIAL_PROTOCOLO, SQL_PROTOCOLO, comentarios_de, completo, contexto_formulario, crear_estudio, dni_valido, edicion_propia, edicion_vigente, error_plan, estudios_del_formulario, leer_protocolo, protocolo_o_404, protocolos_del_paciente, recordar_tecnicas, sincronizar_paciente, soltar_edicion, tomar_edicion, validar_estudios, volver_a_comentarios
from vighi.servicios.ubicaciones import error_ubicaciones, ubicaciones_del_protocolo
from vighi.servicios.validacion import CAMPOS_ACTIVACION, activar, faltantes_activacion, solo_pap

bp = Blueprint("protocolos", __name__)


@bp.route("/protocolo/nuevo", methods=["GET", "POST"])
@requiere_permiso("protocolo_crear")
def protocolo_nuevo():
    yo = usuario_actual()
    p, lista = {}, []
    if request.method == "POST":
        p, lista = leer_protocolo(), estudios_del_formulario()
        lote_valor, error = validar_estudios(lista)
        if not p["numero"]:
            error = "Falta el N° de protocolo."
        elif (dup := db.uno("SELECT id, borrador FROM protocolos WHERE numero=?", (p["numero"],))) and dup["borrador"]:
            flash(f"El protocolo {p['numero']} ya fue generado desde Recepción y falta completarlo: cargá los datos acá.", "ok")
            return redirect(url_for("protocolos.protocolo_editar", pid=dup["id"]))
        elif dup:
            error = f"El protocolo {p['numero']} ya existe: para sumarle un estudio usá «+ Agregar estudio» en su ficha."
        elif not lista:
            error = "Agregá al menos un estudio (PAP, Biopsia o Citología)."
        error = error or error_ubicaciones(p)
        if error:
            flash(error, "error")
        else:
            cols = ["numero"] + CAMPOS_PROTOCOLO
            pid = db.ex(f"INSERT INTO protocolos (creado_por, creado_en, {', '.join(cols)}) VALUES (?,?,{','.join('?' * len(cols))})",
                        [yo["id"], db.ahora()] + [p[c] for c in cols])
            db.auditar(yo["id"], pid, "ingreso", p["numero"])
            sincronizar_paciente(pid, p["dni"])
            lote = concretar_lote(lote_valor, yo["id"])
            for e in lista:
                crear_estudio(pid, e, lote, yo["id"])
            avisar_lote_lleno(ubicar_en_lote(pid, yo["id"]))
            flash(f"Protocolo {p['numero']} ingresado con {len(lista)} estudio(s).", "ok")
            if not numero_emitido(p["numero"]):
                flash(f"Atención: {p['numero']} no figura en ningún lote de etiquetas confirmado (menú Etiquetas).", "error")
            return redirect(url_for("protocolos.protocolo", pid=pid))
    elif request.args.get("tipo") in REGISTRO:
        lista = [{"tipo": request.args["tipo"]}]
    ultimos = [r["numero"] for r in db.q("SELECT numero FROM protocolos ORDER BY id DESC LIMIT 5")]
    return render_template("protocolos/protocolo_form.html", p=p, estudios=lista, nuevo=True, ultimos=ultimos, **contexto_formulario())


@bp.route("/protocolo/<int:pid>/editar", methods=["GET", "POST"])
@requiere_permiso("protocolo_crear", "protocolo_editar")
def protocolo_editar(pid):
    if request.method != "POST":
        return _protocolo_editar(pid)
    try:
        with db.bloqueo(f"completar-{pid}"):
            return _protocolo_editar(pid)
    except RuntimeError:
        flash("Otra persona está guardando este protocolo en este momento. Esperá unos segundos y revisá cómo quedó.", "error")
        return redirect(url_for("protocolos.protocolo", pid=pid))


@bp.route("/protocolo/<int:pid>/editar/soltar", methods=["POST"])
@requiere_permiso("protocolo_crear", "protocolo_editar")
def protocolo_soltar(pid):
    soltar_edicion(pid, usuario_actual()["id"], request.form.get("edicion", ""))
    return ("", 204)


def _protocolo_editar(pid):
    yo = usuario_actual()
    p = protocolo_o_404(pid)
    borrador = bool(p["borrador"])
    token_form = request.form.get("edicion")
    if request.method == "POST" and token_form is not None and not borrador:
        flash(f"El protocolo {p['numero']} ya estaba completo: no se cambió nada.", "ok")
        return redirect(url_for("protocolos.protocolo", pid=pid))
    if request.method == "POST" and borrador:
        if not edicion_propia(pid, yo["id"], token_form):
            otra = edicion_vigente(pid)
            if otra and otra["usuario_id"] != yo["id"]:
                flash(f"{otra['nombre'] or 'Otra persona'} está completando este protocolo: no se guardó nada.", "error")
                return redirect(url_for("tablero.completar"))
            flash("Este formulario quedó desactualizado (el protocolo ya se guardó o se abrió en otra ventana). Abrilo de nuevo para completarlo.", "error")
            return redirect(url_for("protocolos.protocolo_editar", pid=pid))
    if not borrador and not puede("protocolo_editar"):
        flash("No tenés permiso para editar protocolos. Pedíselo a un administrador.", "error")
        return redirect(url_for("protocolos.protocolo", pid=pid))
    actuales = {e["id"]: e for e in db.q("SELECT * FROM estudios WHERE protocolo_id=? ORDER BY id", (pid,))}
    lista = [{**dict(e), "lote_sel": str(e["lote_id"] or "")} for e in actuales.values() if not e["anulado"]] if borrador else []
    modo_pap = borrador and solo_pap(list(actuales.values()))
    if request.method == "POST":
        d = {**{k: request.form.get(k, "").strip() for k in CAMPOS_ACTIVACION}, "numero": p["numero"]} if modo_pap else leer_protocolo()
        error = None
        if borrador:
            lista = [e for e in estudios_del_formulario() if e["id"] is None or e["id"] in actuales]
            error = validar_combinacion(lista) if lista else "El protocolo tiene que tener al menos un estudio."
            lote_valor = None
            if not error:
                actual = lote_del_protocolo(pid)
                lote_valor, error = validar_lote(lista[0]["lote_sel"], lista[0]["tipo"], actual["id"] if actual else None)
        if not d["numero"]:
            error = "Falta el N° de protocolo."
        elif db.uno("SELECT 1 FROM protocolos WHERE numero=? AND id<>?", (d["numero"], pid)):
            error = f"Ya existe otro protocolo {d['numero']}."
        error = error or error_ubicaciones(d, p) or error_plan(d)
        if error:
            flash(error, "error")
        else:
            cols = CAMPOS_ACTIVACION if modo_pap else ["numero"] + CAMPOS_PROTOCOLO
            db.ex(f"UPDATE protocolos SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [d[c] for c in cols] + [pid])
            db.auditar(yo["id"], pid, "editar_protocolo")
            if not modo_pap and (not p["dni"] or p["dni"] == d["dni"]):
                sincronizar_paciente(pid, d["dni"], [c for c in CAMPOS_PACIENTE if d[c] != (p[c] or "")] if p["dni"] else None)
            if not borrador:
                flash("Datos del protocolo actualizados.", "ok")
                return redirect(url_for("protocolos.protocolo", pid=pid))
            soltar_edicion(pid)
            lote = concretar_lote(lote_valor, yo["id"])
            for e in lista:
                if e["id"]:
                    db.ex(f"UPDATE estudios SET {', '.join(k + '=?' for k in CAMPOS_ESTUDIO)} WHERE id=?",
                          [e[k] for k in CAMPOS_ESTUDIO] + [e["id"]])
                    recordar_tecnicas(e)
                else:
                    crear_estudio(pid, e, lote, yo["id"])
            asignar_lote(pid, lote, yo["id"])
            quitados = [k for k, e in actuales.items() if k not in {x["id"] for x in lista} and not e["anulado"]]
            for k in quitados:
                db.ex("DELETE FROM estudios WHERE id=?", (k,))
            if quitados:
                db.ex("DELETE FROM flujos WHERE protocolo_id=? AND NOT EXISTS (SELECT 1 FROM estudios e WHERE e.flujo_id=flujos.id)", (pid,))
                db.auditar(yo["id"], pid, "quitar_muestra", f"{len(quitados)} muestra(s) quitada(s) al completar el protocolo")
            if modo_pap:
                falta = faltantes_activacion(d, [dict(x) for x in db.q("SELECT cantidad, anulado FROM estudios WHERE protocolo_id=?", (pid,))])
                if not falta:
                    activar(pid, yo)
                    avisar_lote_lleno(ubicar_en_lote(pid, yo["id"]))
                    flash(f"Protocolo {d['numero']} activado: sigue su curso en el laboratorio y queda pendiente de validar los datos del paciente.", "ok")
                    return redirect(url_for("protocolos.protocolo", pid=pid))
                flash("Datos guardados. Para activar el protocolo falta: " + ", ".join(falta) + ".", "ok")
                return redirect(url_for("protocolos.protocolo_editar", pid=pid))
            if completo(d, [dict(x) for x in db.q("SELECT cantidad, anulado FROM estudios WHERE protocolo_id=?", (pid,))]):
                db.ex("UPDATE protocolos SET borrador=0 WHERE id=?", (pid,))
                db.auditar(yo["id"], pid, "completar", d["numero"])
                avisar_lote_lleno(ubicar_en_lote(pid, yo["id"]))
                flash(f"Protocolo {d['numero']} completo.", "ok")
                return redirect(url_for("protocolos.protocolo", pid=pid))
            flash("Datos guardados. Para completar el protocolo faltan apellido, nombre y la cantidad de cada estudio.", "ok")
            return redirect(url_for("protocolos.protocolo_editar", pid=pid))
        p = {**dict(p), **d}
    token = None
    if borrador:
        token, otra = tomar_edicion(pid, yo["id"])
        if not token:
            hora = (otra["desde"] or "")[11:16] if otra else ""
            flash(f"{(otra and otra['nombre']) or 'Otra persona'} está completando este protocolo" + (f" desde las {hora}" if hora else "") + ". Esperá a que termine o pedile que salga.", "error")
            return redirect(url_for("tablero.completar"))
    ctx = contexto_formulario()
    for e in actuales.values():
        if e["lote_id"] and all(l["id"] != e["lote_id"] for l in ctx["lotes_abiertos"][e["tipo"]]):
            ctx["lotes_abiertos"][e["tipo"]].insert(0, db.uno("SELECT * FROM lotes WHERE id=?", (e["lote_id"],)))
    return render_template("protocolos/protocolo_form.html", p=p, estudios=lista, nuevo=False, completar=borrador, pap=modo_pap, ordenes=ordenes_de(pid) if modo_pap else [], edicion=token, ultimos=[], **ctx)


@bp.route("/paciente/<int:pid>/datos", methods=["POST"])
@requiere_permiso("protocolo_editar")
def paciente_datos(pid):
    base = protocolo_o_404(pid)
    d = {k: request.form.get(k, "").strip() for k in ["dni"] + CAMPOS_PACIENTE}
    if not (d["apellido"] or d["nombre"]):
        flash("Escribí al menos el apellido o el nombre del paciente.", "error")
        return redirect(url_for("protocolos.paciente", pid=pid))
    protocolos = protocolos_del_paciente(base)
    ajenos = [x for x in db.q("SELECT id FROM protocolos WHERE dni=?", (d["dni"],)) if x["id"] not in {y["id"] for y in protocolos}] if dni_valido(d["dni"]) else []
    if ajenos:
        flash("Ya hay otro paciente con ese DNI. Si es la misma persona, corregí el DNI en el protocolo que tiene el error.", "error")
        return redirect(url_for("protocolos.paciente", pid=pid))
    cambios = [k for k in d if d[k] != (base[k] or "")]
    error = error_plan(d)
    if error:
        flash(error, "error")
        return redirect(url_for("protocolos.paciente", pid=pid))
    if cambios:
        cols = list(d)
        yo = usuario_actual()
        db.lote_ex([(f"UPDATE protocolos SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [d[c] for c in cols] + [x["id"]]) for x in protocolos]
                   + [("INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, accion, detalle) VALUES (?,?,?,?,?)",
                       (db.ahora(), yo["id"], x["id"], "editar_paciente", ", ".join(cambios))) for x in protocolos])
        flash(f"Datos del paciente actualizados en {len(protocolos)} protocolo(s).", "ok")
    return redirect(url_for("protocolos.paciente", pid=pid))


@bp.route("/paciente/<int:pid>")
@requiere_login
def paciente(pid):
    base = protocolo_o_404(pid)
    protocolos = protocolos_del_paciente(base)
    ids = [x["id"] for x in protocolos]
    marcas = ",".join("?" * len(ids))
    estudios = cargar_estudios(f"e.protocolo_id IN ({marcas})", ids, borradores=True)
    por_protocolo = {}
    for e in estudios:
        por_protocolo.setdefault(e["protocolo_id"], []).append(e)
    emitidos = {r["protocolo_id"]: r for r in db.q(
        f"SELECT id, protocolo_id, estudios FROM informes_emitidos WHERE protocolo_id IN ({marcas})", ids)}
    informes = {}
    for x in protocolos:
        activos = [e for e in por_protocolo.get(x["id"], []) if not e["anulado"]]
        r = emitidos.get(x["id"])
        cerrado = bool(activos) and not any(e["borrador"] or e["proxima"] for e in activos)
        if r and cerrado and (not r["estudios"] or set(r["estudios"].split(",")) == {str(e["id"]) for e in activos}):
            informes[x["id"]] = r["id"]
    return render_template("protocolos/paciente.html", p=base, listas=listas(), protocolos=protocolos, estudios=por_protocolo, informes=informes,
                           flujos=flujos_de(ids), origen=pid)


@bp.route("/protocolo/<int:pid>/datos", methods=["POST"])
@requiere_permiso("protocolo_editar")
def protocolo_datos(pid):
    p = protocolo_o_404(pid)
    if p["borrador"]:
        return redirect(url_for("protocolos.protocolo_editar", pid=pid))
    d = {k: request.form[k].strip() for k in CAMPOS_RAPIDOS if k in request.form}
    if "cobertura" in d and "plan" not in d:
        d["plan"] = ""
    cambios = [k for k in d if d[k] != (p[k] or "")]
    error = error_ubicaciones(d, p) or error_plan(d, p)
    if error:
        flash(error, "error")
        return redirect(url_for("protocolos.protocolo", pid=pid))
    if cambios:
        db.ex(f"UPDATE protocolos SET {', '.join(k + '=?' for k in cambios)} WHERE id=?", [d[k] for k in cambios] + [pid])
        db.auditar(usuario_actual()["id"], pid, "editar_protocolo", ", ".join(cambios))
        sincronizar_paciente(pid, p["dni"], cambios)
        flash("Datos del protocolo actualizados.", "ok")
    return redirect(url_for("protocolos.protocolo", pid=pid))


@bp.route("/buscar")
@requiere_login
def buscar_protocolo():
    texto = request.args.get("q", "").strip()
    if not texto:
        return redirect(url_for("tablero.tablero"))
    m = re.fullmatch(r"[cC]?\s*0*(\d{1,6})", texto)
    numero = numero_protocolo(int(m.group(1))) if m and int(m.group(1)) > 0 else texto
    p = db.uno("SELECT id FROM protocolos WHERE numero=?", (numero,)) or db.uno("SELECT id FROM protocolos WHERE LOWER(numero)=?", (texto.lower(),))
    if p:
        return redirect(url_for("protocolos.protocolo", pid=p["id"]))
    if m:
        flash(f"No existe el protocolo {numero}.", "error")
        return redirect(url_for("tablero.tablero"))
    return redirect(url_for("tablero.tablero", ver="todos", q=texto))


@bp.route("/protocolo/<int:pid>")
@requiere_login
def protocolo(pid):
    db.precargar([(SQL_PROTOCOLO, (pid,)), (SQL_HISTORIAL_PROTOCOLO, (pid,)), (SQL_INFORME_EMITIDO, (pid,)),
                   (SQL_COMENTARIOS, (pid,)), (SQL_IMAGENES, (pid,)), (SQL_TAREAS, (pid,)), (SQL_USUARIOS_SECTORES, ()), (SQL_ORDENES, (pid,))] + consultas_estudios("e.protocolo_id=?", (pid,), True))
    p = protocolo_o_404(pid)
    historial = db.q(SQL_HISTORIAL_PROTOCOLO, (pid,))
    estudios = cargar_estudios("e.protocolo_id=?", (pid,), borradores=True)
    pendientes = []
    for x in estudios:
        if not x["anulado"] and x["proxima"] and (x["tipo"], x["proxima"][1]) not in [(q[0], q[1]) for q in pendientes]:
            pendientes.append((x["tipo"], x["proxima"][1], TIPOS[x["tipo"]]))
    return render_template("protocolos/protocolo.html", p=p, estudios=estudios, historial=historial, listas=listas(), comentarios=comentarios_de(pid), imagenes=imagenes_de(pid), tareas=tareas_de(pid), ordenes=ordenes_de(pid), usuarios_tarea=usuarios_con_sectores(),
                           ubicaciones=ubicaciones_del_protocolo(p), flujos_malignidad=malignidad_por_flujo(estudios), malignidades=mensajeria.MALIGNIDADES,
                           emitido=informe_emitido(pid),
                           flujos=flujos_de([pid]).get(pid, ""),
                           informe_listo=bool(estudios) and not p["borrador"] and not p["pendiente_validacion"] and not pendientes and any(not x["anulado"] for x in estudios),
                           pendientes=pendientes, informe_vigente=informe_vigente(pid, informe_emitido(pid)))


@bp.route("/protocolo/<int:pid>/malignidad", methods=["POST"])
@requiere_permiso("micro", "informe")
def malignidad_asignar(pid):
    yo = usuario_actual()
    protocolo_o_404(pid)
    tipo = request.form.get("tipo", "")
    valor = request.form.get("valor", "")
    volver = redirect(url_for("protocolos.protocolo", pid=pid) + "#malignidad")
    if tipo not in TIPOS or (valor and valor not in mensajeria.NOMBRE_MALIGNIDAD):
        flash("Elegí una malignidad válida.", "error")
        return volver
    activos = [x for x in cargar_estudios("e.protocolo_id=?", (pid,), borradores=True) if x["tipo"] == tipo and not x["anulado"]]
    if not activos or any(x["borrador"] or x["proxima"] for x in activos):
        flash("La malignidad se asigna cuando los estudios están informados.", "error")
        return volver
    db.ex("UPDATE estudios SET malignidad=? WHERE protocolo_id=? AND tipo=? AND anulado=0", (valor or None, pid, tipo))
    nombre = mensajeria.NOMBRE_MALIGNIDAD.get(valor, "sin malignidad")
    db.auditar(yo["id"], pid, "malignidad", f"{TIPOS[tipo]}: {nombre}")
    flash(f"Malignidad de {TIPOS[tipo].lower()}: {nombre.lower()}.", "ok")
    return volver


@bp.route("/protocolo/<int:pid>/comentario", methods=["POST"])
@requiere_login
def comentario_nuevo(pid):
    protocolo_o_404(pid)
    texto = request.form.get("texto", "").strip()
    if not texto:
        flash("Escribí el comentario.", "error")
    elif len(texto) > 2000:
        flash("El comentario es demasiado largo (máximo 2000 caracteres).", "error")
    else:
        db.ex("INSERT INTO comentarios (protocolo_id, usuario_id, fecha_hora, texto) VALUES (?,?,?,?)",
              (pid, usuario_actual()["id"], db.ahora(), texto))
        db.auditar(usuario_actual()["id"], pid, "comentario", texto[:60] + ("…" if len(texto) > 60 else ""))
        flash("Comentario agregado.", "ok")
    return volver_a_comentarios(pid)


@bp.route("/comentario/<int:cid>/borrar", methods=["POST"])
@requiere_login
def comentario_borrar(cid):
    yo = usuario_actual()
    c = db.uno("SELECT * FROM comentarios WHERE id=?", (cid,)) or abort(404)
    if c["usuario_id"] != yo["id"] and not yo["admin"]:
        flash("Solo podés borrar tus propios comentarios.", "error")
    else:
        db.ex("DELETE FROM comentarios WHERE id=?", (cid,))
        db.auditar(yo["id"], c["protocolo_id"], "comentario_borrado", c["texto"][:60] + ("…" if len(c["texto"]) > 60 else ""))
        flash("Comentario borrado.", "ok")
    return volver_a_comentarios(c["protocolo_id"])


@bp.route("/protocolo/<int:pid>/sistema", methods=["POST"])
@requiere_permiso("sistema")
def cargado_sistema(pid):
    protocolo_o_404(pid)
    cargado = 1 if request.form.get("cargado_sistema") == "1" else 0
    db.ex("UPDATE protocolos SET protocolo_sistema=?, cargado_sistema=? WHERE id=?",
          (request.form.get("protocolo_sistema", "").strip(), cargado, pid))
    db.auditar(usuario_actual()["id"], pid, "sistema", "cargado" if cargado else "no cargado")
    flash("Datos de carga en el sistema actualizados.", "ok")
    return redirect(url_for("protocolos.protocolo", pid=pid))
