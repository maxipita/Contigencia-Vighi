# Sistema web de contingencia — CAP Vighi

Sistema provisorio para cuando southernbits no está disponible. Corre en **una PC del laboratorio** (servidor)
y el resto entra con el navegador por la **red interna**: funciona aunque no haya internet.

## Poner en marcha

1. En la PC servidor (con Python 3 instalado), doble clic en **`Iniciar contingencia.bat`**.
   La ventana muestra las direcciones, por ejemplo `http://192.168.1.50:8000`. **No cerrar esa ventana.**
2. **Primera vez:** desde la PC servidor abrir `http://localhost:8000` y crear el usuario administrador.
3. En **Usuarios**, darle a cada persona una clave temporal (al entrar la cambia por una propia).
   Los usuarios y sectores ya vienen cargados desde el Excel; revisar nombres y sectores.
4. El resto de las PCs entra con la dirección que muestra la ventana.

Si Windows pregunta por el firewall, permitir el acceso en **redes privadas**.

## Uso

Un **protocolo** es un paciente/solicitud con un número. Adentro tiene uno o más **estudios** (PAP, Biopsia,
Citología), cada uno con su muestra, responsable, lote, etapas y trazabilidad propios.

- **+ Nuevo protocolo:** datos del paciente (una sola vez, con la fecha de recolección) y abajo los estudios con
  los botones `+ PAP`, `+ Biopsia`, `+ Citología` (puede haber varias biopsias). Regla: **con un PAP solo pueden ir
  muestras ginecológicas**; las demás se combinan libremente (ej. biopsia + citología de líquido).
- **Ficha del protocolo:** paciente, lista de estudios, `+ Agregar estudio` y "Vuelta al sistema" (por protocolo).
- **Ficha del estudio:** **trazabilidad** (fecha límite de cada etapa en días hábiles desde la recolección, OT/LT,
  demora) con el botón **✔ Completar**; macroscopía / microscopía con **templates** (solo editables mientras el
  estudio está en esa etapa), IHQ, y "Anular estudio" (anula solo ese estudio).
- **Lotes:** los lotes del día (`TIPO-MMDD.N`, ej. `ONCO-0930.2`; en PAP las iniciales del citotécnico, ej.
  `MAD-0930.1`), con sus estudios. Se imprimen y se **cierran** al despacharlos (un administrador los puede reabrir).
- **Tablero:** una fila por estudio: pendientes, informados, sin cargar al sistema; filtros y búsqueda.
- **Deshacer:** la última etapa la puede deshacer quien la registró o un administrador.
- **Feriados** (administrador): se descuentan de los plazos. Verificar la lista cada año.
- **Exportar Excel:** una fila por estudio con los datos del protocolo, para re-cargarlos en southernbits.

## Datos y respaldos

- Base de datos: `data/contingencia.db` (SQLite). **Contiene datos de pacientes.**
- Respaldo automático cada 10 minutos en `data/respaldos/` (se guardan los últimos 48).
- Respaldo extra en otra carpeta (ej. biblioteca de SharePoint sincronizada): completar
  `CONTINGENCIA_RESPALDO` en `Iniciar contingencia.bat`.
- Cuando todo esté re-cargado en el sistema, archivar o borrar la base según la política del laboratorio.

## Configuración (variables de entorno)

| Variable | Para qué | Por defecto |
|---|---|---|
| `CONTINGENCIA_PUERTO` | Puerto web | `8000` |
| `CONTINGENCIA_DB` | Ruta de la base | `data/contingencia.db` |
| `CONTINGENCIA_RESPALDO` | Carpeta extra de respaldos | — |

## Actualizar templates / catálogo / usuarios

`py preparar_semillas.py` regenera `seed/*.json` desde el Excel y los CSV. Las semillas se cargan
solo en una base nueva (vacía).

## Estructura

- `app.py` — pantallas y reglas comunes (protocolo, lotes, usuarios, tablero)
- `estudios/` — **un módulo por tipo de estudio** (`pap.py`, `bp.py`, `ct.py`): etapas, plazos, lotes, cantidades,
  responsable y requisitos. Para sumar un tipo nuevo se agrega un módulo y se registra en `estudios/__init__.py`.
- `trazabilidad.py` — fechas límite, OT/LT y demoras
- `db.py` — **todo el acceso a datos** (SQL estándar; para migrar a MySQL se cambia solo este módulo)
- `templates/`, `static/` — interfaz · `seed/` — datos iniciales
