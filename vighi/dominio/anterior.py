import re
import unicodedata
from collections import OrderedDict

from vighi.dominio.estudios.base import ETAPAS

ETAPA_DE = {v[4]: k for k, v in ETAPAS.items() if k != "ingreso"}
CARGA = "Protocolo > Cargar"
TIPO_DE = {"BP": "BP", "BPC": "BP", "PAP": "PAP", "CT": "CT", "LIQ": "CT"}
FRAGMENTOS_VARIOS = 4
INCLUSIONES = {"R": "Reserva", "IT": "Inclusión total"}
PRACTICAS_ADMINISTRATIVAS = ("intraoperatoria", "presencia de patologo")
RE_TITULO = re.compile(r"^#?(P\d+)-(\w+)")
RE_TECNICA = re.compile(r"(?:^|\s)([A-Z]{1,2}\d*)\s+(V|\d+)F/(R|IT)/(\d+)C$")
RE_FECHA = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?")
RE_ANIO = re.compile(r"\((\d{4})\)")
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}
RE_COMENTARIO = re.compile(r"(\d{1,2})\s+([a-z]{3})[a-z]*\.?\s+(\d{1,2}):(\d{2})", re.I)


def sin_acentos(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")


def clave(texto):
    return re.sub(r"[^a-z0-9]+", " ", sin_acentos(texto).lower()).strip()


def numero_de(texto):
    return re.sub(r"[^A-Za-z0-9]", "", texto or "")


def fecha_iso(texto):
    m = RE_FECHA.search(texto or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def fecha_hora(texto):
    m = RE_FECHA.search(texto or "")
    if not m:
        return None
    hora = f"{int(m.group(4) or 0):02d}:{m.group(5) or '00'}:00"
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d} {hora}"


def fecha_hora_comentario(texto, anio):
    m = RE_COMENTARIO.search(texto or "")
    if not m or m.group(2).lower() not in MESES:
        return None
    return f"{anio}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d} {int(m.group(3)):02d}:{m.group(4)}:00"


def tipo_de(titulo):
    m = RE_TITULO.match(titulo or "")
    base = TIPO_DE.get(m.group(2)) if m else None
    return {"tipo": base, "numero": m.group(1) if m else None, "ihq": "c/IHQ" in (titulo or ""), "urgente": "(U)" in (titulo or "")}


def partir_nombre(texto):
    apellido, _, nombre = (texto or "").partition(",")
    return apellido.strip(), nombre.strip()


def entero(texto, defecto=None):
    m = re.search(r"\d+", texto or "")
    return int(m.group()) if m else defecto


def parsear_tecnica(texto):
    m = RE_TECNICA.search((texto or "").strip())
    if not m:
        return None
    fragmentos = FRAGMENTOS_VARIOS if m.group(2) == "V" else min(int(m.group(2)), FRAGMENTOS_VARIOS)
    return {"numero": m.group(1), "fragmentos": fragmentos, "inclusion": INCLUSIONES[m.group(3)], "cassettes": int(m.group(4))}


def cobertura_y_plan(encabezado, cobertura_paciente):
    cobertura = (cobertura_paciente or "").strip()
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", encabezado or "")
    if m:
        return (cobertura or m.group(1).strip()), m.group(2).strip()
    return (cobertura or (encabezado or "").strip()), ""


def etapas_de(tracking):
    vistas = OrderedDict()
    for t in tracking or []:
        etapa = ETAPA_DE.get(t.get("accion"))
        fecha = fecha_hora(t.get("completada"))
        if etapa and fecha and etapa not in vistas:
            vistas[etapa] = {"etapa": etapa, "usuario": (t.get("usuario") or "").strip(), "fecha_hora": fecha}
    return list(vistas.values())


def pide_decal(flujo):
    acciones = [t.get("accion") for t in (flujo.get("tracking") or []) + (flujo.get("pendientes") or [])]
    return "Macro > Decal" in acciones


def es_practica_administrativa(nombre):
    return clave(nombre) in PRACTICAS_ADMINISTRATIVAS


def es_muestra(fila):
    return bool(fila.get("orden")) or bool((fila.get("detalle") or {}).get("zona"))


def estudio_de(fila, tipo, tecnicas):
    d = fila.get("detalle") or {}
    tacos = entero(d.get("tacos") or fila.get("tacos"), 1)
    mia = next((t for t in tecnicas if t["numero"] == (fila.get("orden") or "")), None)
    return {"orden": fila.get("orden"), "tipo": tipo, "categoria": d.get("tipo") or ("Citologías" if tipo != "BP" else "Biopsias"),
            "subcategoria": d.get("zona") or None, "sitio": d.get("organo") or fila.get("organo") or None, "tipo_muestra": fila.get("nombre") or None,
            "observaciones": d.get("libre") or fila.get("libre") or None, "tacos": tacos, "nomenclador": d.get("nomenclador"),
            "tecnica": dict(mia, tacos=tacos) if mia else None}


def comentarios_de(grupo):
    vistos, salida = set(), []
    for g in grupo:
        for fila in g.get("estudios") or []:
            for c in (fila.get("detalle") or {}).get("comentarios") or []:
                llave = (c.get("usuario"), c.get("fecha"), c.get("texto"))
                if c.get("texto") and llave not in vistos:
                    vistos.add(llave)
                    salida.append({"autor": c.get("usuario"), "fecha": c.get("fecha"), "texto": c.get("texto")})
    return salida


def imagenes_de(formularios_por_flujo):
    vistas, salida = set(), []
    for formularios in formularios_por_flujo.values():
        for f in formularios or []:
            for i in f.get("imagenes") or []:
                url = i.get("url")
                if url and url not in vistas:
                    vistas.add(url)
                    salida.append({"url": url, "tipo": (i.get("tipo") or "").strip()})
    return salida


def practicas_de(flujo):
    salida = []
    for fila in flujo.get("estudios") or []:
        if not es_muestra(fila):
            d = fila.get("detalle") or {}
            salida.append({"nombre": fila.get("nombre"), "nomenclador": d.get("nomenclador"), "unidades": entero(d.get("unidades"), 1)})
    return salida


def pap_de(campos):
    def texto(*claves):
        valor = next((campos[k] for k in claves if campos.get(k)), "")
        return re.sub(r"^\[[-+]*\]\s*", "", valor).strip()
    datos = {"leucocitos": texto("DD_Leucocitos"), "hematies": texto("DD_Hematies"), "flora": texto("tb_Flora"), "aspecto": texto("tb_Aspecto"), "otros": texto("tb_Otros"),
             "pavimentosas": texto("tb_Pavimentosas"), "endocervicales": texto("tb_Endocervicales"), "metaplasicas": texto("tb_Metaplasticas"),
             "endometriales": texto("tb_Endometriales"), "resultado": texto("tb_Diagnostico"), "conclusion": texto("tb_Observaciones")}
    cargado = any(datos[k] for k in ("flora", "aspecto", "otros", "pavimentosas", "endocervicales", "metaplasicas", "endometriales", "resultado", "conclusion"))
    return datos if cargado else None


def micro_de(flujo, formularios):
    campos = {}
    for f in formularios or []:
        if f.get("form", "").startswith("micro/pap") and flujo["base"] == "PAP":
            return {"pap": pap_de(f.get("campos") or {})}
        if f.get("form", "").startswith("micro/bp") and flujo["base"] != "PAP":
            campos = f.get("campos") or {}
    descripcion = campos.get("tb_micro") or flujo.get("micro") or None
    conclusion = campos.get("tb_diagnostico") or None
    return {"descripcion": descripcion, "conclusion": conclusion, "observaciones": campos.get("tb_observaciones") or None} if (descripcion or conclusion) else None


def macro_de(flujo, formularios, tecnicas):
    texto = flujo.get("macro") or None
    for f in formularios or []:
        if (f.get("campos") or {}).get("tb_macro"):
            texto = f["campos"]["tb_macro"]
            break
    if not texto and not tecnicas:
        return None
    return {"descripcion": texto, "cassettes": sum(t["cassettes"] for t in tecnicas) or None, "decal": 1 if pide_decal(flujo) else 0, "autor": flujo.get("autor_macro") or None}


def flujo_de(flujo, formularios):
    info = tipo_de(flujo.get("titulo"))
    if not info["tipo"]:
        return None
    tecnicas = [t for t in (parsear_tecnica(x) for x in flujo.get("tecnicas") or []) if t]
    estudios = [estudio_de(f, info["tipo"], tecnicas) for f in flujo.get("estudios") or [] if es_muestra(f)]
    practicas = practicas_de(flujo)
    return {"tipo": info["tipo"], "base": info["tipo"], "titulo": flujo.get("titulo"), "ihq": info["ihq"], "urgente": info["urgente"], "estudios": estudios,
            "practicas": practicas, "etapas": etapas_de(flujo.get("tracking")), "macro": macro_de(dict(flujo, base=info["tipo"]), formularios, tecnicas),
            "micro": micro_de(dict(flujo, base=info["tipo"]), formularios), "firmante": flujo.get("firmante"), "asignado": flujo.get("asignado"),
            "lote": (flujo.get("lote") or {}).get("nombre"), "lote_tipo": flujo.get("lote_tipo"), "pendientes": [p.get("accion") for p in flujo.get("pendientes") or []],
            "idf": flujo.get("idf")}


def separar_practicas(practicas, con_ihq, tecnicas_conocidas):
    tecnicas, marcadores, administrativas = [], [], []
    for p in practicas:
        nombre = (p.get("nombre") or "").strip()
        if not nombre:
            continue
        if es_practica_administrativa(nombre):
            administrativas.append(p)
        elif clave(nombre) in tecnicas_conocidas or not con_ihq:
            tecnicas.append(nombre)
        else:
            marcadores.append(nombre)
    return list(dict.fromkeys(tecnicas)), list(dict.fromkeys(marcadores)), administrativas


def juntar_flujos(flujos):
    por_tipo = OrderedDict()
    for f in flujos:
        previo = por_tipo.get(f["tipo"])
        if not previo:
            por_tipo[f["tipo"]] = f
            continue
        previo["estudios"] += f["estudios"]
        previo["practicas"] += f["practicas"]
        previo["ihq"] = previo["ihq"] or f["ihq"]
        previo["urgente"] = previo["urgente"] or f["urgente"]
        previo["macro"] = previo["macro"] or f["macro"]
        previo["micro"] = previo["micro"] or f["micro"]
        hechas = {e["etapa"] for e in previo["etapas"]}
        previo["etapas"] += [e for e in f["etapas"] if e["etapa"] not in hechas]
        previo["lote"] = previo["lote"] or f["lote"]
    return list(por_tipo.values())


def observaciones_de(numero, paciente, flujos, urgente):
    lineas = [f"Migrado del sistema anterior ({numero})."]
    anio = RE_ANIO.search((paciente or {}).get("edad") or "")
    if anio:
        lineas.append(f"Año de nacimiento: {anio.group(1)}.")
    if urgente:
        lineas.append("Urgente en el sistema anterior.")
    extras = [f"{p['nombre']} ({p['nomenclador']})" + (f" x{p['unidades']}" if p["unidades"] > 1 else "")
              for f in flujos for p in f["practicas"] if es_practica_administrativa(p["nombre"])]
    if extras:
        lineas.append("Prácticas del sistema anterior: " + ", ".join(extras) + ".")
    return "\n".join(lineas)


def protocolo_de(grupo, paciente, formularios_por_flujo):
    flujos = [f for f in (flujo_de(x, formularios_por_flujo.get(x.get("idf"))) for x in grupo) if f]
    if not flujos:
        return None
    primero = grupo[0]
    flujos = juntar_flujos(flujos)
    paciente = paciente or {}
    numero = numero_de(primero.get("numero"))
    cobertura, plan = cobertura_y_plan(primero.get("cobertura"), paciente.get("cobertura"))
    apellido, nombre = partir_nombre(paciente.get("nombre") or (primero.get("paciente") or {}).get("nombre"))
    provisorio = not apellido
    carga = next((e for g in grupo for e in [t for t in (g.get("tracking") or []) if t.get("accion") == CARGA and t.get("completada")]), None)
    return {"numero": numero, "fecha_recoleccion": fecha_iso(primero.get("recoleccion")), "dni": re.sub(r"\D", "", paciente.get("dni") or primero.get("dni") or "") or None,
            "apellido": apellido or None, "nombre": nombre or None, "provisorio": provisorio, "sexo": paciente.get("sexo") or None, "email": (paciente.get("email") or "").lower() or None,
            "telefono": paciente.get("telefono") or None, "cobertura": cobertura or None, "plan": plan or None,
            "n_afiliado": numero_de(paciente.get("credencial") or primero.get("credencial")) or None,
            "exento": "Si" if clave(paciente.get("iva")) == "exento" else ("No" if paciente.get("iva") else None),
            "medico": ((primero.get("medico") or {}).get("nombre") or None), "lugar_recoleccion": (primero.get("procedencia") or {}).get("nombre") or None,
            "lugar_entrega": (primero.get("entrega") or {}).get("nombre") or None, "validado": "Validado" in (primero.get("validado") or ""),
            "observaciones": observaciones_de(numero, paciente, flujos, any(f["urgente"] for f in flujos)),
            "ingreso": {"usuario": (carga or {}).get("usuario"), "fecha_hora": fecha_hora((carga or {}).get("completada")) or (fecha_iso(primero.get("recoleccion")) + " 00:00:00" if primero.get("recoleccion") else None)},
            "comentarios": comentarios_de(grupo), "imagenes": imagenes_de(formularios_por_flujo), "flujos": flujos}
