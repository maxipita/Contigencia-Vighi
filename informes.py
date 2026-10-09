import io
import os
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, Image, KeepTogether, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

import db
from estudios import REGISTRO

BASE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(BASE, "static", "img", "logo.png")

CENTRO = {
    "nombre": "CAP VIGHI",
    "subtitulo": "CENTRO DE ANATOMÍA PATOLÓGICA",
    "direccion": "Concepción Arenal 3732 · CABA · C1427EKH",
    "telefono": "4551-7752 L.R.",
    "email": "anatomia.patologica@susanavighi.com.ar",
    "web": "www.susanavighi.com.ar",
}
CONFIDENCIAL = "INFORMACIÓN CONFIDENCIAL · SECRETO MÉDICO · ALCANCES DEL ARTÍCULO 156 DEL CÓDIGO PENAL"

PRIMARIO = colors.HexColor("#431866")
ACENTO = colors.HexColor("#8a3fd6")
PIZARRA = colors.HexColor("#665e77")
SUPERFICIE = colors.HexColor("#f8f5fb")
BORDE = colors.HexColor("#e3e8ee")
TEXTO = colors.HexColor("#2d2038")

MAX_FIRMA = (900, 360)
MAX_COMENTARIO = 3000


class InformeError(Exception):
    pass


def _fuentes():
    carpeta = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for normal, negrita in (("segoeui.ttf", "segoeuib.ttf"), ("arial.ttf", "arialbd.ttf")):
        a, b = os.path.join(carpeta, normal), os.path.join(carpeta, negrita)
        if os.path.exists(a) and os.path.exists(b):
            try:
                pdfmetrics.registerFont(TTFont("Informe", a))
                pdfmetrics.registerFont(TTFont("Informe-Bold", b))
                pdfmetrics.registerFontFamily("Informe", normal="Informe", bold="Informe-Bold", italic="Informe", boldItalic="Informe-Bold")
                return "Informe", "Informe-Bold"
            except Exception:
                pass
    return "Helvetica", "Helvetica-Bold"


FUENTE, NEGRITA = _fuentes()


def procesar_firma(contenido):
    from PIL import Image as PIL
    if len(contenido) > 6 * 1024 * 1024:
        raise ValueError("La imagen pesa más de 6 MB.")
    try:
        img = PIL.open(io.BytesIO(contenido))
        if img.format not in ("PNG", "JPEG"):
            raise ValueError
        img = img.convert("RGBA")
    except Exception:
        raise ValueError("El archivo no es una imagen PNG o JPG válida.")
    img.thumbnail(MAX_FIRMA)
    fondo = PIL.new("RGBA", img.size, (255, 255, 255, 0))
    fondo.alpha_composite(img)
    salida = io.BytesIO()
    fondo.save(salida, "PNG", optimize=True)
    return salida.getvalue()


def _fecha(texto):
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def _t(fila, campo):
    return ((fila[campo] if fila else "") or "").strip()


def _etiqueta(e):
    nombre = REGISTRO[e["tipo"]].nombre
    return nombre if e["tipo"] == "PAP" or not e["sitio"] else f"{nombre} · {e['sitio']}"


def _firmante(protocolo, estudios, cierre):
    if protocolo["firmante_id"]:
        u = db.uno("SELECT id, iniciales, nombre, titulo, mn, mp FROM usuarios WHERE id=?", (protocolo["firmante_id"],))
        if u:
            return u, "pasó la firma a su nombre al cerrar el último paso"
    for e in estudios:
        if e["responsable_id"]:
            u = db.uno("SELECT id, iniciales, nombre, titulo, mn, mp, sectores FROM usuarios WHERE id=?", (e["responsable_id"],))
            if u and "firmante" in (u["sectores"] or "").split(","):
                return u, "responsable asignado al caso"
    u = db.uno("SELECT id, iniciales, nombre, titulo, mn, mp FROM usuarios WHERE id=?", (cierre["usuario_id"],))
    return u, "quien cerró la última etapa (no hay un médico responsable asignado)"


def armar(pid, comentario=""):
    p = db.uno("SELECT * FROM protocolos WHERE id=?", (pid,))
    if not p:
        raise InformeError("El protocolo no existe.")
    if p["borrador"]:
        raise InformeError("Primero hay que completar los datos del paciente de este protocolo.")
    estudios = db.q("SELECT * FROM estudios WHERE protocolo_id=? AND anulado=0 ORDER BY id", (pid,))
    if not estudios:
        raise InformeError("El protocolo no tiene estudios activos.")

    etapas = {}
    for x in db.q("SELECT x.* FROM etapas x JOIN estudios e ON e.id=x.estudio_id WHERE e.protocolo_id=?", (pid,)):
        etapas.setdefault(x["estudio_id"], {})[x["etapa"]] = x
    ihq_pide = {e["tipo"] for e in estudios if db.uno("SELECT 1 FROM micro WHERE estudio_id=? AND solicita_ihq=1", (e["id"],))}
    pendientes = []
    for e in estudios:
        _, proxima = REGISTRO[e["tipo"]].estado(set(etapas.get(e["id"], {})), e["tipo"] in ihq_pide)
        if proxima and (_etiqueta(e), proxima[1]) not in pendientes:
            pendientes.append((_etiqueta(e), proxima[1]))
    if pendientes:
        raise InformeError("El informe se genera cuando todos los estudios están informados. Falta: "
                           + "; ".join(f"{n} (pendiente {s})" for n, s in pendientes) + ".")

    cierre = max((x for ids in etapas.values() for x in ids.values()), key=lambda x: (x["fecha_hora"], x["id"]))
    medico, origen = _firmante(p, estudios, cierre)
    tiene_firma = bool(db.uno("SELECT 1 FROM firmas WHERE usuario_id=?", (medico["id"],)))
    nombre_medico = medico["nombre"] or medico["iniciales"]

    secciones, avisos = [], []
    flujos = {}
    for e in estudios:
        flujos.setdefault(e["tipo"], []).append(e)
    for miembros in flujos.values():
        e = miembros[0]
        tipo = REGISTRO[e["tipo"]]
        macro = db.uno("SELECT * FROM macro WHERE estudio_id=?", (e["id"],))
        micro = db.uno("SELECT * FROM micro WHERE estudio_id=?", (e["id"],))
        ihq = db.uno("SELECT * FROM ihq WHERE estudio_id=?", (e["id"],))
        cuerpo = _t(micro, "conclusion")
        if tipo.bethesda and _t(micro, "bethesda"):
            diag, detalle = _t(micro, "bethesda"), cuerpo or _t(micro, "descripcion")
        elif cuerpo:
            primera, _, resto = cuerpo.partition("\n")
            diag, detalle = primera.strip(), resto.strip()
        elif _t(micro, "descripcion"):
            diag, detalle = "Ver descripción microscópica.", ""
        else:
            diag, detalle = "", ""
        materiales = []
        for m in miembros:
            cant = (m["cantidad"] or "").strip()
            material = " · ".join(x for x in (m["sitio"], m["tipo_muestra"]) if x)
            if cant:
                material += f" ({cant} {tipo.etiqueta_cantidad})" if material else f"{cant} {tipo.etiqueta_cantidad}"
            if material:
                materiales.append(material)
        ihq_txt = ""
        if "ihq" in tipo.secciones and ihq and (_t(ihq, "marcadores") or _t(ihq, "resultado")):
            ihq_txt = "\n".join(x for x in (("Marcadores: " + _t(ihq, "marcadores")) if _t(ihq, "marcadores") else "", _t(ihq, "resultado")) if x)
        etiqueta = _etiqueta(e) if len(miembros) == 1 else f"{tipo.nombre} · " + ", ".join(dict.fromkeys(m["sitio"] for m in miembros if m["sitio"]))
        if not diag:
            avisos.append(f"{etiqueta}: no hay diagnóstico cargado, el informe saldría sin diagnóstico final.")
        secciones.append({"eid": e["id"], "eids": [m["id"] for m in miembros], "tipo": e["tipo"], "etiqueta": etiqueta, "material": "\n".join(materiales),
                          "diagnostico": diag, "detalle": detalle,
                          "macroscopia": _t(macro, "descripcion") if "macro" in tipo.secciones else "", "microscopia": _t(micro, "descripcion"),
                          "tecnicas": _t(micro, "tecnicas_especiales"), "ihq": ihq_txt})
    if not tiene_firma:
        avisos.append(f"{nombre_medico} no tiene la firma cargada: el informe saldría sin firma (se carga en Usuarios).")
    if not (medico["mn"] or medico["mp"]):
        avisos.append(f"{nombre_medico} no tiene la matrícula cargada (MN / MP).")

    tipos = {s["tipo"] for s in secciones}
    return {
        "pid": pid, "numero": p["numero"], "estudios": secciones,
        "titulo": "INFORME HISTOPATOLÓGICO" if tipos == {"BP"} else ("INFORME CITOLÓGICO" if "BP" not in tipos else "INFORME DE ANATOMÍA PATOLÓGICA"),
        "paciente": f"{p['apellido'] or ''}, {p['nombre'] or ''}".strip(", ").upper(),
        "medico_solicitante": p["medico"] or "", "institucion": p["lugar_recoleccion"] or "",
        "cobertura": " ".join(x for x in (p["cobertura"], p["n_afiliado"]) if x),
        "fecha": _fecha(cierre["fecha_hora"]) or datetime.now().strftime("%d/%m/%Y"),
        "comentario": (comentario or "").strip()[:MAX_COMENTARIO],
        "medico": {"id": medico["id"], "nombre": nombre_medico, "titulo": medico["titulo"] or "",
                   "mn": medico["mn"] or "", "mp": medico["mp"] or "", "firma": tiene_firma, "origen": origen},
        "avisos": avisos,
    }


def nombre_archivo(d):
    seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in d["numero"])
    return f"Informe_{seguro}.pdf"


def _estilos():
    base = dict(fontName=FUENTE, textColor=TEXTO, leading=14.5, fontSize=10.5)
    return {
        "texto": ParagraphStyle("texto", **base),
        "etiqueta": ParagraphStyle("etiqueta", **{**base, "fontName": NEGRITA, "textColor": PRIMARIO, "fontSize": 9.5, "leading": 12}),
        "valor": ParagraphStyle("valor", **{**base, "fontSize": 9.5, "leading": 12}),
        "titulo": ParagraphStyle("titulo", **{**base, "fontName": NEGRITA, "textColor": PRIMARIO, "fontSize": 17, "leading": 22, "alignment": TA_CENTER}),
        "estudio": ParagraphStyle("estudio", **{**base, "fontName": NEGRITA, "textColor": PRIMARIO, "fontSize": 12.5, "leading": 16}),
        "seccion": ParagraphStyle("seccion", **{**base, "fontName": NEGRITA, "textColor": ACENTO, "fontSize": 11, "leading": 14, "spaceAfter": 3}),
        "diagnostico": ParagraphStyle("diagnostico", **{**base, "fontName": NEGRITA, "textColor": PRIMARIO, "fontSize": 14, "leading": 18, "spaceAfter": 3}),
        "marca": ParagraphStyle("marca", **{**base, "fontName": NEGRITA, "textColor": PRIMARIO, "fontSize": 17, "leading": 18, "alignment": TA_RIGHT}),
        "marca2": ParagraphStyle("marca2", **{**base, "fontName": NEGRITA, "textColor": PIZARRA, "fontSize": 8, "leading": 11, "alignment": TA_RIGHT}),
        "firma_nombre": ParagraphStyle("firma_nombre", **{**base, "fontName": NEGRITA, "textColor": PRIMARIO, "fontSize": 11, "leading": 14, "alignment": TA_RIGHT}),
        "firma_dato": ParagraphStyle("firma_dato", **{**base, "textColor": PIZARRA, "fontSize": 8.5, "leading": 11, "alignment": TA_RIGHT}),
        "pie": ParagraphStyle("pie", **{**base, "textColor": PIZARRA, "fontSize": 8, "leading": 10}),
    }


def _p(texto, estilo):
    return Paragraph(escape(texto or "").replace("\r", "").replace("\n", "<br/>"), estilo)


def _construir(d, total, firma_png):
    s = _estilos()
    ancho, alto = A4
    izq = der = 18 * mm
    util = ancho - izq - der
    salida = io.BytesIO()

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BORDE)
        canvas.setLineWidth(0.6)
        canvas.line(izq, 27 * mm, ancho - der, 27 * mm)
        canvas.setFillColor(PIZARRA)
        canvas.setFont(NEGRITA, 7.5)
        canvas.drawCentredString(ancho / 2, 21.5 * mm, CONFIDENCIAL)
        canvas.setFont(FUENTE, 7.5)
        contacto = f"{CENTRO['direccion']}  ·  {CENTRO['telefono']}  ·  {CENTRO['email']}  ·  {CENTRO['web']}"
        canvas.drawCentredString(ancho / 2, 17.5 * mm, contacto)
        canvas.drawRightString(ancho - der, 12 * mm, f"Página {doc.page} de {total or 1}")
        canvas.drawString(izq, 12 * mm, f"Protocolo {d['numero']}")
        canvas.restoreState()

    doc = BaseDocTemplate(salida, pagesize=A4, leftMargin=izq, rightMargin=der, topMargin=14 * mm, bottomMargin=31 * mm,
                          title=f"{d['titulo'].title()} {d['numero']}", author=CENTRO["nombre"], subject=d["paciente"])
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(izq, 31 * mm, util, alto - 45 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=pie)])

    flujo = []

    logo = Image(LOGO, width=17 * mm, height=17 * mm) if os.path.exists(LOGO) else Spacer(1, 1)
    marca = Table([[[Paragraph(CENTRO["nombre"], s["marca"]), Paragraph(CENTRO["subtitulo"], s["marca2"])], logo]],
                  colWidths=[util - 17 * mm - 6, 17 * mm + 6], style=TableStyle([
                      ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 8),
                      ("RIGHTPADDING", (1, 0), (1, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 0),
                      ("LINEBELOW", (0, 0), (-1, 0), 1.6, ACENTO)]))
    flujo += [marca, Spacer(1, 8)]

    def fila(a, b, c, d_):
        return [Paragraph(a, s["etiqueta"]) if a else "", _p(b, s["valor"]) if b else "",
                Paragraph(c, s["etiqueta"]) if c else "", _p(d_, s["valor"]) if d_ else ""]
    filas = [fila("Paciente:", d["paciente"], "Protocolo:", d["numero"]),
             fila("Médico solicitante:", d["medico_solicitante"], "Fecha:", d["fecha"]),
             fila("Institución:", d["institucion"], "Página:", f"1 de {total or 1}"),
             fila("Cobertura:", d["cobertura"], "", "")]
    cw = [106, util - 106 - 62 - 100, 62, 100]
    flujo.append(Table(filas, colWidths=cw, style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LINEBELOW", (0, -1), (-1, -1), 0.6, BORDE)])))
    flujo += [Spacer(1, 10), Paragraph(d["titulo"], s["titulo"]), Spacer(1, 8)]

    def seccion(titulo, texto):
        if texto:
            flujo.append(KeepTogether([HRFlowable(width="100%", thickness=0.6, color=BORDE, spaceBefore=2, spaceAfter=7),
                                       Paragraph(titulo, s["seccion"]), _p(texto, s["texto"]), Spacer(1, 5)]))

    varios = len(d["estudios"]) > 1
    for est in d["estudios"]:
        if varios:
            flujo.append(Table([[Paragraph(escape(est["etiqueta"]).upper(), s["estudio"])]], colWidths=[util], style=TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, ACENTO), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])))
            flujo.append(Spacer(1, 6))
        if est["diagnostico"]:
            partes = [Paragraph("DIAGNÓSTICO FINAL", s["seccion"]), _p(est["diagnostico"], s["diagnostico"])]
            if est["detalle"]:
                partes.append(_p(est["detalle"], s["texto"]))
            flujo.append(Table([[partes]], colWidths=[util], style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), SUPERFICIE), ("ROUNDEDCORNERS", [7, 7, 7, 7]), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 11)])))
            flujo.append(Spacer(1, 8))
        seccion("MATERIAL", est["material"])
        seccion("MACROSCOPÍA", est["macroscopia"])
        seccion("MICROSCOPÍA" if est["tipo"] == "BP" else "DESCRIPCIÓN", est["microscopia"])
        seccion("TÉCNICAS ESPECIALES", est["tecnicas"])
        seccion("INMUNOHISTOQUÍMICA", est["ihq"])
        if varios:
            flujo.append(Spacer(1, 10))
    seccion("COMENTARIO", d["comentario"])

    m = d["medico"]
    rol = {"Dra.": "Médica Patóloga", "Dr.": "Médico Patólogo"}.get(m["titulo"], "Médico/a Patólogo/a")
    nombre = f"{m['titulo']} {m['nombre']}".strip()
    matricula = " · ".join(x for x in (f"MN {m['mn']}" if m["mn"] else "", f"MP {m['mp']}" if m["mp"] else "") if x)
    celdas = []
    if firma_png:
        from reportlab.lib.utils import ImageReader
        w, h = ImageReader(io.BytesIO(firma_png)).getSize()
        alto_f = min(18 * mm, 46 * mm * h / w)
        celdas.append([Image(io.BytesIO(firma_png), width=alto_f * w / h, height=alto_f, hAlign="RIGHT")])
    celdas.append([Paragraph(escape(nombre), s["firma_nombre"])])
    celdas.append([Paragraph(rol, s["firma_dato"])])
    if matricula:
        celdas.append([Paragraph(matricula, s["firma_dato"])])
    bloque = Table(celdas, colWidths=[85 * mm], style=TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                                                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                                                   ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    emitido = Paragraph(f"Informe emitido por el sistema de contingencia · {datetime.now():%d/%m/%Y %H:%M}", s["pie"])
    flujo.append(KeepTogether([Spacer(1, 14), HRFlowable(width="100%", thickness=0.6, color=BORDE, spaceAfter=6),
                               Table([[emitido, bloque]], colWidths=[util - 85 * mm, 85 * mm], style=TableStyle([
                                   ("VALIGN", (0, 0), (0, 0), "BOTTOM"), ("VALIGN", (1, 0), (1, 0), "BOTTOM"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))]))

    doc.build(flujo)
    return salida.getvalue(), doc.page


def generar_pdf(d):
    firma = None
    if d["medico"]["firma"]:
        f = db.uno("SELECT imagen FROM firmas WHERE usuario_id=?", (d["medico"]["id"],))
        firma = bytes(f["imagen"]) if f else None
    _, paginas = _construir(d, 0, firma)
    return _construir(d, paginas, firma)[0]
