import os


SEMAFOROS = {"on_time": "On time", "delayed": "Delayed", "late": "Late"}
SIN_INFORMES = "Los informes en PDF no están disponibles: falta instalar reportlab (python -m pip install -r requirements.txt) y reiniciar el sistema."
PUERTO = int(os.environ.get("CONTINGENCIA_PUERTO", "8000"))
