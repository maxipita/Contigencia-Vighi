import io
from urllib.parse import quote

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, url_for

from vighi.core import db
from vighi.core.sesion import requiere_admin, requiere_permiso, usuario_actual
from vighi.servicios import mensajeria
from vighi.servicios.consultas import cargar_estudios
from vighi.servicios.entrega import (ROLES_ENVIO, SQL_ENVIOS, centro, datos_del_mensaje, destinos_del_formulario, guardar_correos_del_formulario, informe_para_enviar,
                                     lugares_de_envio, malignidad_pendiente, malignidad_por_flujo, medico_de, textos_envio)
from vighi.servicios.fichas import SQL_INFORME_EMITIDO
from vighi.servicios.protocolos import SQL_PROTOCOLO, protocolo_o_404
from vighi.servicios.tareas import ENTREGA, sentencias_de_cierre

bp = Blueprint("envios", __name__)

SQL_INSERTAR_ENVIO = "INSERT INTO envios (protocolo_id, informe_id, version, canal, rol, destino, estado, detalle, usuario_id, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)"
SQL_INSERTAR_AUDITORIA = "INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, estudio_id, accion, detalle) VALUES (?,?,?,?,?,?)"
FALTA_MALIGNIDAD = "Antes de entregar el informe hay que asignar la malignidad del protocolo."


def mensaje_del_formulario(p):
    asunto = " ".join(request.form.get("asunto", "").split())[:150] or textos_envio(p)["asunto"]
    cuerpo = request.form.get("cuerpo", "").replace("\r\n", "\n").strip()[:3000] or textos_envio(p)["cuerpo"]
    texto, html = mensajeria.armar_mensaje(cuerpo, datos_del_mensaje(p), centro())
    return asunto, texto, html


@bp.route("/protocolo/<int:pid>/enviar")
@requiere_permiso("informe")
def envio(pid):
    db.precargar([(SQL_PROTOCOLO, (pid,)), (SQL_INFORME_EMITIDO, (pid,)), (SQL_ENVIOS, (pid,))])
    p = protocolo_o_404(pid)
    if p["borrador"]:
        flash("El protocolo todavía está por completar.", "error")
        return redirect(url_for("protocolos.protocolo", pid=pid))
    emitido, vigente = informe_para_enviar(pid)
    historial = db.q(SQL_ENVIOS, (pid,))
    mandados = {}
    for v in historial:
        if v["estado"] == "enviado" and v["canal"] == "email" and emitido and v["version"] == emitido["version"]:
            mandados.setdefault(v["destino"], v["creado_en"])
    return render_template("envios/envio.html", flujos_malignidad=malignidad_por_flujo(cargar_estudios("e.protocolo_id=?", (pid,), borradores=True)),
                           malignidades=mensajeria.NOMBRE_MALIGNIDAD, p=p, emitido=emitido, vigente=vigente, historial=historial, mandados=mandados,
                           lugares=lugares_de_envio(p), medico=medico_de(p), textos=textos_envio(p), email_ok=mensajeria.configurado(), faltante=mensajeria.faltante(),
                           roles=ROLES_ENVIO, telefono_paciente=mensajeria.whatsapp_visible(mensajeria.whatsapp_numero(p["telefono"])) or (p["telefono"] or ""))


@bp.route("/protocolo/<int:pid>/enviar", methods=["POST"])
@requiere_permiso("informe")
def envio_enviar(pid):
    yo = usuario_actual()
    p = protocolo_o_404(pid)
    volver = redirect(url_for("envios.envio", pid=pid))
    emitido, vigente = informe_para_enviar(pid)
    if not vigente:
        flash("Primero hay que generar el informe: el guardado no existe o cambió el protocolo.", "error")
        return volver
    if malignidad_pendiente(cargar_estudios("e.protocolo_id=?", (pid,), borradores=True)):
        flash(FALTA_MALIGNIDAD, "error")
        return volver
    if not mensajeria.configurado():
        flash("El envío por e-mail no está configurado en este servidor.", "error")
        return volver
    vistos, error = destinos_del_formulario()
    if error:
        flash(error, "error")
        return volver
    asunto, texto, html = mensaje_del_formulario(p)
    pdf = db.uno("SELECT pdf, archivo FROM informes_emitidos WHERE id=?", (emitido["id"],))
    resultados = mensajeria.enviar_emails(list(vistos), asunto, texto, bytes(pdf["pdf"]), pdf["archivo"] or "informe.pdf", html=html)
    ahora_ = db.ahora()
    sentencias = [(SQL_INSERTAR_ENVIO, (pid, emitido["id"], emitido["version"], "email", vistos[destino], destino, "enviado" if ok else "error", detalle or None, yo["id"], ahora_))
                  for destino, ok, detalle in resultados]
    bien = [r[0] for r in resultados if r[1]]
    mal = [r for r in resultados if not r[1]]
    sentencias.append((SQL_INSERTAR_AUDITORIA, (ahora_, yo["id"], pid, None, "informe_envio",
                                                f"Informe enviado por e-mail a {', '.join(bien)}" + (f" · falló: {', '.join(r[0] for r in mal)}" if mal else "") if bien
                                                else f"No se pudo enviar el informe por e-mail a {', '.join(r[0] for r in mal)}")))
    if bien:
        sentencias += sentencias_de_cierre([pid], ENTREGA, "informe enviado", yo["id"])
    db.lote_ex(sentencias)
    if bien:
        guardar_correos_del_formulario(p, yo)
        flash(f"✔ Informe enviado a {len(bien)} destinatario{'s' if len(bien) != 1 else ''}: {', '.join(bien)}.", "ok")
    for destino, _, detalle in mal:
        flash(f"No se pudo enviar a {destino}: {detalle}", "error")
    return volver


@bp.route("/protocolo/<int:pid>/enviar/correo", methods=["POST"])
@requiere_permiso("informe")
def envio_correo(pid):
    yo = usuario_actual()
    p = protocolo_o_404(pid)
    modo = "eml" if request.values.get("modo") == "eml" else "mailto"

    def fallo(mensaje):
        if modo == "mailto":
            return jsonify(error=mensaje), 400
        flash(mensaje, "error")
        return redirect(url_for("envios.envio", pid=pid))

    emitido, vigente = informe_para_enviar(pid)
    if not vigente:
        return fallo("Primero hay que generar el informe: el guardado no existe o cambió el protocolo.")
    if malignidad_pendiente(cargar_estudios("e.protocolo_id=?", (pid,), borradores=True)):
        return fallo(FALTA_MALIGNIDAD)
    vistos, error = destinos_del_formulario()
    if error:
        return fallo(error)
    asunto, texto, html = mensaje_del_formulario(p)
    guardar_correos_del_formulario(p, yo)
    ahora_ = db.ahora()
    detalle = "Se abrió en el correo propio: el PDF lo adjunta quien envía" if modo == "mailto" else "Borrador (.eml) descargado con el PDF adjunto: lo envía quien lo abre"
    db.lote_ex([(SQL_INSERTAR_ENVIO, (pid, emitido["id"], emitido["version"], "correo", rol, destino, "abierto", detalle, yo["id"], ahora_)) for destino, rol in vistos.items()]
               + [(SQL_INSERTAR_AUDITORIA, (ahora_, yo["id"], pid, None, "informe_envio", f"Se preparó el envío por correo propio a {', '.join(vistos)}"))]
              + sentencias_de_cierre([pid], ENTREGA, "informe preparado para enviar", yo["id"]))
    if modo == "mailto":
        destinos = list(vistos)
        campo = "to=" if len(destinos) == 1 else "bcc="
        return jsonify(enlace="mailto:?" + campo + quote(",".join(destinos), safe="@,") + "&subject=" + quote(asunto) + "&body=" + quote(texto))
    pdf = db.uno("SELECT pdf, archivo FROM informes_emitidos WHERE id=?", (emitido["id"],))
    contenido = mensajeria.armar_borrador(list(vistos), asunto, texto, html, bytes(pdf["pdf"]), pdf["archivo"] or "informe.pdf")
    seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in p["numero"])
    return send_file(io.BytesIO(contenido), mimetype="message/rfc822", as_attachment=True, download_name=f"Informe_{seguro}.eml", max_age=0)


@bp.route("/protocolo/<int:pid>/enviar/whatsapp", methods=["POST"])
@requiere_permiso("informe")
def envio_whatsapp(pid):
    yo = usuario_actual()
    protocolo_o_404(pid)
    emitido, vigente = informe_para_enviar(pid)
    if not vigente:
        return jsonify(error="Primero hay que generar el informe: el guardado no existe o cambió el protocolo."), 400
    if malignidad_pendiente(cargar_estudios("e.protocolo_id=?", (pid,), borradores=True)):
        return jsonify(error=FALTA_MALIGNIDAD), 400
    numero = mensajeria.whatsapp_numero(request.form.get("numero", ""))
    if not numero:
        return jsonify(error="El número no es válido. Escribilo con el código de área, por ejemplo 11 5015 1099."), 400
    rol = request.form.get("rol") if request.form.get("rol") in ROLES_ENVIO else "otro"
    texto = " ".join(request.form.get("texto", "").split())[:700]
    db.lote_ex([(SQL_INSERTAR_ENVIO, (pid, emitido["id"], emitido["version"], "whatsapp", rol, "+" + numero, "abierto", "Se abrió WhatsApp: el PDF lo adjunta quien envía", yo["id"], db.ahora())),
                (SQL_INSERTAR_AUDITORIA, (db.ahora(), yo["id"], pid, None, "informe_envio", f"Se abrió WhatsApp para enviar el informe a +{numero}"))]
              + sentencias_de_cierre([pid], ENTREGA, "informe preparado para enviar", yo["id"]))
    return jsonify(enlace=f"https://wa.me/{numero}" + (f"?text={quote(texto)}" if texto else ""))


@bp.route("/correo", methods=["GET", "POST"])
@requiere_admin
def correo():
    resultado = None
    if request.method == "POST":
        destino = request.form.get("destino", "").strip().lower()
        if not mensajeria.configurado():
            flash("El correo todavía no está configurado en este servidor.", "error")
        elif not mensajeria.email_valido(destino):
            flash("Escribí un e-mail válido para la prueba.", "error")
        else:
            resultado = mensajeria.enviar_emails([destino], "Prueba de correo · CAP Vighi",
                                                 "Este es un mensaje de prueba del sistema de contingencia del CAP Vighi.\n\nSi lo recibiste, el envío de informes por e-mail está funcionando.")[0]
            db.auditar(usuario_actual()["id"], None, "correo_prueba", f"Prueba a {destino}: " + ("enviada" if resultado[1] else f"falló ({resultado[2]})"))
    return render_template("envios/correo.html", c=mensajeria.resumen(), resultado=resultado, destino=request.form.get("destino", ""))
