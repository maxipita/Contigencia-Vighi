import sys

try:
    from vighi.dominio import informes
except ImportError as _err:
    informes = None
    print(f"AVISO: los informes en PDF están desactivados ({_err}). Instalar con: {sys.executable} -m pip install -r requirements.txt")
