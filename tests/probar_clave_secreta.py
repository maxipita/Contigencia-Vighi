import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("CONTINGENCIA_SECRET_KEY", None)
os.environ.setdefault("PROBAR_D1", "1")
sys.stdout.reconfigure(encoding="utf-8")
import vighi
from vighi.core import db

fallas = []


def chequear(n, ok, det=""):
    print(("  OK   " if ok else "  FALLA"), n, "" if ok else det)
    if not ok:
        fallas.append(n)


original = db.DATA
for ronda in range(20):
    with tempfile.TemporaryDirectory() as carpeta:
        db.DATA = carpeta
        with ThreadPoolExecutor(8) as pool:
            claves = list(pool.map(lambda _: vighi.clave_secreta(), range(8)))
        if len(set(claves)) != 1 or not claves[0]:
            chequear("el arranque en paralelo ve siempre la misma clave, nunca vacía", False, claves)
            break
        sobrantes = [x for x in os.listdir(carpeta) if x != "secret.key"]
        if sobrantes:
            chequear("no quedan archivos temporales", False, sobrantes)
            break
else:
    chequear("el arranque en paralelo ve siempre la misma clave, nunca vacía", True)
db.DATA = original

print()
print("FALLAS:", fallas if fallas else "ninguna")
