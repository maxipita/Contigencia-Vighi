import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from email.utils import formataddr, formatdate, make_msgid

import db

CLAVES = ("SMTP_HOST", "SMTP_PORT", "SMTP_USUARIO", "SMTP_CLAVE", "SMTP_DESDE", "SMTP_NOMBRE", "SMTP_SEGURIDAD", "SMTP_RESPONDER_A")
EMAIL = re.compile(r"^[\w.+'-]+@[\w-]+(?:\.[\w-]+)+$")
MAX_DESTINOS = 15
_config = {}
_marca = [None]


def _fecha_archivo():
    try:
        return os.path.getmtime(db.ARCHIVO_CLOUDFLARE)
    except OSError:
        return None


def config():
    if _config and _marca[0] != _fecha_archivo():
        _config.clear()
    if not _config:
        _marca[0] = _fecha_archivo()
        valores = {k: os.environ.get(k, "") for k in CLAVES}
        if os.path.exists(db.ARCHIVO_CLOUDFLARE):
            with open(db.ARCHIVO_CLOUDFLARE, encoding="utf-8") as f:
                for linea in f:
                    clave, _, valor = linea.strip().partition("=")
                    if clave in valores and not valores[clave]:
                        valores[clave] = valor.strip().strip('"').strip("'")
        _config.update(valores)
    return _config


def olvidar_config():
    _config.clear()


def configurado():
    c = config()
    return bool(c["SMTP_HOST"] and c["SMTP_DESDE"])


def resumen():
    c = config()
    return {"host": c["SMTP_HOST"], "puerto": c["SMTP_PORT"] or ("465" if c["SMTP_SEGURIDAD"] == "ssl" else "587"),
            "seguridad": {"ssl": "SSL directo", "ninguna": "Sin cifrado"}.get(c["SMTP_SEGURIDAD"], "STARTTLS"),
            "usuario": c["SMTP_USUARIO"], "con_clave": bool(c["SMTP_CLAVE"]), "desde": c["SMTP_DESDE"], "nombre": c["SMTP_NOMBRE"] or "CAP Vighi",
            "responder_a": c["SMTP_RESPONDER_A"], "configurado": configurado(), "faltante": faltante()}


def faltante():
    c = config()
    return [k for k in ("SMTP_HOST", "SMTP_DESDE") if not c[k]]


def email_valido(texto):
    texto = (texto or "").strip()
    return bool(EMAIL.match(texto)) and len(texto) <= 120


def emails_de(texto):
    return [e.lower() for e in dict.fromkeys(p.strip() for p in re.split(r"[\s,;]+", texto or "") if "@" in p) if email_valido(e)]


def whatsapp_numero(texto):
    d = re.sub(r"\D", "", texto or "")
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("54"):
        resto = d[2:]
        if resto.startswith("9"):
            resto = resto[1:]
        d = resto
    else:
        d = d.lstrip("0")
    if len(d) == 8:
        d = "11" + d
    if len(d) == 12 and d[2:4] == "15":
        d = d[:2] + d[4:]
    elif len(d) == 12 and d[3:5] == "15":
        d = d[:3] + d[5:]
    if len(d) != 10:
        return None
    return "549" + d


def whatsapp_visible(numero):
    return f"+{numero[:2]} {numero[2]} {numero[3:]}" if numero else ""


def enviar_emails(destinos, asunto, cuerpo, adjunto=None, nombre_adjunto="informe.pdf", html=None):
    c = config()
    puerto = int(c["SMTP_PORT"] or (465 if c["SMTP_SEGURIDAD"] == "ssl" else 587))
    contexto = ssl.create_default_context()
    resultados = []
    try:
        if c["SMTP_SEGURIDAD"] == "ssl":
            servidor = smtplib.SMTP_SSL(c["SMTP_HOST"], puerto, timeout=30, context=contexto)
        else:
            servidor = smtplib.SMTP(c["SMTP_HOST"], puerto, timeout=30)
        with servidor:
            if c["SMTP_SEGURIDAD"] not in ("ssl", "ninguna"):
                servidor.starttls(context=contexto)
            if c["SMTP_USUARIO"]:
                servidor.login(c["SMTP_USUARIO"], c["SMTP_CLAVE"])
            for destino in destinos:
                m = EmailMessage()
                m["Subject"] = asunto
                m["From"] = formataddr((c["SMTP_NOMBRE"] or "CAP Vighi", c["SMTP_DESDE"]))
                m["To"] = destino
                m["Date"] = formatdate(localtime=True)
                m["Message-ID"] = make_msgid(domain=c["SMTP_DESDE"].rpartition("@")[2] or None)
                if c["SMTP_RESPONDER_A"]:
                    m["Reply-To"] = c["SMTP_RESPONDER_A"]
                m.set_content(cuerpo)
                if html:
                    m.add_alternative(html, subtype="html")
                if adjunto:
                    m.add_attachment(adjunto, maintype="application", subtype="pdf", filename=nombre_adjunto)
                try:
                    servidor.send_message(m)
                    resultados.append((destino, True, ""))
                except smtplib.SMTPException as err:
                    resultados.append((destino, False, _texto_error(err)))
    except (smtplib.SMTPException, OSError) as err:
        enviados = {r[0] for r in resultados}
        for destino in destinos:
            if destino not in enviados:
                resultados.append((destino, False, _texto_error(err)))
    return resultados


def _respuesta(err):
    if isinstance(err, smtplib.SMTPRecipientsRefused):
        partes = [f"{codigo} {(texto.decode('utf-8', 'replace') if isinstance(texto, bytes) else str(texto))}" for codigo, texto in err.recipients.values()]
    else:
        texto = getattr(err, "smtp_error", b"")
        partes = [f"{getattr(err, 'smtp_code', '')} {texto.decode('utf-8', 'replace') if isinstance(texto, bytes) else texto}".strip()]
    detalle = " ".join(" ".join(partes).split())[:220]
    return f" Respuesta del servidor: {detalle}" if detalle else ""


def _texto_error(err):
    if isinstance(err, smtplib.SMTPAuthenticationError):
        return "El servidor de correo rechazó el usuario o la clave." + _respuesta(err)
    if isinstance(err, smtplib.SMTPRecipientsRefused):
        return "El servidor de correo rechazó la dirección." + _respuesta(err)
    if isinstance(err, smtplib.SMTPConnectError) or isinstance(err, OSError):
        return "No se pudo conectar con el servidor de correo."
    return (str(err) or err.__class__.__name__)[:200]


TIPOS_ESTUDIO = [("BP", "Biopsia"), ("PAP", "PAP"), ("CT", "Citología")]
MALIGNIDADES = [("SOSPECHOSO", "Sospechoso"), ("MALIGNO", "Maligno"), ("NMA", "No maligno")]
NOMBRE_TIPO = dict(TIPOS_ESTUDIO)
NOMBRE_MALIGNIDAD = dict(MALIGNIDADES)
CLAVES_ALCANCE = [f"{t}.{m}" for t, _ in TIPOS_ESTUDIO for m, _ in MALIGNIDADES]


def alcance_valido(claves):
    return ",".join(c for c in CLAVES_ALCANCE if c in claves)


def alcance_texto(alcance):
    elegidas = {c for c in (alcance or "").split(",") if c in CLAVES_ALCANCE}
    if not elegidas:
        return "Todos los estudios"
    partes = []
    for t, nombre in TIPOS_ESTUDIO:
        malig = [m for m, _ in MALIGNIDADES if f"{t}.{m}" in elegidas]
        if len(malig) == len(MALIGNIDADES):
            partes.append(f"{nombre} (todas)")
        elif malig:
            partes.append(f"{nombre}: " + ", ".join(NOMBRE_MALIGNIDAD[m].lower() for m in malig))
    return " · ".join(partes)


def evaluar(alcance, estudios):
    elegidas = {c for c in (alcance or "").split(",") if c in CLAVES_ALCANCE}
    if not elegidas:
        return "si"
    falta = False
    for tipo, malignidad in estudios:
        if malignidad in NOMBRE_MALIGNIDAD:
            if f"{tipo}.{malignidad}" in elegidas:
                return "si"
        elif any(c.startswith(tipo + ".") for c in elegidas):
            falta = True
    return "falta" if falta else "no"


LEMA = "La prevención es cuidarnos."
PIE = "Centro de Anatomía Patológica Dra. Susana Vighi"
AVISO = "Información confidencial · secreto médico"
AUTOMATICO = "Este es un mensaje automático: por favor no lo responda."


def armar_mensaje(intro, datos, centro=None):
    centro = centro or {}
    filas = [(k, v) for k, v in datos if v]
    contacto = " · ".join(x for x in (centro.get("direccion"), centro.get("telefono"), centro.get("email"), centro.get("web")) if x)
    consultas = " ".join(x for x in (f"Ante cualquier consulta, comuníquese con el laboratorio por teléfono al {centro['telefono']}" if centro.get("telefono") else "",
                                      f"o por e-mail a {centro['email']}." if centro.get("email") else "") if x)
    automatico = (AUTOMATICO + (" " + consultas if consultas else "")).strip()
    texto = "\n\n".join(x for x in (intro.strip(), "Informe adjunto\n" + "\n".join(f"{k}: {v}" for k, v in filas), automatico, f"{PIE}\n{contacto}".strip(), AVISO) if x.strip())
    parrafos = "".join(f'<p style="margin:0 0 14px">{escape(p).replace(chr(10), "<br>")}</p>' for p in intro.strip().split("\n\n") if p.strip())
    tabla = "".join(f'<tr><td style="padding:3px 0;font-weight:bold;color:#2b1a3a">{escape(k)}</td></tr><tr><td style="padding:0 0 10px;color:#2b1a3a">{escape(v)}</td></tr>' for k, v in filas)
    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#f3eef8;font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3eef8"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:6px;overflow:hidden">
<tr><td style="background:#4b1d6b;padding:18px 24px;color:#ffffff"><div style="font-size:20px;font-weight:bold;letter-spacing:.5px">{escape(centro.get("nombre", "CAP VIGHI"))}</div>
<div style="font-size:12px;opacity:.85">{escape(centro.get("subtitulo", "").title())}</div></td></tr>
<tr><td style="background:#c9a3dc;padding:8px 24px;text-align:center;color:#3a1655;font-size:15px">{escape(LEMA)}</td></tr>
<tr><td style="padding:24px;color:#2b1a3a">{parrafos}
<div style="font-weight:bold;font-size:15px;margin:18px 0 8px;color:#4b1d6b">Informe adjunto</div>
<table role="presentation" cellpadding="0" cellspacing="0">{tabla}</table></td></tr>
<tr><td style="padding:14px 24px;background:#fff7e0;border-top:1px solid #f2dc9a;text-align:center;font-size:12px;color:#5c4400"><b>{escape(AUTOMATICO)}</b>{(" " + escape(consultas)) if consultas else ""}</td></tr>
<tr><td style="background:#e9dcf2;padding:14px 24px;text-align:center;font-size:12px;color:#4b1d6b"><b>{escape(PIE)}</b><br>{escape(contacto)}<br><span style="opacity:.8">{escape(AVISO)}</span></td></tr>
</table></td></tr></table></body></html>"""
    return texto, html


def armar_borrador(destinos, asunto, texto, html, adjunto, nombre_adjunto):
    m = EmailMessage()
    m["X-Unsent"] = "1"
    m["Subject"] = asunto
    if len(destinos) == 1:
        m["To"] = destinos[0]
    else:
        m["Bcc"] = ", ".join(destinos)
    m.set_content(texto)
    m.add_alternative(html, subtype="html")
    m.add_attachment(adjunto, maintype="application", subtype="pdf", filename=nombre_adjunto)
    return m.as_bytes()
