import argparse
import json
import sys
from datetime import datetime, timedelta

from vighi import crear_app
from vighi.core import db
from vighi.core.texto import sin_acentos

TIPOS = ("tentativa", "confirmada", "cargada")


def fecha_con_plazo(fecha_factura, dias):
    return (datetime.strptime(fecha_factura, "%Y-%m-%d") + timedelta(days=dias)).strftime("%Y-%m-%d")


def aplicar(facturas, imprimir=print):
    reales = {sin_acentos(r["valor"]): r["valor"] for r in db.q("SELECT valor FROM listas WHERE nombre='cobertura'")}
    plazos = {sin_acentos(r["cobertura"]): r["dias"] for r in db.q("SELECT cobertura, dias FROM cobertura_pago")}
    existentes = {r["numero"] for r in db.q("SELECT numero FROM facturas WHERE estado<>'anulada' AND numero IS NOT NULL")}
    cargadas, repetidas, calculadas, sin_cobertura, sin_plazo = [], [], [], set(), []
    ahora = db.ahora()
    for f in facturas:
        if f["numero"] in existentes:
            repetidas.append(f["numero"])
            continue
        cobertura = reales.get(sin_acentos(f["cobertura"]))
        if not cobertura:
            sin_cobertura.add(f["cobertura"])
            cobertura = f["cobertura"]
        fec, tipo, nota = f.get("fec"), f.get("fec_tipo") or "tentativa", ""
        if not fec:
            dias = plazos.get(sin_acentos(cobertura))
            if dias is not None and f.get("ff"):
                fec, tipo = fecha_con_plazo(f["ff"], dias), "tentativa"
                nota = f" Fecha estimada de cobro calculada con el plazo de la cobertura ({dias} días)."
                calculadas.append((f["numero"], cobertura, fec))
            else:
                sin_plazo.append((f["numero"], cobertura))
        alicuota = round(f["iva"] / f["gravado"], 4) if f.get("gravado") else 0.21
        observaciones = f"Cargada desde el sistema anterior (id {f.get('id')}), sin detalle de estudios.{nota}"
        db.ex("""INSERT INTO facturas (numero, estado, cobertura, fecha_factura, fecha_estimada_cobro, fec_tipo, exento, gravado, iva, total, alicuota,
                                       observaciones, creado_en, emitida_en)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (f["numero"], "emitida", cobertura, f.get("ff"), fec, tipo if tipo in TIPOS else "tentativa", f["exento"], f["gravado"], f["iva"], f["total"],
               alicuota, observaciones, ahora, ahora))
        cargadas.append(f)
        existentes.add(f["numero"])
    return {"cargadas": cargadas, "repetidas": repetidas, "calculadas": calculadas, "sin_cobertura": sorted(sin_cobertura), "sin_plazo": sin_plazo}


def main(argumentos):
    p = argparse.ArgumentParser(description="Carga las facturas emitidas pendientes de cobro tomadas del sistema anterior.")
    p.add_argument("archivo")
    p.add_argument("--si", action="store_true", help="no pedir confirmación")
    args = p.parse_args(argumentos)
    with open(args.archivo, encoding="utf-8") as f:
        facturas = json.load(f)["facturas"]
    total = sum(f["total"] for f in facturas)
    print(f"{len(facturas)} facturas emitidas, total ${total:,.2f}.")
    if not args.si and input("Escribí SI para guardar en la base: ").strip() != "SI":
        print("Cancelado, no se guardó nada.")
        return 1
    db.inicializar()
    with crear_app().app_context():
        r = aplicar(facturas)
        db.auditar(None, None, "cobros_cargados", f"{len(r['cargadas'])} facturas emitidas del sistema anterior")
    print(f"Listo: {len(r['cargadas'])} facturas cargadas, {len(r['repetidas'])} ya existían.")
    for numero, cobertura, fec in r["calculadas"]:
        print(f"  {numero} · {cobertura}: sin fecha estimada, se calculó {fec} con el plazo de la cobertura")
    for numero, cobertura in r["sin_plazo"]:
        print(f"  {numero} · {cobertura}: sin fecha estimada y la cobertura no tiene plazo de cobro")
    if r["sin_cobertura"]:
        print("Coberturas que no están en nuestra lista (se guardaron con el nombre del sistema anterior):", ", ".join(r["sin_cobertura"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
