import hashlib
import io
import re
import threading

from vighi.core import almacen, db
from vighi.servicios.etiquetas import numero_protocolo
from vighi.servicios.imagenes import reducir_a_jpeg

PERMISOS_ORDENES = ("protocolo_editar",)
MAX_PAGINAS = 40
DPI = 200
LADO_OCR = 1800
SQL_ORDENES = """SELECT o.id, o.protocolo_id, o.nombre, o.pagina, o.metodo, o.creado_en, u.iniciales FROM ordenes o
                 LEFT JOIN usuarios u ON u.id=o.usuario_id WHERE o.protocolo_id=? ORDER BY o.id"""
SQL_PENDIENTES = """SELECT o.id, o.nombre, o.pagina, o.leido, o.motivo, o.creado_en, u.iniciales FROM ordenes o
                    LEFT JOIN usuarios u ON u.id=o.usuario_id WHERE o.protocolo_id IS NULL ORDER BY o.id"""
SQL_RECIENTES = """SELECT o.id, o.protocolo_id, o.nombre, o.pagina, o.metodo, o.creado_en, p.numero, u.iniciales FROM ordenes o
                   JOIN protocolos p ON p.id=o.protocolo_id LEFT JOIN usuarios u ON u.id=o.usuario_id ORDER BY o.id DESC LIMIT 30"""
PATRON_NUMERO = re.compile(r"(?<![A-Za-z0-9])[Cc]\s*#?\s*([0-9OoQDIl|SsBZ]{6})(?![0-9A-Za-z])")
_modulos = {}
_candado_ocr = threading.Lock()
_cupo_archivos = threading.BoundedSemaphore(2)


def _modulo(nombre):
    if nombre not in _modulos:
        try:
            if nombre == "zxing":
                import zxingcpp as m
            elif nombre == "pdf":
                import pypdfium2 as m
            else:
                from rapidocr_onnxruntime import RapidOCR
                m = RapidOCR()
        except ImportError:
            m = None
        _modulos[nombre] = m
    return _modulos[nombre]


def lectores():
    return {"qr": _modulo("zxing") is not None, "ocr": _modulo("ocr") is not None, "pdf": _modulo("pdf") is not None}


def numeros_del_texto(texto):
    numeros = []
    for m in PATRON_NUMERO.finditer(texto or ""):
        digitos = m.group(1).translate(str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "S": "5", "s": "5", "B": "8", "Z": "2"}))
        if digitos.isdigit() and int(digitos) > 0:
            numeros.append("C" + digitos)
    return list(dict.fromkeys(numeros))


def numero_escrito(texto):
    limpio = (texto or "").strip().lstrip("#").strip().upper()
    if limpio.isdigit() and 0 < int(limpio) <= 999999:
        return numero_protocolo(int(limpio))
    if re.fullmatch(r"C\d{6}", limpio):
        return limpio
    return None


def paginas_de(contenido):
    from PIL import Image, ImageOps, ImageSequence
    if contenido[:5] == b"%PDF-":
        pdfium = _modulo("pdf")
        if pdfium is None:
            raise ValueError("falta instalar pypdfium2 para leer PDF (python -m pip install -r requirements.txt)")
        try:
            pdf = pdfium.PdfDocument(contenido)
        except Exception:
            raise ValueError("no es un PDF válido")
        try:
            if len(pdf) > MAX_PAGINAS:
                raise ValueError(f"tiene más de {MAX_PAGINAS} páginas")
            for i in range(len(pdf)):
                pagina = pdf[i]
                ancho, alto = pagina.get_size()
                escala = min(DPI / 72, 3300 / max(ancho, alto, 1))
                yield pagina.render(scale=escala).to_pil().convert("RGB")
        finally:
            pdf.close()
        return
    try:
        img = Image.open(io.BytesIO(contenido))
        if img.format not in ("JPEG", "PNG", "WEBP", "TIFF"):
            raise ValueError
        cuadros = zip(range(MAX_PAGINAS), ImageSequence.Iterator(img))
    except Exception:
        raise ValueError("no es un PDF ni una imagen JPG, PNG, WEBP o TIFF válida")
    for _, f in cuadros:
        yield ImageOps.exif_transpose(f.copy()).convert("RGB")


def leer_qr(img):
    zxing = _modulo("zxing")
    if zxing is None:
        return []
    for escala in (1, 2):
        chica = img if escala == 1 else img.resize((img.width // 2, img.height // 2))
        textos = [b.text for b in zxing.read_barcodes(chica)]
        encontrados = [n for t in textos for n in numeros_del_texto(t)]
        if encontrados:
            return list(dict.fromkeys(encontrados))
    return []


def leer_ocr(img):
    motor = _modulo("ocr")
    if motor is None:
        return []
    import numpy as np
    chica = img.copy()
    chica.thumbnail((LADO_OCR, LADO_OCR))
    with _candado_ocr:
        resultado, _ = motor(np.asarray(chica))
    return list(dict.fromkeys(n for fila in (resultado or []) for n in numeros_del_texto(fila[1])))


def protocolos_existentes(numeros):
    if not numeros:
        return {}
    return {r["numero"]: r["id"] for r in db.q(f"SELECT id, numero FROM protocolos WHERE numero IN ({','.join('?' * len(numeros))})", list(numeros))}


def identificar(img):
    vistos = []
    for metodo, lector in (("qr", leer_qr), ("ocr", leer_ocr)):
        numeros = lector(img)
        vistos += numeros
        existentes = protocolos_existentes(numeros)
        if len(existentes) == 1:
            numero, pid = next(iter(existentes.items()))
            return {"protocolo_id": pid, "numero": numero, "metodo": metodo, "motivo": None, "con_numero": True}
        if len(existentes) > 1:
            return {"protocolo_id": None, "numero": None, "metodo": None, "leido": ", ".join(existentes), "con_numero": True,
                    "motivo": "La hoja tiene varios números de protocolo: " + ", ".join(existentes)}
    if vistos:
        return {"protocolo_id": None, "numero": None, "metodo": None, "leido": ", ".join(vistos), "con_numero": True,
                "motivo": "El protocolo " + ", ".join(vistos) + " no existe"}
    return {"protocolo_id": None, "numero": None, "metodo": None, "leido": None, "con_numero": False, "motivo": "No se encontró el número de protocolo"}


def guardar_pagina(img, nombre, pagina, ident, yo, grupo=None, reducida=None):
    grande, mini = reducida or reducir_a_jpeg(img)
    huella = hashlib.sha256(grande).hexdigest()
    if db.uno("SELECT 1 FROM ordenes WHERE huella=?", (huella,)):
        return None
    ahora = db.ahora()
    oid = db.ex("INSERT INTO ordenes (protocolo_id, nombre, pagina, imagen, miniatura, huella, metodo, leido, motivo, usuario_id, creado_en, grupo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ident["protocolo_id"], nombre[:160], pagina, almacen.guardar("ordenes", grande, "image/jpeg"), almacen.guardar("ordenes", mini, "image/jpeg"), huella,
                 ident["metodo"], (ident.get("leido") or ident.get("numero") or "")[:40] or None, ident["motivo"], yo, ahora, grupo))
    if ident["protocolo_id"]:
        db.auditar(yo, ident["protocolo_id"], "orden", f"{nombre[:60]} (página {pagina}, {ident['metodo']})")
    return oid


def _clave_natural(texto):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", texto or "")]


def _es_ancla(o):
    return o["metodo"] in ("qr", "ocr", "manual") or (o["metodo"] is None and bool(o["leido"]))


def reagrupar(grupo):
    filas = sorted(db.q("SELECT id, protocolo_id, nombre, pagina, metodo, leido FROM ordenes WHERE grupo=?", (grupo,)),
                   key=lambda o: (_clave_natural(o["nombre"]), o["pagina"], o["id"]))
    actual, cambios, ahora = None, [], db.ahora()
    for o in filas:
        if _es_ancla(o):
            actual = o["protocolo_id"]
        elif actual:
            if o["protocolo_id"] != actual or o["metodo"] != "continuacion":
                cambios.append(("UPDATE ordenes SET protocolo_id=?, metodo='continuacion', motivo=NULL WHERE id=?", (actual, o["id"])))
                if o["protocolo_id"] != actual:
                    cambios.append(("INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, estudio_id, accion, detalle) VALUES (?,?,?,?,?,?)",
                                    (ahora, None, actual, None, "orden", f"{(o['nombre'] or '')[:60]} (página {o['pagina']}, continuación)")))
        elif o["protocolo_id"] is not None or o["metodo"] is not None or o["leido"]:
            cambios.append(("UPDATE ordenes SET protocolo_id=NULL, metodo=NULL, leido=NULL, motivo=? WHERE id=?", ("No se encontró el número de protocolo", o["id"])))
    if cambios:
        db.lote_ex(cambios)


def procesar_archivo(nombre, contenido, yo, protocolo_id=None, grupo=None):
    with _cupo_archivos:
        return _procesar_archivo(nombre, contenido, yo, protocolo_id, grupo)


def _procesar_archivo(nombre, contenido, yo, protocolo_id, grupo):
    resultados = []
    anterior = None
    for pagina, img in enumerate(paginas_de(contenido), 1):
        reducida = reducir_a_jpeg(img)
        if db.uno("SELECT 1 FROM ordenes WHERE huella=?", (hashlib.sha256(reducida[0]).hexdigest(),)):
            resultados.append({"pagina": pagina, "estado": "repetida", "numero": None, "metodo": None, "motivo": "Ya estaba cargada"})
            continue
        if protocolo_id:
            ident = {"protocolo_id": protocolo_id, "numero": None, "metodo": "manual", "motivo": None}
        else:
            ident = identificar(img)
            if not ident["protocolo_id"] and not ident["con_numero"] and anterior:
                ident = {"protocolo_id": anterior["protocolo_id"], "numero": anterior["numero"], "metodo": "continuacion", "motivo": None}
        oid = guardar_pagina(img, nombre, pagina, ident, yo, grupo, reducida)
        if oid is None:
            resultados.append({"pagina": pagina, "estado": "repetida", "numero": ident["numero"], "metodo": None, "motivo": "Ya estaba cargada"})
            continue
        if ident["protocolo_id"]:
            anterior = ident
        resultados.append({"pagina": pagina, "id": oid, "estado": "adjunta" if ident["protocolo_id"] else "pendiente", "numero": ident["numero"],
                           "metodo": ident["metodo"], "motivo": ident["motivo"]})
    if grupo and any("id" in r for r in resultados):
        with db.bloqueo("ordenes-" + hashlib.sha1(grupo.encode("utf-8")).hexdigest()[:20]):
            reagrupar(grupo)
        for r in resultados:
            if "id" in r:
                o = db.uno("SELECT o.protocolo_id, o.metodo, o.motivo, p.numero FROM ordenes o LEFT JOIN protocolos p ON p.id=o.protocolo_id WHERE o.id=?", (r["id"],))
                r.update(estado="adjunta" if o["protocolo_id"] else "pendiente", numero=o["numero"], metodo=o["metodo"], motivo=o["motivo"])
    return resultados


def ordenes_de(pid):
    return db.q(SQL_ORDENES, (pid,))


def asignar_orden(oid, texto, yo):
    o = db.uno("SELECT id, nombre FROM ordenes WHERE id=?", (oid,))
    numero = numero_escrito(texto)
    if not o:
        return "No se encontró la orden."
    if not numero:
        return "Escribí el número de protocolo, por ejemplo C000123."
    existentes = protocolos_existentes([numero])
    if numero not in existentes:
        return f"El protocolo {numero} no existe."
    db.ex("UPDATE ordenes SET protocolo_id=?, metodo='manual', motivo=NULL, asignado_por=?, asignado_en=? WHERE id=?", (existentes[numero], yo, db.ahora(), oid))
    db.auditar(yo, existentes[numero], "orden", f"{(o['nombre'] or '')[:60]} (asignada a mano)")
    return None


def borrar_orden(oid, yo):
    o = db.uno("SELECT id, protocolo_id, nombre, imagen, miniatura FROM ordenes WHERE id=?", (oid,))
    if not o:
        return None
    db.ex("DELETE FROM ordenes WHERE id=?", (oid,))
    almacen.borrar(o["imagen"])
    almacen.borrar(o["miniatura"])
    db.auditar(yo, o["protocolo_id"], "orden_borrada", (o["nombre"] or "")[:80])
    return o["protocolo_id"]
