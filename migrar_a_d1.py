import os
import sqlite3
import sys

import db

TABLAS_CON_ARCHIVOS = ("firmas", "informes_emitidos")
PROPIAS = ("bloqueos",)


def orden_tablas(origen):
    tablas = [r[0] for r in origen.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    depende = {t: {r[2] for r in origen.execute(f"PRAGMA foreign_key_list({t})") if r[2] != t} for t in tablas}
    orden, pendientes = [], set(tablas)
    while pendientes:
        listas = sorted(t for t in pendientes if depende[t] <= set(orden))
        if not listas:
            raise RuntimeError("Hay referencias circulares entre tablas: " + ", ".join(sorted(pendientes)))
        orden += listas
        pendientes -= set(listas)
    return orden


def main(argumentos):
    if not db.MODO_D1:
        print("Primero activá el modo D1: definí CONTINGENCIA_D1=1 y las credenciales de Cloudflare (ver LEEME).")
        return 1
    ruta = next((a for a in argumentos if not a.startswith("--")), os.path.join(db.DATA, "contingencia.db"))
    if not os.path.exists(ruta):
        print(f"No existe la base local {ruta}")
        return 1
    origen = sqlite3.connect(ruta)
    origen.row_factory = sqlite3.Row
    tablas = [t for t in orden_tablas(origen) if t not in PROPIAS]
    cantidades = {t: origen.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tablas}
    destino = db._conectar()
    db.preparar_esquema(destino)
    ocupadas = {t: destino.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tablas}
    if any(ocupadas.values()):
        print("La base de Cloudflare D1 ya tiene datos, no se sube nada para no mezclarlos:")
        for t, n in ocupadas.items():
            if n:
                print(f"  {t}: {n} filas")
        return 1
    print(f"Base local: {ruta}")
    print("Se van a subir estas tablas a Cloudflare D1 (incluye datos de pacientes):")
    for t in tablas:
        print(f"  {t}: {cantidades[t]} filas")
    if "--si" not in argumentos and input("Escribí SI para continuar: ").strip() != "SI":
        print("Cancelado, no se subió nada.")
        return 1
    for t in tablas:
        columnas_destino = {r["name"] for r in destino.execute(f"PRAGMA table_info({t})")}
        columnas = [c for c in (r[1] for r in origen.execute(f"PRAGMA table_info({t})")) if c in columnas_destino]
        filas = [tuple(f[c] for c in columnas) for f in origen.execute(f"SELECT {', '.join(columnas)} FROM {t}")]
        sql = f"INSERT INTO {t} ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})"
        if t in TABLAS_CON_ARCHIVOS:
            for fila in filas:
                destino.execute(sql, fila)
        else:
            destino.executemany(sql, filas)
        print(f"  {t}: {len(filas)} filas subidas")
    distintas = []
    for t in tablas:
        n = destino.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        if n != cantidades[t]:
            distintas.append((t, cantidades[t], n))
    if distintas:
        print("ATENCIÓN: las cantidades no coinciden:", distintas)
        return 1
    db.inicializar()
    print("Listo: todas las tablas coinciden con la base local.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
