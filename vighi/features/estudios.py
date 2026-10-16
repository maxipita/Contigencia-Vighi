from datetime import datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from vighi.core import db
from vighi.core.fechas import hoy
from vighi.core.sesion import puede, requiere_login, requiere_permiso, usuario_actual
from vighi.dominio import trazabilidad
from vighi.dominio.estudios import NOMBRE_ETAPA, PASOS_IHQ, REGISTRO, con_decal, validar_combinacion
from vighi.servicios.catalogo import muestra_para, muestras_posibles, sitios_posibles
from vighi.servicios.consultas import SQL_LISTAS, SQL_VARIANTE, cargar_estudios, consultas_estudios, etiqueta, flujo_avanzado, flujos_de, listas, miembros_flujo, protocolo_cerrado, responsables, SQL_RESPONSABLES
from vighi.servicios.fichas import FRAGMENTOS_VARIOS, INCLUSION_POR_LOTE, INCLUSIONES, OPCIONES_FRAGMENTOS, auditar_autoguardado, SQL_FICHA, SQL_HISTORIAL_ESTUDIO, SQL_TECNICAS, SQL_TEMPLATES, SQL_ULTIMA_ETAPA, con_permiso, consultas_ficha, entero_positivo, estudios_sin_tecnicas, ficha, fragmentos_de, guardar_seccion, habilitada, lista_marcadores, macro_editable, motivo_no_listo, pedido_ihq_confirmado, rotulo_fragmentos, sumar_cassettes
from vighi.servicios.imagenes import SQL_IMAGENES, imagenes_de
from vighi.servicios.lotes import asignar_lote, avisar_lote_lleno, concretar_lote, lote_del_protocolo, lotes_para_formulario, primer_estudio, ubicar_en_lote, validar_lote, SQL_LOTES_ABIERTOS
from vighi.servicios.tareas import cerrar_por_etapa, crear_tarea, tipo_solicitud_ihq
from vighi.servicios.protocolos import CAMPOS_ESTUDIO, SQL_COMENTARIOS, comentarios_de, contexto_formulario, crear_estudio, estudios_del_formulario, leer_estudio, opciones_de_edicion, protocolo_o_404, recordar_tecnicas, sin_repetidos, validar_estudios

bp = Blueprint("estudios", __name__)


@bp.route("/protocolo/<int:pid>/estudio/nuevo", methods=["GET", "POST"])
@requiere_permiso("protocolo_editar")
def estudio_nuevo(pid):
    yo = usuario_actual()
    p = protocolo_o_404(pid)
    existentes = [dict(e) for e in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=?", (pid,))]
    lista = [{"tipo": request.args["tipo"]}] if request.args.get("tipo") in REGISTRO else []
    if request.method == "POST":
        lista = estudios_del_formulario()
        lote_del_prot = lote_del_protocolo(pid)
        lote_valor, error = validar_estudios(lista, existentes, con_lote=not primer_estudio(pid))
        if not lista:
            error = "Elegí qué estudio agregar."
        for e in lista:
            if not error and (avance := flujo_avanzado(pid, e["tipo"])):
                error = (f"Ya hay {REGISTRO[e['tipo']].nombre.lower()} de este protocolo en proceso (llegó a {avance}) y comparten el mismo flujo: "
                         "para sumar otra hay que deshacer las etapas antes.")
        if error:
            flash(error, "error")
        else:
            lote = lote_del_prot if primer_estudio(pid) else concretar_lote(lote_valor, yo["id"])
            for e in lista:
                crear_estudio(pid, e, lote, yo["id"])
            avisar_lote_lleno(ubicar_en_lote(pid, yo["id"]))
            flash(f"Se agregó {', '.join(etiqueta(e) for e in lista)} al protocolo {p['numero']}.", "ok")
            return redirect(url_for("protocolos.protocolo", pid=pid))
    lote_fijo = lote_del_protocolo(pid)
    return render_template("estudios/estudio_form.html", p=p, estudios=lista, editando=None, lote_editable=not primer_estudio(pid),
                           lote_fijo=lote_fijo["codigo"] if lote_fijo else None, **contexto_formulario())


@bp.route("/estudio/<int:eid>/editar", methods=["GET", "POST"])
@requiere_permiso("protocolo_editar")
def estudio_editar(eid):
    yo = usuario_actual()
    actual = db.uno("SELECT * FROM estudios WHERE id=?", (eid,)) or abort(404)
    p = protocolo_o_404(actual["protocolo_id"])
    e = dict(actual)
    primero = primer_estudio(p["id"])
    es_primero = bool(primero and primero["id"] == eid)
    if request.method == "POST":
        e = {**leer_estudio("e-0-", actual["tipo"]), "id": eid}
        otros = [dict(x) for x in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=? AND id<>?",
                                       (p["id"], eid))]
        lote_valor, error = validar_estudios([{**e, "anulado": actual["anulado"]}], otros, actual["lote_id"], con_lote=es_primero)
        if error:
            flash(error, "error")
        else:
            db.ex(f"UPDATE estudios SET {', '.join(k + '=?' for k in CAMPOS_ESTUDIO)} WHERE id=?",
                  [e[k] for k in CAMPOS_ESTUDIO] + [eid])
            recordar_tecnicas(e)
            db.auditar(yo["id"], p["id"], "editar_estudio", etiqueta(e), eid)
            if es_primero:
                asignar_lote(p["id"], concretar_lote(lote_valor, yo["id"]), yo["id"])
            avisar_lote_lleno(ubicar_en_lote(p["id"], yo["id"]))
            flash("Datos del estudio actualizados.", "ok")
            return redirect(url_for("estudios.estudio", eid=eid))
    else:
        e["lote_sel"] = str(actual["lote_id"] or "")
    ctx = contexto_formulario()
    ctx["lotes_abiertos"][actual["tipo"]] = lotes_para_formulario(actual["tipo"], actual["lote_id"])
    lote_fijo = lote_del_protocolo(p["id"])
    return render_template("estudios/estudio_form.html", p=p, estudios=[e], editando=eid, lote_editable=es_primero,
                           lote_fijo=lote_fijo["codigo"] if lote_fijo else None, **ctx)


def estudio_para_modificar(eid):
    e = db.uno("SELECT * FROM estudios WHERE id=?", (eid,)) or abort(404)
    destino = redirect(url_for("estudios.estudio", eid=eid))
    if e["anulado"]:
        flash("El estudio está anulado: no se puede modificar.", "error")
        return None, destino
    return e, destino


def registrar_cambio(e, accion, detalle):
    db.auditar(usuario_actual()["id"], e["protocolo_id"], accion, detalle, e["id"])
    avisar_lote_lleno(ubicar_en_lote(e["protocolo_id"], usuario_actual()["id"]))


@bp.route("/estudio/<int:eid>/muestra", methods=["POST"])
@requiere_permiso("protocolo_editar")
def estudio_muestra(eid):
    e, destino = estudio_para_modificar(eid)
    nuevo = request.form.get("tipo_muestra", "").strip()
    if not e:
        return destino
    if nuevo not in muestras_posibles(e):
        flash("Elegí un tipo de muestra de la lista.", "error")
    elif nuevo != (e["tipo_muestra"] or ""):
        db.ex("UPDATE estudios SET tipo_muestra=? WHERE id=?", (nuevo, eid))
        db.auditar(usuario_actual()["id"], e["protocolo_id"], "cambiar_muestra", f"{etiqueta(e)}: {e['tipo_muestra'] or 'sin tipo'} → {nuevo}", eid)
        flash(f"Tipo de muestra cambiado a «{nuevo}».", "ok")
    return destino


@bp.route("/estudio/<int:eid>/sitio", methods=["POST"])
@requiere_permiso("protocolo_editar")
def estudio_sitio(eid):
    e, destino = estudio_para_modificar(eid)
    nuevo = request.form.get("sitio", "").strip()
    if not e:
        return destino
    if nuevo not in sitios_posibles(e):
        flash("Elegí un órgano de la lista.", "error")
    elif nuevo != (e["sitio"] or ""):
        muestra = muestra_para(e, nuevo)
        db.ex("UPDATE estudios SET sitio=?, tipo_muestra=? WHERE id=?", (nuevo, muestra, eid))
        registrar_cambio(e, "cambiar_sitio", f"{etiqueta(e)}: {e['sitio'] or 'sin órgano'} → {nuevo}" + (f" (muestra: {muestra})" if muestra != (e["tipo_muestra"] or "") else ""))
        flash(f"Órgano cambiado a «{nuevo}»." + (f" La muestra pasó a «{muestra}»: revisala si hace falta." if muestra != (e["tipo_muestra"] or "") else ""), "ok")
    return destino


@bp.route("/estudio/<int:eid>/cantidad", methods=["POST"])
@requiere_permiso("protocolo_editar")
def estudio_cantidad(eid):
    e, destino = estudio_para_modificar(eid)
    nuevo = request.form.get("cantidad", "").strip()
    if not e:
        return destino
    if nuevo not in REGISTRO[e["tipo"]].cantidades:
        flash("Elegí una cantidad de la lista.", "error")
    elif nuevo != (e["cantidad"] or ""):
        db.ex("UPDATE estudios SET cantidad=? WHERE id=?", (nuevo, eid))
        registrar_cambio(e, "cambiar_cantidad", f"{etiqueta(e)}: {e['cantidad'] or '—'} → {nuevo} {REGISTRO[e['tipo']].etiqueta_cantidad}")
        flash(f"Cantidad cambiada a {nuevo} {REGISTRO[e['tipo']].etiqueta_cantidad}.", "ok")
    return destino


@bp.route("/estudio/<int:eid>/responsable", methods=["POST"])
@requiere_permiso("protocolo_editar")
def estudio_responsable(eid):
    e, destino = estudio_para_modificar(eid)
    if not e:
        return destino
    posibles = {str(r["id"]): r["iniciales"] for r in responsables(e["tipo"])}
    nuevo = request.form.get("responsable_id", "")
    if nuevo not in posibles:
        flash("Elegí un responsable de la lista.", "error")
    elif nuevo != str(e["responsable_id"] or ""):
        antes = db.uno("SELECT iniciales FROM usuarios WHERE id=?", (e["responsable_id"],)) if e["responsable_id"] else None
        db.ex("UPDATE estudios SET responsable_id=? WHERE id=?", (int(nuevo), eid))
        db.auditar(usuario_actual()["id"], e["protocolo_id"], "cambiar_responsable", f"{etiqueta(e)}: {antes['iniciales'] if antes else '—'} → {posibles[nuevo]}", eid)
        flash(f"Responsable cambiado a {posibles[nuevo]}.", "ok")
    return destino


@bp.route("/estudio/<int:eid>/lote", methods=["POST"])
@requiere_permiso("protocolo_editar")
def estudio_lote(eid):
    e, destino = estudio_para_modificar(eid)
    if not e:
        return destino
    primero = primer_estudio(e["protocolo_id"])
    if not primero or primero["id"] != eid:
        flash("El lote es de todo el protocolo: se cambia desde su primer estudio.", "error")
        return destino
    valor, error = validar_lote(request.form.get("lote_id", ""), e["tipo"], e["lote_id"])
    if error:
        flash(error, "error")
        return destino
    yo = usuario_actual()
    asignar_lote(e["protocolo_id"], concretar_lote(valor, yo["id"]), yo["id"])
    avisar_lote_lleno(ubicar_en_lote(e["protocolo_id"], yo["id"]))
    flash("Lote del protocolo actualizado.", "ok")
    return destino


@bp.route("/protocolo/<int:pid>/flujo/<tipo>")
@requiere_login
def flujo(pid, tipo):
    fila = db.uno("""SELECT e.id FROM estudios e JOIN flujos f ON f.id=e.flujo_id WHERE f.protocolo_id=? AND f.tipo=?
                     ORDER BY e.anulado, e.id LIMIT 1""", (pid, tipo))
    if not fila:
        abort(404)
    return estudio(fila["id"])


@bp.route("/estudio/<int:eid>")
@requiere_login
def estudio(eid):
    db.precargar(consultas_ficha(eid) + ([(SQL_RESPONSABLES, ()), (SQL_LOTES_ABIERTOS, (hoy(),))] if puede("protocolo_editar") else []) + [(SQL_ULTIMA_ETAPA, (eid,)), (SQL_HISTORIAL_ESTUDIO, (eid,)), (SQL_TEMPLATES, ("macro",)),
                                         (SQL_TEMPLATES, ("micro",)), (SQL_LISTAS, ()), ("SELECT fecha FROM feriados", ())])
    primero = db.uno(SQL_FICHA, (eid,))
    if primero:
        db.precargar([(SQL_VARIANTE, (primero["protocolo_id"], primero["tipo"], primero["protocolo_id"], primero["tipo"])), (SQL_COMENTARIOS, (primero["protocolo_id"],)), (SQL_IMAGENES, (primero["protocolo_id"],)), (SQL_TECNICAS, (primero["protocolo_id"], primero["tipo"]))] + consultas_estudios("e.protocolo_id=?", (primero["protocolo_id"],), True))
    e, macro, micro, ihq, etapas, solicita = ficha(eid)
    tipo = REGISTRO[e["tipo"]]
    est, prox = tipo.estado(set(etapas), solicita, bool(e["anulado"]))
    ultima = db.uno(SQL_ULTIMA_ETAPA, (eid,))
    historial = db.q(SQL_HISTORIAL_ESTUDIO, (eid,))
    tpl = lambda clase: db.q(SQL_TEMPLATES, (clase,))
    pasos = tipo.flujo(solicita)
    decal = con_decal(solicita)
    traza_enc, traza = trazabilidad.calcular(e, pasos, etapas, db.feriados(), decal=decal)
    hermanos = cargar_estudios("e.protocolo_id=?", (e["protocolo_id"],), borradores=True)
    activos = [h for h in hermanos if not h["anulado"]]
    miembros = [h for h in hermanos if h["id"] == e["id"]] if e["anulado"] else [h for h in activos if h["tipo"] == e["tipo"]]
    pestanas, vistos = [], set()
    for h in hermanos:
        if h["anulado"]:
            pestanas.append({"id": h["id"], "texto": f"{h['etiqueta']} (anulado)", "activa": e["anulado"] and h["id"] == e["id"], "anulado": True})
        elif h["tipo"] not in vistos:
            vistos.add(h["tipo"])
            n = sum(1 for x in activos if x["tipo"] == h["tipo"])
            pestanas.append({"id": h["id"], "texto": h["etiqueta"] if n == 1 else f"{REGISTRO[h['tipo']].nombre} ({n} estudios)",
                             "activa": not e["anulado"] and h["tipo"] == e["tipo"], "anulado": False})
    limite_etapa = trazabilidad.limite(e["tipo"], prox[0], e["fecha_recoleccion"] or e["creado_en"], db.feriados(), decal) if prox and not e["anulado"] and not e["borrador"] else None
    semaforo = (trazabilidad.semaforo_acumulado(e["tipo"], e["fecha_recoleccion"] or e["creado_en"],
                                                {"ingreso": e["creado_en"], **{k: v["fecha_hora"] for k, v in etapas.items()}}, limite_etapa, datetime.now(), db.feriados(), decal)
                if limite_etapa else "")
    cierra_protocolo = bool(prox and not e["anulado"] and prox[0] == tipo.ultima_etapa(solicita)
                            and all(not h["proxima"] and not h["borrador"] for h in activos if h["tipo"] != e["tipo"]))
    tecnicas = db.q(SQL_TECNICAS, (e["protocolo_id"], e["tipo"])) if "macro" in tipo.secciones and not e["anulado"] else []
    return render_template("estudios/estudio.html", ihq_confirmado=pedido_ihq_confirmado(micro, ihq), marcadores_ihq=lista_marcadores(ihq["marcadores"] if ihq else ""), INCLUSION_POR_LOTE=INCLUSION_POR_LOTE, FRAGMENTOS_VARIOS=FRAGMENTOS_VARIOS, OPCIONES_FRAGMENTOS=OPCIONES_FRAGMENTOS, ed=opciones_de_edicion(hermanos) if not e["borrador"] else opciones_de_edicion([]), tecnicas=tecnicas, sin_tecnicas={m["id"] for m in estudios_sin_tecnicas(miembros)}, e=e, miembros=miembros, pestanas=pestanas, comentarios=comentarios_de(e["protocolo_id"]), imagenes=imagenes_de(e["protocolo_id"]), cierra_protocolo=cierra_protocolo, semaforo=semaforo,
                           flujos=flujos_de([e["protocolo_id"]]).get(e["protocolo_id"], ""), tipo=tipo, macro=macro, micro=micro, ihq=ihq, etapas=etapas, estado=est,
                           prox=prox, ultima=ultima, historial=historial, traza=traza, traza_enc=traza_enc,
                           hermanos=hermanos, etiqueta=etiqueta(e) if len(miembros) < 2 else tipo.nombre,
                           tpl_macro=tpl("macro"), tpl_micro=tpl("micro"), bethesda=listas().get("bethesda", []),
                           tecnicas_pedidas=sin_repetidos(x.strip() for m in miembros for x in (m["tecnicas_especiales"] or "").split(";")),
                           lista_ihq=listas().get("ihq_marcadores", []),
                           filtro_templates={"zona": e["subcategoria"] or "", "organo": e["sitio"] or "", "tipo": e["tipo_muestra"] or ""},
                           ihq_hecha=any(k in etapas for k in PASOS_IHQ),
                           edita_macro=macro_editable(e, etapas, solicita),
                           decal_cambiable=macro_editable(e, etapas, solicita)[0] and "procesamiento" not in etapas and "decal" not in etapas,
                           edita_micro=con_permiso("micro", habilitada(e, etapas, solicita, "microscopia")))


@bp.route("/estudio/<int:eid>/macro", methods=["POST"])
@requiere_permiso("macro", "micro")
def guardar_macro(eid):
    e, macro, _, _, etapas, solicita = ficha(eid)
    ok, motivo = macro_editable(e, etapas, solicita)
    auto = request.form.get("autoguardar") == "1"
    if "macro" not in REGISTRO[e["tipo"]].secciones or not ok:
        if auto:
            return jsonify(ok=False, error=motivo or "este estudio no tiene macroscopía"), 409
        flash(f"No se guardó: {motivo or 'este estudio no tiene macroscopía.'}", "error")
        return redirect(url_for("estudios.estudio", eid=eid) + "#macro")
    valores = {"template": request.form.get("template", "").strip(),
               "descripcion": request.form.get("descripcion", "").strip()}
    detalle = ""
    if auto:
        guardar_seccion("macro", e["flujo_id"], valores)
        auditar_autoguardado(usuario_actual(), e, "guardar_macro")
        return jsonify(ok=True, hora=datetime.now().strftime("%H:%M"))
    if request.form.get("decal_presente") == "1" and "procesamiento" not in etapas and "decal" not in etapas:
        decal = 1 if request.form.get("decal") == "1" else 0
        valores["decal"] = decal
        if decal != (1 if macro and macro["decal"] else 0):
            detalle = "agrega Macro > Decal" if decal else "quita Macro > Decal"
    guardar_seccion("macro", e["flujo_id"], valores)
    db.auditar(usuario_actual()["id"], e["protocolo_id"], "guardar_macro", detalle, eid)
    flash("Macroscopía guardada.", "ok")
    if request.form.get("y_listo"):
        return marcar_listo(eid, "macroscopia")
    return redirect(url_for("estudios.estudio", eid=eid) + "#macro")


@bp.route("/estudio/<int:eid>/tecnicas", methods=["POST"])
@requiere_permiso("macro", "micro")
def tecnica_nueva(eid):
    e, _, _, _, etapas, solicita = ficha(eid)
    ok, motivo = macro_editable(e, etapas, solicita)
    destino = url_for("estudios.estudio", eid=eid) + "#tecnicas"
    if "macro" not in REGISTRO[e["tipo"]].secciones or not ok:
        flash(f"No se guardó: {motivo or 'este estudio no tiene macroscopía.'}", "error")
        return redirect(destino)
    miembro = db.uno("SELECT id FROM estudios WHERE id=? AND protocolo_id=? AND tipo=? AND anulado=0",
                     (request.form.get("estudio_id", "") if request.form.get("estudio_id", "").isdigit() else 0, e["protocolo_id"], e["tipo"]))
    inclusion = request.form.get("inclusion", "")
    fragmentos, cassettes = fragmentos_de(request.form.get("fragmentos")), entero_positivo(request.form.get("cassettes"))
    numero = request.form.get("numero", "").strip()[:10]
    if not miembro:
        flash("Elegí el estudio de la técnica.", "error")
    elif inclusion not in INCLUSIONES:
        flash("Elegí el tipo de inclusión.", "error")
    elif not numero or not fragmentos or not cassettes:
        flash("Completá el número, los fragmentos y los cassettes de la técnica.", "error")
    else:
        tacos = cargar_estudios("e.id=?", (miembro["id"],))[0]["tacos"]
        db.ex("""INSERT INTO tecnicas (estudio_id, numero, fragmentos, inclusion, tacos, cassettes, comentarios, usuario_id, creado_en)
                 VALUES (?,?,?,?,?,?,?,?,?)""", (miembro["id"], numero, fragmentos, inclusion, tacos, cassettes,
                                                  request.form.get("comentarios", "").strip()[:300], usuario_actual()["id"], db.ahora()))
        sumar_cassettes(e)
        db.auditar(usuario_actual()["id"], e["protocolo_id"], "tecnica", f"{numero}: {inclusion}, {rotulo_fragmentos(fragmentos).lower()} fragm., {cassettes} cassette(s)", miembro["id"])
        miembros = miembros_flujo(e)
        faltan = estudios_sin_tecnicas(miembros)
        if faltan and len(miembros) > 1:
            letra = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[[m["id"] for m in miembros].index(faltan[0]["id"]) % 26]
            flash(f"Técnica agregada. Sigue la de {letra}) {etiqueta(faltan[0])}.", "ok")
        else:
            flash("Técnica agregada." + (" Ya están las técnicas de todas las muestras." if len(miembros) > 1 else ""), "ok")
    return redirect(destino)


@bp.route("/tecnica/<int:tid>/borrar", methods=["POST"])
@requiere_permiso("macro", "micro")
def tecnica_borrar(tid):
    t = db.uno("SELECT id, estudio_id, numero FROM tecnicas WHERE id=?", (tid,)) or abort(404)
    e, _, _, _, etapas, solicita = ficha(t["estudio_id"])
    ok, motivo = macro_editable(e, etapas, solicita)
    destino = url_for("estudios.estudio", eid=t["estudio_id"]) + "#tecnicas"
    if not ok:
        flash(f"No se borró: {motivo}", "error")
        return redirect(destino)
    db.ex("DELETE FROM tecnicas WHERE id=?", (tid,))
    sumar_cassettes(e)
    db.auditar(usuario_actual()["id"], e["protocolo_id"], "tecnica_borrada", t["numero"] or "", t["estudio_id"])
    flash("Técnica borrada.", "ok")
    return redirect(destino)


@bp.route("/estudio/<int:eid>/micro", methods=["POST"])
@requiere_permiso("micro")
def guardar_micro(eid):
    e, _, micro, _, etapas, solicita = ficha(eid)
    ok, motivo = habilitada(e, etapas, solicita, "microscopia")
    auto = request.form.get("autoguardar") == "1"
    if not ok:
        if auto:
            return jsonify(ok=False, error=motivo), 409
        flash(f"No se guardó: {motivo}", "error")
        return redirect(url_for("estudios.estudio", eid=eid) + "#micro")
    if auto:
        guardar_seccion("micro", e["flujo_id"], {"template": request.form.get("template", "").strip(), "descripcion": request.form.get("descripcion", "").strip(),
                                              "conclusion": request.form.get("conclusion", "").strip(), "bethesda": request.form.get("bethesda", "").strip()})
        auditar_autoguardado(usuario_actual(), e, "guardar_micro")
        return jsonify(ok=True, hora=datetime.now().strftime("%H:%M"))
    guardar_seccion("micro", e["flujo_id"], {"template": request.form.get("template", "").strip(),
                                          "descripcion": request.form.get("descripcion", "").strip(),
                                          "conclusion": request.form.get("conclusion", "").strip(),
                                          "bethesda": request.form.get("bethesda", "").strip()})
    db.auditar(usuario_actual()["id"], e["protocolo_id"], "guardar_micro", "", eid)
    flash("Microscopía guardada.", "ok")
    if request.form.get("y_listo"):
        return marcar_listo(eid, "microscopia")
    return redirect(url_for("estudios.estudio", eid=eid) + "#micro")


@bp.route("/estudio/<int:eid>/ihq", methods=["POST"])
@requiere_permiso("micro")
def guardar_ihq(eid):
    e, _, micro, ihq, _, _ = ficha(eid)
    confirmado = pedido_ihq_confirmado(micro, ihq)
    if confirmado:
        guardar_seccion("ihq", e["flujo_id"], {"resultado": request.form.get("resultado", "").strip()})
    else:
        guardar_seccion("ihq", e["flujo_id"], {"marcadores": ", ".join(lista_marcadores(request.form.get("marcadores", "")))})
    if request.form.get("autoguardar") == "1":
        auditar_autoguardado(usuario_actual(), e, "guardar_ihq")
        return jsonify(ok=True, hora=datetime.now().strftime("%H:%M"))
    db.auditar(usuario_actual()["id"], e["protocolo_id"], "guardar_ihq", "", eid)
    flash("IHQ guardada.", "ok")
    if request.form.get("y_listo") and confirmado:
        return marcar_listo(eid, "interp_ihq")
    return redirect(url_for("estudios.estudio", eid=eid) + "#ihq")


@bp.route("/estudio/<int:eid>/ihq/pedir", methods=["POST"])
@requiere_permiso("micro")
def ihq_pedir(eid):
    yo = usuario_actual()
    e, _, micro, ihq, etapas, solicita = ficha(eid)
    destino = url_for("estudios.estudio", eid=eid) + "#ihq"
    ok, motivo = habilitada(e, etapas, solicita, "microscopia")
    ok = ok or ("microscopia" in etapas and not e["anulado"])
    marcadores = lista_marcadores(request.form.get("marcadores", "") or (ihq["marcadores"] if ihq else ""))
    if "ihq" not in REGISTRO[e["tipo"]].secciones:
        flash("Este tipo de estudio no lleva IHQ.", "error")
    elif pedido_ihq_confirmado(micro, ihq):
        flash("El pedido de IHQ ya estaba confirmado: no se cambió nada.", "ok")
    elif not ok:
        flash(f"No se pudo confirmar el pedido: {motivo}", "error")
    elif not marcadores:
        flash("Elegí al menos un marcador antes de confirmar el pedido.", "error")
    else:
        guardar_seccion("ihq", e["flujo_id"], {"marcadores": ", ".join(marcadores), "pedido_en": db.ahora(), "pedido_por": yo["id"]})
        guardar_seccion("micro", e["flujo_id"], {"solicita_ihq": 1})
        tipo_tarea = tipo_solicitud_ihq()
        descripcion = (f"Marcadores pedidos ({len(marcadores)}):\n" + "\n".join(f"- {m}" for m in marcadores))[:2000]
        crear_tarea(e["protocolo_id"], tipo_tarea, descripcion, "regular", "media", tipo_tarea["responsable_id"], yo["id"])
        db.auditar(yo["id"], e["protocolo_id"], "pedido_ihq", ", ".join(marcadores), eid)
        quien = db.uno("SELECT iniciales FROM usuarios WHERE id=?", (tipo_tarea["responsable_id"],)) if tipo_tarea["responsable_id"] else None
        flash(f"Pedido de IHQ confirmado ({len(marcadores)} marcador(es)). " + (f"Se creó la tarea «{tipo_tarea['titulo']}» para {quien['iniciales']}."
              if quien else f"Se creó la tarea «{tipo_tarea['titulo']}» sin responsable: asignalo en Responsables de tareas."), "ok")
    return redirect(destino)


@bp.route("/estudio/<int:eid>/listo/<etapa>", methods=["POST"])
@requiere_permiso("etapas")
def marcar_listo(eid, etapa):
    yo = usuario_actual()
    e, macro, micro, ihq, etapas, solicita = ficha(eid)
    if e["borrador"]:
        flash("Primero completá los datos del paciente de este protocolo.", "error")
        return redirect(url_for("protocolos.protocolo_editar", pid=e["protocolo_id"]))
    tipo = REGISTRO[e["tipo"]]
    _, prox = tipo.estado(set(etapas), solicita, bool(e["anulado"]))
    miembros = miembros_flujo(e)
    sin = estudios_sin_tecnicas(miembros) if etapa == "macroscopia" and "macro" in tipo.secciones else []
    motivo = motivo_no_listo(yo, e["tipo"], etapa, prox, solicita, macro, micro, ihq, sin)
    if motivo:
        flash(motivo, "error")
    else:
        ahora_ = db.ahora()
        if not db.uno("SELECT 1 FROM etapas WHERE flujo_id=? AND etapa=?", (e["flujo_id"], etapa)):
            db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (e["flujo_id"], etapa, yo["id"], ahora_))
        db.auditar(yo["id"], e["protocolo_id"], "listo", NOMBRE_ETAPA[etapa] + (f" (en {len(miembros)} estudios {tipo.nombre.lower()})" if len(miembros) > 1 else ""), eid)
        flash(f"✔ {NOMBRE_ETAPA[etapa]} registrada por {yo['iniciales']}"
              + (f" en los {len(miembros)} estudios de {tipo.nombre.lower()} del protocolo." if len(miembros) > 1 else "."), "ok")
        if cerrar_por_etapa(e["protocolo_id"], etapa, NOMBRE_ETAPA[etapa], yo["id"]):
            flash("Se cerraron las tareas que esperaban esta etapa.", "ok")
        if request.form.get("firmar_yo") == "1" and protocolo_cerrado(e["protocolo_id"]):
            db.ex("UPDATE protocolos SET firmante_id=? WHERE id=?", (yo["id"], e["protocolo_id"]))
            db.auditar(yo["id"], e["protocolo_id"], "firmante", f"{yo['iniciales']} firmará el informe", eid)
            flash("Vas a figurar como firmante del informe.", "ok")
    return redirect(request.form.get("volver") or url_for("estudios.estudio", eid=eid))


@bp.route("/estudio/<int:eid>/deshacer", methods=["POST"])
@requiere_permiso("etapas")
def deshacer(eid):
    yo = usuario_actual()
    e = ficha(eid)[0]
    ultima = db.uno("SELECT * FROM etapas WHERE flujo_id=? ORDER BY fecha_hora DESC, id DESC LIMIT 1", (e["flujo_id"],))
    if not ultima:
        flash("No hay etapas para deshacer.", "error")
    elif ultima["usuario_id"] != yo["id"] and not puede("etapas_deshacer"):
        flash("Solo quien la registró o alguien con permiso puede deshacer la etapa.", "error")
    else:
        db.ex("DELETE FROM etapas WHERE flujo_id=? AND etapa=?", (e["flujo_id"], ultima["etapa"]))
        db.ex("UPDATE protocolos SET firmante_id=NULL WHERE id=?", (e["protocolo_id"],))
        db.auditar(yo["id"], e["protocolo_id"], "deshacer", NOMBRE_ETAPA.get(ultima["etapa"], ultima["etapa"]), eid)
        flash(f"Se deshizo {NOMBRE_ETAPA.get(ultima['etapa'])}.", "ok")
    return redirect(url_for("estudios.estudio", eid=eid))


@bp.route("/estudio/<int:eid>/anular", methods=["POST"])
@requiere_permiso("estudio_anular")
def anular(eid):
    e = ficha(eid)[0]
    motivo = request.form.get("motivo", "").strip()
    nuevo = 0 if e["anulado"] else 1
    otros = [dict(x) for x in db.q("SELECT tipo, subcategoria, anulado FROM estudios WHERE protocolo_id=? AND id<>?",
                                   (e["protocolo_id"], eid))]
    if nuevo and not motivo:
        flash("Indicá el motivo de la anulación.", "error")
    elif not nuevo and (error := validar_combinacion(otros + [{"tipo": e["tipo"], "subcategoria": e["subcategoria"]}])):
        flash(f"No se puede reactivar: {error}", "error")
    elif not nuevo and (avance := flujo_avanzado(e["protocolo_id"], e["tipo"])):
        flash(f"No se puede reactivar: hay {REGISTRO[e['tipo']].nombre.lower()} de este protocolo en proceso (llegó a {avance}) y comparten el mismo "
              "flujo. Primero hay que deshacer las etapas.", "error")
    else:
        db.ex("UPDATE estudios SET anulado=?, motivo_anulacion=? WHERE id=?", (nuevo, motivo if nuevo else None, eid))
        db.olvidar_cache()
        db.auditar(usuario_actual()["id"], e["protocolo_id"], "anular" if nuevo else "reactivar", motivo, eid)
        flash("Estudio anulado." if nuevo else "Estudio reactivado.", "ok")
        if not nuevo:
            avisar_lote_lleno(ubicar_en_lote(e["protocolo_id"], usuario_actual()["id"]))
    if request.form.get("volver") == "protocolo":
        return redirect(url_for("protocolos.protocolo", pid=e["protocolo_id"]))
    return redirect(url_for("estudios.estudio", eid=eid))
