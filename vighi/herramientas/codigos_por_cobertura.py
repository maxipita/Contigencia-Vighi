import argparse
import sys

from vighi import crear_app
from vighi.core import db
from vighi.core.texto import sin_acentos
from vighi.dominio import facturacion
from vighi.servicios.facturas import importar_asignaciones, planilla_de_tarifa


def tarifa_de(cobertura):
    filas = db.q("SELECT c.cobertura, t.id, t.nombre FROM tarifario_coberturas c JOIN tarifarios t ON t.id=c.tarifario_id WHERE c.plan=''")
    for f in filas:
        if sin_acentos(f["cobertura"]) == sin_acentos(cobertura):
            return f["id"], f["nombre"]
    for f in db.q("SELECT id, nombre FROM tarifarios"):
        if sin_acentos(f["nombre"]) == sin_acentos(cobertura):
            return f["id"], f["nombre"]
    asignadas = ", ".join(sorted(f["cobertura"] for f in filas)) or "ninguna"
    raise SystemExit(f"«{cobertura}» no tiene una tarifa asignada. Coberturas con tarifa: {asignadas}.")


def exportar(args):
    tid, nombre = tarifa_de(args.cobertura)
    salida = args.archivo or f"codigos_{sin_acentos(args.cobertura).replace(' ', '_')}.csv"
    with open(salida, "w", encoding="utf-8", newline="") as f:
        f.write(planilla_de_tarifa(tid))
    cargadas = db.uno("SELECT COUNT(*) AS n FROM nomenclador_muestras WHERE tarifario_id=?", (tid,))["n"]
    print(f"Planilla de {args.cobertura} (tarifa {nombre}) guardada en {salida}: completá la columna Nomenclador y volvé a importarla. Hoy tiene {cargadas} asignaciones.")
    return 0


def importar(args):
    tid, nombre = tarifa_de(args.cobertura)
    with open(args.archivo, encoding="utf-8-sig") as f:
        texto = f.read()
    nuevas, errores, sin_codigo = facturacion.leer_asignaciones(texto)
    print(f"Tarifa {nombre}: {len(nuevas)} asignaciones para cargar, {sin_codigo} líneas sin nomenclador (se omiten), {len(errores)} con error.")
    for e in errores[:10]:
        print("  " + e)
    if errores:
        return 1
    if not args.si and input("Escribí SI para guardar en la base: ").strip() != "SI":
        print("Cancelado, no se guardó nada.")
        return 1
    cantidad, errores, _ = importar_asignaciones(tid, texto)
    for e in errores:
        print("  " + e)
    if errores:
        print("No se guardó nada.")
        return 1
    db.auditar(None, None, "nomenclador_muestra", f"{nombre}: {cantidad} asignaciones importadas por herramienta")
    print(f"Listo: {cantidad} asignaciones guardadas en {nombre}.")
    return 0


def main(argumentos):
    p = argparse.ArgumentParser(description="Códigos de facturación por tipo de muestra y cobertura.")
    sub = p.add_subparsers(dest="orden", required=True)
    e = sub.add_parser("exportar", help="genera la planilla con todos los tipos de muestra y el código actual de la cobertura")
    e.add_argument("cobertura")
    e.add_argument("archivo", nargs="?")
    e.set_defaults(funcion=exportar)
    i = sub.add_parser("importar", help="carga la planilla completada")
    i.add_argument("cobertura")
    i.add_argument("archivo")
    i.add_argument("--si", action="store_true", help="no pedir confirmación")
    i.set_defaults(funcion=importar)
    args = p.parse_args(argumentos)
    with crear_app().app_context():
        return args.funcion(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
