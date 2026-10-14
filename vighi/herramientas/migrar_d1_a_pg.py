import hashlib
import sys

from vighi.core import almacen
from vighi.core import d1
from vighi.core import db
from vighi.core import pg
INTERNAS = ("sqlite_", "_cf_", "d1_")
CON_ARCHIVOS = {"imagenes": ("imagen", "miniatura"), "firmas": ("imagen",), "informes_emitidos": ("pdf",)}
FILAS_POR_PAGINA = 200
ARCHIVOS_POR_PAGINA = 3


def tablas_origen(origen):
    nombres = [r["name"] for r in origen.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return [n for n in nombres if not n.startswith(INTERNAS)]


def columnas_destino(destino, tabla):
    filas = destino._cx().execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s "
                                  "ORDER BY ordinal_position", (tabla,)).fetchall()
    return {n: t for n, t in filas}


def orden_por_dependencias(destino):
    tablas = [r[0] for r in destino._cx().execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'").fetchall()]
    dependen = {t: set() for t in tablas}
    for hija, madre in destino._cx().execute(
            "SELECT c.conrelid::regclass::text, c.confrelid::regclass::text FROM pg_constraint c WHERE c.contype='f' "
            "AND c.connamespace=current_schema()::regnamespace").fetchall():
        if hija != madre:
            dependen[hija].add(madre)
    orden, pendientes = [], set(tablas)
    while pendientes:
        listas = sorted(t for t in pendientes if dependen[t] <= set(orden))
        if not listas:
            raise RuntimeError("Hay referencias circulares entre tablas: " + ", ".join(sorted(pendientes)))
        orden += listas
        pendientes -= set(listas)
    return orden


def _convertir(valor, tipo):
    if valor is None:
        return None
    if tipo in ("integer", "bigint", "smallint"):
        if isinstance(valor, str):
            texto = valor.strip()
            if not texto:
                return None
            try:
                return int(float(texto))
            except ValueError:
                return None
        return int(valor)
    if tipo == "double precision":
        if isinstance(valor, str):
            texto = valor.strip().replace(",", ".")
            if not texto:
                return None
            try:
                return float(texto)
            except ValueError:
                return None
        return float(valor)
    if tipo == "text" and not isinstance(valor, (str, bytes)):
        return str(valor)
    return valor


def huella(valor):
    return hashlib.sha256(bytes(valor)).hexdigest() if valor is not None else None


def copiar_tabla(origen, destino, tabla, columnas, tipos, informe):
    blobs = [c for c in CON_ARCHIVOS.get(tabla, ()) if c in columnas]
    informe["claves"][tabla] = columnas[0]
    por_pagina = ARCHIVOS_POR_PAGINA if blobs else FILAS_POR_PAGINA
    lista = ", ".join(columnas)
    marcas = ", ".join("?" * len(columnas))
    sql = f"INSERT INTO {tabla} ({lista}) VALUES ({marcas})"
    ultimo, total = -1, 0
    while True:
        filas = origen.execute(f"SELECT rowid AS _rid_, {lista} FROM {tabla} WHERE rowid > ? ORDER BY rowid LIMIT {por_pagina}", (ultimo,)).fetchall()
        if not filas:
            break
        ultimo = filas[-1]["_rid_"]
        lote = []
        for f in filas:
            valores = []
            for c in columnas:
                v = f[c]
                if c in blobs:
                    v = almacen.leer(v)
                    informe["huellas"].setdefault(tabla, {})[(f[columnas[0]], c)] = huella(v)
                    v = almacen.guardar(tabla, v)
                else:
                    v = _convertir(v, tipos[c])
                valores.append(v)
            lote.append(tuple(valores))
        destino.executemany(sql, lote)
        total += len(lote)
    return total


def verificar_archivos(destino, informe):
    fallas = []
    for tabla, esperadas in informe["huellas"].items():
        clave = informe["claves"][tabla]
        for (valor_clave, col), esperado in esperadas.items():
            r = destino.execute(f"SELECT {col} AS v FROM {tabla} WHERE {clave}=?", (valor_clave,)).fetchone()
            if r is None or huella(almacen.leer(r["v"])) != esperado:
                fallas.append(f"{tabla}.{col} ({clave}={valor_clave}): el archivo copiado no coincide")
    return fallas


def crear_heredada(origen, destino, tabla):
    columnas, claves = [], []
    for r in origen.execute(f"PRAGMA table_info({tabla})").fetchall():
        tipo = (r["type"] or "").upper()
        pg_tipo = "INTEGER" if "INT" in tipo else "DOUBLE PRECISION" if any(x in tipo for x in ("REAL", "FLOA", "DOUB")) else "BYTEA" if "BLOB" in tipo else "TEXT"
        columnas.append(f"{r['name']} {pg_tipo}" + (" NOT NULL" if r["notnull"] or r["pk"] else ""))
        if r["pk"]:
            claves.append((r["pk"], r["name"]))
    if claves:
        columnas.append("PRIMARY KEY (" + ", ".join(n for _, n in sorted(claves)) + ")")
    destino.execute(f"CREATE TABLE IF NOT EXISTS {tabla} (" + ", ".join(columnas) + ")")


def migrar(origen, destino, confirmar=lambda resumen: True, solo_contar=False):
    informe = {"huellas": {}, "claves": {}, "filas": {}, "omitidas": [], "diferencias": []}
    db.preparar_esquema(destino)
    en_origen = set(tablas_origen(origen))
    sin_esquema = sorted(en_origen - set(orden_por_dependencias(destino)))
    for t in sin_esquema:
        crear_heredada(origen, destino, t)
    informe["heredadas"] = sin_esquema
    orden = [t for t in orden_por_dependencias(destino) if t in en_origen]
    informe["omitidas"] = sorted(en_origen - set(orden))
    cantidades = {t: origen.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in orden}
    ocupadas = {t: destino.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in orden}
    informe["cantidades_origen"] = cantidades
    if any(ocupadas.values()):
        informe["error"] = "La base PostgreSQL ya tiene datos: " + ", ".join(f"{t}={n}" for t, n in ocupadas.items() if n)
        return informe
    if solo_contar or not confirmar(cantidades):
        informe["cancelado"] = True
        return informe
    for t in orden:
        tipos = columnas_destino(destino, t)
        columnas_origen = [r["name"] for r in origen.execute(f"PRAGMA table_info({t})")]
        columnas = [c for c in columnas_origen if c in tipos]
        informe["filas"][t] = copiar_tabla(origen, destino, t, columnas, tipos, informe) if cantidades[t] else 0
    pg.reiniciar_secuencias(destino, orden)
    for t in orden:
        n = destino.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        if n != cantidades[t]:
            informe["diferencias"].append(f"{t}: origen {cantidades[t]}, destino {n}")
    informe["diferencias"] += verificar_archivos(destino, informe)
    return informe


def main(argumentos):
    url = db.url_postgres()
    if not url:
        print("Falta DATABASE_URL (variable de entorno o data/cloudflare.env) con la dirección de PostgreSQL de destino.")
        return 1
    c = db.credenciales_d1()
    origen = d1.Conexion(c["CLOUDFLARE_ACCOUNT_ID"], c["CLOUDFLARE_D1_ID"], c["CLOUDFLARE_API_TOKEN"])
    destino = pg.Conexion(url)

    def confirmar(cantidades):
        print("Se van a copiar estas tablas de Cloudflare D1 (solo lectura) a PostgreSQL:")
        for t, n in cantidades.items():
            print(f"  {t}: {n} filas")
        if "--si" in argumentos:
            return True
        return input("Escribí SI para continuar: ").strip() == "SI"

    informe = migrar(origen, destino, confirmar, solo_contar="--contar" in argumentos)
    if informe.get("error"):
        print(informe["error"])
        return 1
    if "--contar" in argumentos:
        for t, n in informe["cantidades_origen"].items():
            print(f"  {t}: {n} filas")
    if informe.get("cancelado"):
        print("No se copió nada.")
        return 0
    for t, n in informe["filas"].items():
        print(f"  {t}: {n} filas copiadas")
    if informe["omitidas"]:
        print("Tablas de D1 sin copiar: " + ", ".join(informe["omitidas"]))
    if informe.get("heredadas"):
        print("Tablas heredadas (sin uso en el sistema actual), copiadas tal cual: " + ", ".join(informe["heredadas"]))
    if informe["diferencias"]:
        print("DIFERENCIAS:")
        for d in informe["diferencias"]:
            print("  " + d)
        return 2
    print("Listo: las cantidades coinciden en todas las tablas.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
