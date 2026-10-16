import argparse
import json
import os
import sys
from collections import Counter, OrderedDict

from vighi.dominio import anterior

CARPETA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "migracion_anterior")


def leer_lineas(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def cargar(carpeta):
    flujos = leer_lineas(os.path.join(carpeta, "flujos.jsonl"))
    pacientes = {p["id"]: p for p in leer_lineas(os.path.join(carpeta, "pacientes.jsonl"))}
    formularios = {}
    for f in leer_lineas(os.path.join(carpeta, "formularios.jsonl")):
        formularios[(f["idp"], f["idf"])] = f.get("formularios") or []
    return flujos, pacientes, formularios


def agrupar(flujos):
    grupos = OrderedDict()
    for f in flujos:
        grupos.setdefault(f["idp"], {})[f["idf"]] = f
    return {idp: list(por_idf.values()) for idp, por_idf in grupos.items()}


def preparar(carpeta):
    flujos, pacientes, formularios = cargar(carpeta)
    registros, descartados = [], []
    for idp, grupo in agrupar(flujos).items():
        paciente = pacientes.get((grupo[0].get("paciente") or {}).get("id"))
        por_flujo = {g["idf"]: formularios.get((idp, g["idf"])) for g in grupo}
        registro = anterior.protocolo_de(grupo, paciente, por_flujo)
        if registro is None:
            descartados.append((idp, [g.get("titulo") for g in grupo]))
        else:
            registro["idp"] = idp
            registros.append(registro)
    return registros, descartados, len(flujos), len(pacientes), len(formularios)


def resumen(registros):
    tipos = Counter(f["tipo"] for r in registros for f in r["flujos"])
    sin = {"sin paciente": sum(1 for r in registros if not r["apellido"]), "sin DNI": sum(1 for r in registros if not r["dni"]),
           "sin médico": sum(1 for r in registros if not r["medico"]), "sin lote": sum(1 for r in registros for f in r["flujos"] if not f["lote"]),
           "sin estudios": sum(1 for r in registros for f in r["flujos"] if not f["estudios"])}
    return tipos, sin, Counter(e["etapa"] for r in registros for f in r["flujos"] for e in f["etapas"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Normaliza lo extraído de southernbits y arma el archivo que se sube a la pantalla Migración.")
    ap.add_argument("--carpeta", default=CARPETA)
    args = ap.parse_args(argv)
    registros, descartados, n_flujos, n_pacientes, n_formularios = preparar(args.carpeta)
    destino = os.path.join(args.carpeta, "protocolos_anterior.jsonl")
    with open(destino, "w", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tipos, sin, etapas = resumen(registros)
    print(f"Flujos leídos: {n_flujos} · pacientes: {n_pacientes} · formularios de micro: {n_formularios}")
    print(f"Protocolos armados: {len(registros)} · descartados: {len(descartados)}")
    print("Flujos por tipo:", dict(tipos))
    print("Faltantes:", sin)
    print("Etapas hechas:", dict(etapas))
    for idp, titulos in descartados[:10]:
        print("  descartado", idp, titulos)
    print("Archivo:", destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
