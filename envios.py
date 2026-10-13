import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import db

CLAVES = ("SMTP_HOST", "SMTP_PORT", "SMTP_USUARIO", "SMTP_CLAVE", "SMTP_DESDE", "SMTP_NOMBRE", "SMTP_SEGURIDAD", "SMTP_RESPONDER_A")
EMAIL = re.compile(r"^[\w.+'-]+@[\w-]+(?:\.[\w-]+)+$")
MAX_DESTINOS = 15
_config = {}


def config():
    if not _config:
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


def enviar_emails(destinos, asunto, cuerpo, adjunto=None, nombre_adjunto="informe.pdf"):
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
                if c["SMTP_RESPONDER_A"]:
                    m["Reply-To"] = c["SMTP_RESPONDER_A"]
                m.set_content(cuerpo)
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


def _texto_error(err):
    if isinstance(err, smtplib.SMTPAuthenticationError):
        return "El servidor de correo rechazó el usuario o la clave."
    if isinstance(err, smtplib.SMTPRecipientsRefused):
        return "El servidor de correo rechazó la dirección."
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
