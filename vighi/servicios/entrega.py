import re

from flask import request

from vighi.core import db
from vighi.core.fechas import fecha
from vighi.core.opcionales import informes
from vighi.core.sesion import puede
from vighi.dominio.estudios import TIPOS
from vighi.servicios import mensajeria
from vighi.servicios.fichas import informe_emitido, informe_vigente
from vighi.servicios.protocolos import sincronizar_paciente
from vighi.servicios.ubicaciones import destinos_por_ubicacion

SQL_ENVIOS = """SELECT v.id, v.canal, v.rol, v.destino, v.estado, v.detalle, v.version, v.creado_en, u.iniciales
                FROM envios v LEFT JOIN usuarios u ON u.id=v.usuario_id WHERE v.protocolo_id=? ORDER BY v.id DESC"""
ROLES_ENVIO = {"paciente": "Paciente", "medico": "Médico", "ubicacion": "Ubicación", "otro": "Otro"}


def nombre_paciente(p):
    return f"{p['nombre'] or ''} {p['apellido'] or ''}".strip().upper()


def datos_del_mensaje(p):
    return [("Protocolo", p["numero"]), ("Fecha de recolección", fecha(p["fecha_recoleccion"])), ("Paciente", nombre_paciente(p)), ("Médico", p["medico"])]


def centro():
    return informes.CENTRO if informes else {}


def textos_envio(p):
    cuerpo = f"Adjuntamos el informe de anatomía patológica correspondiente al protocolo {p['numero']}."
    return {"asunto": f"Informe Adjunto : {nombre_paciente(p) or p['numero']}", "cuerpo": cuerpo,
            "whatsapp": f"Hola, te enviamos el informe de anatomía patológica del protocolo {p['numero']}. Ante cualquier consulta, escribinos por acá. {centro().get('nombre', 'CAP Vighi')}"}


def estudios_para_envio(pid):
    return [(r["tipo"], r["malignidad"]) for r in db.q("SELECT tipo, malignidad FROM estudios WHERE protocolo_id=? AND anulado=0", (pid,))]


def lugares_de_envio(p):
    claves = list(dict.fromkeys(l for l in (p["lugar_entrega"], p["lugar_recoleccion"]) if l))
    if not claves:
        return []
    filas = {u["abreviatura"]: u for u in db.q(f"SELECT id, abreviatura, nombre, contactos FROM ubicaciones WHERE abreviatura IN ({','.join('?' * len(claves))})", tuple(claves))}
    destinos = destinos_por_ubicacion({u["id"] for u in filas.values()})
    estudios = estudios_para_envio(p["id"])
    salida = []
    for clave in claves:
        u = filas.get(clave)
        propios = destinos.get(u["id"], []) if u else []
        salida.append({"abreviatura": clave, "nombre": (u["nombre"] if u else "") or "", "contactos": (u["contactos"] if u else "") or "", "id": u["id"] if u else None,
                       "emails": [dict(d, estado=mensajeria.evaluar(d["alcance"], estudios), texto=mensajeria.alcance_texto(d["alcance"])) for d in propios if d["canal"] == "email" and d["informes"]],
                       "telefonos": [dict(d, estado=mensajeria.evaluar(d["alcance"], estudios), texto=mensajeria.alcance_texto(d["alcance"]), visible=mensajeria.whatsapp_visible(d["destino"]))
                                     for d in propios if d["canal"] == "whatsapp" and d["informes"]],
                       "ocultos": sum(1 for d in propios if not d["informes"]), "es_entrega": clave == p["lugar_entrega"]})
    return salida


def medico_de(p):
    nombre = (p["medico"] or "").strip()
    if not nombre:
        return None
    m = db.uno("SELECT id, nombre, email FROM medicos WHERE nombre=?", (nombre,))
    if m:
        return m
    clave = db.clave_nombre(nombre)
    return next((x for x in db.q("SELECT id, nombre, email FROM medicos ORDER BY id") if db.clave_nombre(x["nombre"]) == clave), None)


def informe_para_enviar(pid):
    emitido = informe_emitido(pid)
    return emitido, bool(emitido) and informe_vigente(pid, emitido)


def malignidad_por_flujo(estudios):
    salida = []
    for tipo in dict.fromkeys(x["tipo"] for x in estudios if not x["anulado"]):
        activos = [x for x in estudios if x["tipo"] == tipo and not x["anulado"]]
        valores = {x["malignidad"] for x in activos}
        sin_borrador = not any(x["borrador"] for x in activos)
        informado = sin_borrador and not any(x["proxima"] for x in activos)
        asignable = sin_borrador and not any(x["proxima"] and x["proxima"][0] not in ("microscopia", "interp_ihq", "revision") for x in activos)
        salida.append({"tipo": tipo, "nombre": TIPOS[tipo], "asignable": asignable, "informado": informado,
                       "valor": valores.pop() if len(valores) == 1 else None})
    return salida


def malignidad_pendiente(estudios):
    return any(f["asignable"] and not f["valor"] for f in malignidad_por_flujo(estudios))


def destinos_del_formulario():
    solo = request.form.get("solo", "")
    if solo and solo not in ROLES_ENVIO:
        return None, "No se reconoce a quién enviar el informe."
    pedidos = []
    if solo == "paciente" or (not solo and request.form.get("usar_paciente") == "1"):
        correo = request.form.get("paciente_email", "").strip().lower()
        if not mensajeria.email_valido(correo):
            return None, "Escribí un e-mail válido para el paciente." if not correo else "El e-mail del paciente no es válido."
        pedidos.append(("paciente", correo))
    if solo == "medico":
        correo = request.form.get("medico_email", "").strip().lower()
        if not mensajeria.email_valido(correo):
            return None, "Escribí un e-mail válido para el médico." if not correo else "El e-mail del médico no es válido."
        pedidos.append(("medico", correo))
    if solo in ("", "ubicacion"):
        for correo in request.form.getlist("ubic_email"):
            if not mensajeria.email_valido(correo):
                return None, f"El e-mail {correo[:60]} no es válido."
            pedidos.append(("ubicacion", correo.strip().lower()))
        if solo and not pedidos:
            return None, "Tildá al menos un e-mail de la ubicación."
    otros = request.form.get("otro_email", "").strip()
    if otros and solo in ("", "otro"):
        sueltos = [x for x in re.split(r"[\s,;]+", otros) if x]
        malos = [x for x in sueltos if not mensajeria.email_valido(x)]
        if malos:
            return None, f"El e-mail {malos[0][:60]} no es válido."
        pedidos += [("otro", x.lower()) for x in sueltos]
    elif solo == "otro":
        return None, "Escribí el e-mail del destinatario."
    vistos = {}
    for rol, correo in pedidos:
        vistos.setdefault(correo, rol)
    if not vistos:
        return None, "Elegí a quién enviar el informe."
    if len(vistos) > mensajeria.MAX_DESTINOS:
        return None, f"Se pueden enviar hasta {mensajeria.MAX_DESTINOS} e-mails por vez."
    return vistos, None


def guardar_correos_del_formulario(p, yo):
    if not puede("protocolo_editar"):
        return
    solo = request.form.get("solo", "")
    if request.form.get("guardar_paciente") == "1" and (solo == "paciente" or (not solo and request.form.get("usar_paciente") == "1")):
        nuevo = request.form.get("paciente_email", "").strip().lower()
        if mensajeria.email_valido(nuevo) and nuevo != (p["email"] or "").lower():
            db.ex("UPDATE protocolos SET email=? WHERE id=?", (nuevo, p["id"]))
            sincronizar_paciente(p["id"], p["dni"], ["email"])
            db.auditar(yo["id"], p["id"], "editar_paciente", f"E-mail del paciente: {nuevo}")
    if request.form.get("guardar_medico") == "1" and solo == "medico":
        nuevo = request.form.get("medico_email", "").strip().lower()
        m = medico_de(p)
        if m and mensajeria.email_valido(nuevo) and nuevo != (m["email"] or "").lower():
            db.ex("UPDATE medicos SET email=? WHERE id=?", (nuevo, m["id"]))
            db.auditar(yo["id"], p["id"], "editar_medico", f"E-mail de {m['nombre']}: {nuevo}")
