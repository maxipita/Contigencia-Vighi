from flask import abort

from vighi.core import db
from vighi.core.fechas import hoy
from vighi.core.texto import sin_acentos
from vighi.dominio import facturacion
from vighi.servicios.consultas import cargar_estudios, listas
from vighi.servicios.lotes import orden_numero


def coberturas_lista():
    return listas().get("cobertura", [])


def factura_o_404(fid):
    return db.uno("""SELECT f.*, uc.iniciales AS creador, ue.iniciales AS emisor, ub.iniciales AS cobrador, ua.iniciales AS anulador
                     FROM facturas f LEFT JOIN usuarios uc ON uc.id=f.creado_por LEFT JOIN usuarios ue ON ue.id=f.emitida_por
                     LEFT JOIN usuarios ub ON ub.id=f.cobrada_por LEFT JOIN usuarios ua ON ua.id=f.anulada_por WHERE f.id=?""", (fid,)) or abort(404)


def items_de_factura(fid):
    return db.q("SELECT * FROM factura_items WHERE factura_id=? ORDER BY numero_protocolo, id", (fid,))


def facturacion_buscar(f):
    proto = {r["id"]: r for r in db.q("SELECT id, cobertura, n_afiliado, exento, lugar_recoleccion FROM protocolos")}
    facturados = facturacion.ids_facturados()
    ctx = facturacion.contexto()
    q = f["q"].strip().lower()
    cobertura = sin_acentos(f["cobertura"])
    out = []
    for e in cargar_estudios():
        p = proto.get(e["protocolo_id"])
        if e["anulado"] or not p:
            continue
        if f["tipo"] and e["tipo"] != f["tipo"]:
            continue
        if f["flujo"] and not (e["solicita_ihq"] if f["flujo"] == "IHQ" else e["tipo"] == f["flujo"]):
            continue
        if f["clase"] == "biop" and e["tipo"] != "BP":
            continue
        if f["clase"] == "cito" and e["tipo"] not in ("CT", "PAP"):
            continue
        if f["clase"] == "ihq" and not e["solicita_ihq"]:
            continue
        if f["prioridad"] == "ihq" and not e["solicita_ihq"]:
            continue
        if f["prioridad"] == "te" and not (e["tecnicas_especiales"] or "").strip():
            continue
        if f["zona"] and (e["subcategoria"] or "") != f["zona"]:
            continue
        if f["procedencia"] and (p["lugar_recoleccion"] or "").strip() != f["procedencia"]:
            continue
        if cobertura and sin_acentos(p["cobertura"]) != cobertura:
            continue
        fecha_e = facturacion.fecha_de_estudio(e)
        if f["desde"] and fecha_e < f["desde"]:
            continue
        if f["hasta"] and fecha_e > f["hasta"]:
            continue
        informado = not e["proxima"]
        if (f["informados"] == "si" and not informado) or (f["informados"] == "no" and informado):
            continue
        ya = facturados.get(e["id"])
        if (f["facturados"] == "no" and ya) or (f["facturados"] == "si" and not ya):
            continue
        if q and q not in " ".join(str(x or "") for x in (e["numero"], e["apellido"], e["nombre"], e["dni"], p["n_afiliado"])).lower():
            continue
        tarifa = facturacion.resolver(ctx, p["cobertura"], e["tipo"], e["sitio"], e["tipo_muestra"], fecha_e or hoy())
        iva = facturacion.iva_de(tarifa, p["exento"])
        if f["iva"] and iva != f["iva"]:
            continue
        cantidad = facturacion.cantidad_de(e["cantidad"])
        out.append({"id": e["id"], "protocolo_id": e["protocolo_id"], "numero": e["numero"], "fecha": fecha_e, "tipo": e["tipo"],
                    "paciente": (e["apellido"] or "") + (", " + e["nombre"] if e["nombre"] else ""), "afiliado": p["n_afiliado"] or "",
                    "cobertura": p["cobertura"] or "", "etiqueta": e["etiqueta"], "informado": informado, "factura_id": ya, "tarifa": tarifa["ok"],
                    "motivo": tarifa.get("motivo", ""), "codigo": tarifa.get("codigo", ""), "cantidad": cantidad,
                    "unitario": tarifa.get("importe"), "iva": iva,
                    "importe": facturacion.importe_linea(cantidad, tarifa["importe"]) if tarifa["ok"] else None})
    out.sort(key=lambda r: (orden_numero(r["numero"]), r["id"]))
    return out


def dos_decimales(v):
    return f"{v:.2f}".replace(".", ",")
