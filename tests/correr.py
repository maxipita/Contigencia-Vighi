import argparse
import glob
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
SOLO_D1 = {"probar_d1.py", "probar_sync.py"}
SOLO_PG = {"probar_migracion_pg.py", "probar_concurrencia_pg.py"}
SIN_ESTADO = {"probar_layout.py"}


def veredicto(salida, codigo):
    if codigo != 0:
        return False, f"terminó con código {codigo}"
    if "Traceback (most recent call last)" in salida:
        return False, "error no controlado"
    fallas = re.findall(r"^\s+FALLA\b.*$", salida, re.M)
    if fallas:
        return False, f"{len(fallas)} chequeo(s) fallaron: " + fallas[0].strip()[:90]
    m = re.search(r"^FALLAS:\s*(.*)$", salida, re.M)
    if m and m.group(1).strip() not in ("[]", "ninguna", "ninguna."):
        return False, "FALLAS: " + m.group(1).strip()[:90]
    m = re.search(r"con error 5xx: (.*)$", salida, re.M)
    if m and m.group(1).strip() not in ("ninguna", "[]"):
        return False, "rutas con error 5xx: " + m.group(1).strip()[:80]
    return True, ""


def correr(archivo, motor, url_pg, espera):
    entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
    entorno.pop("PROBAR_PG", None)
    entorno.pop("DATABASE_URL", None)
    if motor == "pg":
        entorno["PROBAR_PG"] = url_pg
    inicio = time.time()
    try:
        r = subprocess.run([sys.executable, os.path.join(AQUI, archivo)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=espera, env=entorno, cwd=AQUI)
        ok, motivo = veredicto(r.stdout + "\n" + r.stderr, r.returncode)
    except subprocess.TimeoutExpired:
        ok, motivo = False, f"más de {espera} s"
    return archivo, motor, ok, motivo, time.time() - inicio


def main():
    p = argparse.ArgumentParser(description="Corre la batería de pruebas del sistema.")
    p.add_argument("--motor", choices=("d1", "pg", "ambos"), default="ambos")
    p.add_argument("--pg", default=os.environ.get("PROBAR_PG", ""), help="URL de un PostgreSQL de pruebas (se borra su esquema public)")
    p.add_argument("--solo", default="", help="texto que debe contener el nombre de la prueba")
    p.add_argument("--espera", type=int, default=300)
    a = p.parse_args()
    archivos = sorted(os.path.basename(f) for f in glob.glob(os.path.join(AQUI, "probar_*.py")))
    archivos = [f for f in archivos if a.solo in f]
    motores = ["d1", "pg"] if a.motor == "ambos" else [a.motor]
    if "pg" in motores and not a.pg:
        print("Para probar contra PostgreSQL hace falta --pg <url> o la variable PROBAR_PG.")
        if a.motor == "pg":
            return 2
        motores.remove("pg")
    tareas = []
    for motor in motores:
        for f in archivos:
            if (motor == "pg" and f in SOLO_D1) or (motor == "d1" and f in SOLO_PG):
                continue
            tareas.append((f, motor))
    fallos = 0
    for motor in motores:
        lista = [t for t in tareas if t[1] == motor]
        print(f"\n== {'Cloudflare D1 (simulador)' if motor == 'd1' else 'PostgreSQL'}: {len(lista)} pruebas")
        paralelo = 4 if motor == "d1" else 1
        with ThreadPoolExecutor(paralelo) as pool:
            for archivo, _, ok, motivo, seg in pool.map(lambda t: correr(t[0], t[1], a.pg, a.espera), lista):
                print(f"  {'OK   ' if ok else 'FALLA'} {archivo:<36} {seg:5.1f} s  {motivo}")
                fallos += 0 if ok else 1
    print("\n" + ("Todo en verde." if not fallos else f"{fallos} prueba(s) con fallas."))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
