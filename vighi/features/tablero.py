import io
from datetime import datetime

from flask import Blueprint, render_template, request, send_file

from vighi.core import db
from vighi.core.config import SEMAFOROS
from vighi.core.fechas import fecha, fecha_hora
from vighi.core.sesion import requiere_login, requiere_permiso, usuario_actual
from vighi.dominio import informes, trazabilidad
from vighi.dominio.estudios import NOMBRE_ETAPA, SECTORES
from vighi.servicios.consultas import cargar_estudios
from vighi.servicios.lotes import orden_numero
from vighi.servicios.protocolos import ediciones_en_curso
from vighi.servicios.validacion import pendientes as pendientes_de_validar

bp = Blueprint("tablero", __name__)


@bp.route("/")
@requiere_login
def tablero():
    yo = usuario_actual()
    f = {k: request.args.get(k, "") for k in ("q", "tipo", "ver", "sector", "etapa", "semaforo", "ubicacion", "mf")}
    f["ver"] = f["ver"] or "pendientes"
    grupos = {}
    for e in cargar_estudios():
        grupos.setdefault(e["protocolo_id"], []).append(e)
    mis = set((yo["sectores"] or "").split(","))
    conteo = {"pendientes": 0, "informados": 0, "sin_cargar": 0}
    for g in grupos.values():
        activos = [e for e in g if not e["anulado"]]
        if any(e["proxima"] for e in activos):
            conteo["pendientes"] += 1
        elif activos:
            conteo["informados"] += 1
            if not activos[0]["cargado_sistema"]:
                conteo["sin_cargar"] += 1

    def del_ver(g):
        activos = [e for e in g if not e["anulado"]]
        pendientes = [e for e in activos if e["proxima"]]
        v = f["ver"]
        if v == "pendientes":
            return bool(pendientes)
        if v == "mios":
            return any(e["proxima"][2] in mis for e in pendientes)
        if v == "informados":
            return bool(activos) and not pendientes
        if v == "sin_cargar":
            return bool(activos) and not pendientes and not activos[0]["cargado_sistema"]
        if v == "anulados":
            return any(e["anulado"] for e in g)
        return True

    def estudio_ok(e):
        if f["tipo"] and e["tipo"] != f["tipo"]:
            return False
        if f["sector"] and not (e["proxima"] and e["proxima"][2] == f["sector"]):
            return False
        if f["etapa"] and not (e["proxima"] and e["proxima"][0] == f["etapa"]):
            return False
        return True

    def con_texto(g):
        q = f["q"].lower()
        return any(q in " ".join(str(e[k] or "") for k in ("numero", "apellido", "nombre", "dni", "lote", "sitio")).lower() for e in g)

    firmantes = db.q("SELECT iniciales, nombre FROM usuarios WHERE activo=1 AND (',' || sectores || ',') LIKE '%,firmante,%' ORDER BY iniciales")
    pap = db.uno("SELECT iniciales FROM usuarios WHERE LOWER(nombre) LIKE ? AND activo=1 ORDER BY id LIMIT 1", (f"%{informes.FIRMANTE_PAP}%",))

    def firmante_de(g):
        activos = [e for e in g if not e["anulado"]]
        if pap and activos and all(e["tipo"] == "PAP" for e in activos):
            return pap["iniciales"]
        return next((e["responsable"] for e in activos if e["responsable"] in {u["iniciales"] for u in firmantes}), "")

    filas = []
    for g in grupos.values():
        if not del_ver(g) or (f["q"] and not con_texto(g)):
            continue
        if f["ubicacion"] and f["ubicacion"] not in (g[0]["lugar_recoleccion"], g[0]["lugar_entrega"]):
            continue
        if f["mf"] and f["mf"] != firmante_de(g):
            continue
        elegidos = [e for e in g if estudio_ok(e)]
        if f["ver"] == "anulados":
            vista = [e for e in elegidos if e["anulado"]]
        elif f["ver"] in ("pendientes", "mios"):
            vista = [e for e in elegidos if not e["anulado"] and e["proxima"] and (f["ver"] != "mios" or e["proxima"][2] in mis)]
        else:
            vista = [e for e in elegidos if not e["anulado"]] or elegidos
        if not vista:
            continue
        primero = g[0]
        estados = list(dict.fromkeys((e["estado"], SECTORES[e["proxima"][2]] if e["proxima"] else "", bool(e["anulado"]), not e["proxima"]) for e in vista))
        vencen = [e["vence"] for e in vista if e["vence"]]
        filas.append({
            "protocolo_id": primero["protocolo_id"], "numero": primero["numero"], "flujos": primero["flujos"],
            "n_comentarios": primero.get("n_comentarios"), "estudios": sum(1 for e in g if not e["anulado"]),
            "apellido": primero["apellido"], "nombre": primero["nombre"], "dni": primero["dni"], "validar": primero["pendiente_validacion"],
            "muestras": list(dict.fromkeys((e["subcategoria"] or "", e["tipo_muestra"] or "") for e in vista)),
            "lote_id": primero["lote_id"], "lote": primero["lote"],
            "responsables": list(dict.fromkeys(e["responsable"] for e in vista if e["responsable"])),
            "estados": estados,
            "semaforo": max((e["semaforo"] for e in vista), key=lambda s: trazabilidad.GRAVEDAD[s or ""]),
            "vence": min(vencen) if vencen else None,
            "creado_en": min(e["creado_en"] for e in g)})
    filas.sort(key=lambda r: (orden_numero(r["numero"])[0].upper() == "C", orden_numero(r["numero"]), r["protocolo_id"]), reverse=True)
    por_semaforo = {k: sum(1 for r in filas if r["semaforo"] == k) for k in SEMAFOROS}
    if f["semaforo"]:
        filas = [r for r in filas if r["semaforo"] == f["semaforo"]]
    lugares = sorted({l for g in grupos.values() for l in (g[0]["lugar_recoleccion"], g[0]["lugar_entrega"]) if l} | ({f["ubicacion"]} if f["ubicacion"] else set()), key=db.clave_nombre)
    return render_template("tablero/tablero.html", filas=filas, f=f, conteo=conteo, por_semaforo=por_semaforo, lugares=lugares, firmantes=firmantes,
                           etapas=[(k, n) for k, n in NOMBRE_ETAPA.items() if k != "ingreso"])


@bp.route("/completar")
@requiere_permiso("protocolo_crear")
def completar():
    lote_sel = request.args.get("lote", "")
    filtro = ("e.lote_id=?", (int(lote_sel),)) if lote_sel.isdigit() else ("1=1", ())
    protocolos = {}
    for e in cargar_estudios("p.borrador=1 AND " + filtro[0], filtro[1], borradores=True):
        protocolos.setdefault(e["protocolo_id"], {"id": e["protocolo_id"], "numero": e["numero"],
                                                  "fecha_recoleccion": e["fecha_recoleccion"], "estudios": []})["estudios"].append(e)
    lotes_con = db.q("""SELECT l.id, l.codigo, COUNT(DISTINCT p.id) AS n FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id
                        JOIN lotes l ON l.id=e.lote_id WHERE p.borrador=1 GROUP BY l.id, l.codigo, l.fecha ORDER BY l.fecha DESC, l.codigo""")
    return render_template("tablero/completar.html", protocolos=sorted(protocolos.values(), key=lambda x: x["numero"]),
                           lotes_con=lotes_con, lote_sel=lote_sel, ediciones=ediciones_en_curso(), n_validar=len(pendientes_de_validar()))


@bp.route("/exportar")
@requiere_permiso("exportar")
def exportar():
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    etapas = {}
    for x in db.q("SELECT x.flujo_id, x.etapa, x.fecha_hora, u.iniciales FROM etapas x JOIN usuarios u ON u.id=x.usuario_id"):
        etapas.setdefault(x["flujo_id"], {})[x["etapa"]] = x
    macro = {r["flujo_id"]: r for r in db.q("SELECT * FROM macro")}
    micro = {r["flujo_id"]: r for r in db.q("SELECT * FROM micro")}
    ihq = {r["flujo_id"]: r for r in db.q("SELECT * FROM ihq")}
    protocolos = {r["id"]: r for r in db.q("SELECT * FROM protocolos")}
    orden_etapas = [k for k in NOMBRE_ETAPA if k != "ingreso"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estudios"
    cab = (["N° Protocolo", "Estudio", "Estado", "Lote", "Anulado", "Protocolo sistema", "Cargado en sistema", "Responsable",
            "Ingresado", "Fecha recolección", "DNI", "Apellido", "Nombre", "Sexo", "Fecha nacimiento", "Cobertura",
            "N° afiliado", "Exento", "E-mail", "Teléfono", "Médico", "Lugar recolección", "Lugar entrega",
            "Observaciones protocolo", "Categoría", "Subcategoría", "Sitio", "Tipo de muestra", "Cantidad",
            "Citología hormonal", "Observaciones estudio",
            "Template macro", "Descripción macro", "Cassettes", "Template micro", "Descripción micro", "Conclusión",
            "Bethesda", "Técnicas especiales", "Solicita IHQ", "Marcadores IHQ", "Resultado IHQ"]
           + [f"{NOMBRE_ETAPA[k]} - {x}" for k in orden_etapas for x in ("usuario", "fecha/hora")])
    ws.append(cab)
    for e in cargar_estudios():
        p = protocolos[e["protocolo_id"]]
        ma, mi, ih, et = macro.get(e["flujo_id"]), micro.get(e["flujo_id"]), ihq.get(e["flujo_id"]), etapas.get(e["flujo_id"], {})
        g = lambda r, k: (r[k] if r else "") or ""
        fila = [p["numero"], e["etiqueta"], e["estado"], e["lote"], "Si" if e["anulado"] else "", p["protocolo_sistema"],
                "Si" if p["cargado_sistema"] else "No", e["responsable"], fecha_hora(e["creado_en"]),
                fecha(p["fecha_recoleccion"]), p["dni"], p["apellido"], p["nombre"], p["sexo"], fecha(p["fecha_nacimiento"]),
                p["cobertura"], p["n_afiliado"], p["exento"], p["email"], p["telefono"], p["medico"], p["lugar_recoleccion"],
                p["lugar_entrega"], p["observaciones"], e["categoria"], e["subcategoria"], e["sitio"], e["tipo_muestra"],
                e["cantidad"], e["citologia_hormonal"], e["observaciones"],
                g(ma, "template"), g(ma, "descripcion"), g(ma, "cassettes"),
                g(mi, "template"), g(mi, "descripcion"), g(mi, "conclusion"), g(mi, "resultado") or g(mi, "bethesda"),
                e["tecnicas_especiales"] or g(mi, "tecnicas_especiales"), "Si" if mi and mi["solicita_ihq"] else "", g(ih, "marcadores"), g(ih, "resultado")]
        for k in orden_etapas:
            x = et.get(k)
            fila += [x["iniciales"] if x else "", fecha_hora(x["fecha_hora"]) if x else ""]
        ws.append(fila)
    for i, cell in enumerate(ws[1], start=1):
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="5B2C83")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = 16
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    db.auditar(usuario_actual()["id"], None, "exportar")
    return send_file(buf, as_attachment=True, download_name=f"contingencia_{datetime.now():%Y%m%d_%H%M}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
