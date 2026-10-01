# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Sistema web provisorio de contingencia del CAP Vighi (anatomía patológica): se usa cuando southernbits (el sistema
real) no está disponible. Corre en una PC del laboratorio y el resto entra por la red interna, sin internet.
El código, los textos de la interfaz y los mensajes están en español (rioplatense); mantener esa convención.
`LEEME.md` es la guía de uso para el personal; no repetirla acá.

## Comandos

No hay linter ni build. Es Flask + waitress + SQLite (Python 3). En algunas PCs el comando es `python` en vez de `py`.

```
py -m pip install -r requirements.txt     # flask, waitress, openpyxl
py app.py                                 # servidor real en :8000 (equivale a "Iniciar contingencia.bat")
```

- **Probar sin tocar datos reales:** `Probar contingencia.bat` (fija `CONTINGENCIA_DB=data\prueba.db` y
  `CONTINGENCIA_PUERTO=8001`). Para desarrollar usar siempre este modo o esas variables; nunca `data\contingencia.db`.
- **Desarrollo con recarga automática:** en VS Code, F5 (`.vscode/launch.json`, base `data/prueba.db`, puerto 8001) o la tarea
  "Contingencia: iniciar (desarrollo)". Equivale a `CONTINGENCIA_DESARROLLO=1` + `py app.py`: usa el servidor de Flask con recargador
  (plantillas y CSS se ven al refrescar; un cambio en `.py` reinicia solo), escucha solo en `127.0.0.1` y no hace respaldos.
  El `.bat` usa waitress (producción) y **no** recarga: es para la PC servidor, no para desarrollar.
- Variables de entorno: `CONTINGENCIA_PUERTO`, `CONTINGENCIA_DB`, `CONTINGENCIA_RESPALDO` (carpeta extra de
  respaldos), `CONTINGENCIA_ESTRICTO=1` (cada etapa solo la marca su sector).
- `py preparar_semillas.py` regenera `seed/*.json` leyendo Excel y CSV con **rutas fijas de OneDrive de una PC
  concreta** (ver constantes al inicio del script): no corre en otra máquina sin ajustarlas.

## Arquitectura

- **Modelo:** un **protocolo** (número, fecha de recolección, datos del paciente, "cargado en sistema") tiene uno o más
  **estudios** (PAP / BP / CT), cada uno con su muestra, cantidad, responsable, lote, etapas, macro/micro/IHQ y anulación
  propios. Regla de combinación (`estudios.validar_combinacion`): con un PAP solo van muestras ginecológicas.
- `app.py` — todas las rutas Flask y las reglas de negocio (protocolos y estudios, lotes, etapas, etiquetas, usuarios,
  feriados, exportación a Excel). Arranca con waitress en `0.0.0.0` y lanza el hilo de respaldos.
- `db.py` — **único lugar con acceso a datos**: esquema (`SCHEMA`), helpers `q` / `uno` / `ex` (usan `flask.g`) y
  respaldos. Se escribe SQL estándar con placeholders `?` para poder migrar a MySQL cambiando solo este módulo; no
  usar `INSERT OR REPLACE` ni otras extensiones de SQLite (`feriados()` en `app.py` ya lo evita con DELETE + INSERT).
- `estudios/` — un módulo por tipo de estudio (`pap.py`, `bp.py`, `ct.py`) con su flujo de etapas, plazos, tipos de lote,
  cantidades, responsable y requisitos; `base.py` tiene sectores, etapas y la clase `Estudio`; `__init__.py` el registro
  (`REGISTRO`). Los formularios se arman desde ahí: un tipo nuevo es un módulo nuevo.
- `trazabilidad.py` — fecha límite de cada etapa en días hábiles desde la recolección (plazos de cada estudio, `FERIADOS_2026`),
  para mostrar OT/LT como southernbits. Horario hábil 8–20.
- `templates/` (Jinja) y `static/` — interfaz. `seed/` — datos iniciales en JSON.
- **Visual** (`static/app.css`, `templates/base.html`): colores y tipografías de la web nueva (`NUEVAWEB/susana-vighi-web`,
  `src/styles.css`; sus valores OKLCH están pasados a hex en `:root`) y armado de pantallas de la maqueta del sistema
  (`SistemaVighi/Sistema-de-Gestion-Laboratorio-Vighi`): barra superior violeta que es el menú principal (íconos, botón "Ingresar", listas desplegables; en pantallas angostas
  se despliega con el botón de menú), cabecera con `.eyebrow`, tarjetas con banda, tablas con encabezado tenue. Para una pantalla nueva alcanza con `.eyebrow` + `h1` +
  `.tarjeta` / `table`; no hay que agregar CSS. El sistema funciona **sin internet**: nada de CDN (Font Awesome, Google Fonts);
  los íconos son SVG en el sprite de `base.html` y las fuentes se sirven desde `static/fonts/`.
- **Etiquetas y protocolos de contingencia** (`/etiquetas`, `/completar`; sección "etiquetas" de `app.py`, `templates/etiquetas.html`,
  `templates/completar.html`, tabla `etiquetas_lotes`, columnas `protocolos.borrador / etiqueta_lote_id` y `estudios.lab_etiquetado_en`).
  Flujo de tres pasos que hay que respetar al tocar cualquiera de ellos:
  1. **Recepción** (etiquetas con QR, `C000001…`): al confirmar, `db.etiquetas_confirmar` reserva el rango y **crea los
     protocolos a completar** (`protocolos.borrador=1`, cada uno con un estudio) dentro del lote abierto de hoy del tipo elegido (o lo crea). El
     estudio sale del tipo de lote (`estudio_de_lote`: PAPS→PAP, CT→CT, el resto→BP; en PAPS el lote es el del citotécnico
     y él queda como responsable). Todo en una transacción que bloquea escrituras: dos PCs no toman el mismo rango.
  2. **Por completar** (`/completar`): lista los borradores; cada uno se completa con el formulario del protocolo
     (`protocolo_editar`, que en borrador muestra y edita sus estudios y deja sumar otros). Con apellido, nombre y la cantidad
     de cada estudio deja de ser borrador. Los borradores **no aparecen** en tablero ni en la exportación
     (`cargar_estudios(borradores=False)`) y no admiten etapas.
  3. **Laboratorio** (PAP-Laboratorio, BP-Laboratorio): etiquetas de los estudios de protocolos ya completos; cada uno lleva
     tantas como su `cantidad` ("1/2" de PAP = 1). No consumen numeración. Al confirmar se marca `lab_etiquetado_en`. Con `/etiquetas?lote=<id>` (botón
     en la página del lote) se abre la pestaña con ese lote elegido.
  Reglas generales: el **servidor manda** (numeración, validaciones, historial; `POST /api/etiquetas/confirmar`); Imprimir
  solo se habilita tras confirmar; la página usa `base.html` como el resto, pero **la vista previa va en un shadow DOM** (`#etiquetas`) con su propio CSS
  (`#css-etiquetas`): así el CSS del sistema no altera las medidas de impresión. No tocar los px de las etiquetas ni sacar la vista
  previa del shadow DOM; la fuente Finlandica está en `static/fonts/` para imprimir sin
  internet. Las listas salen del sistema: citotécnicos y patólogos de `usuarios` (sectores `citotecnico` / `firmante`), tipos
  de lote de `tipos_lote_fijos()` + `LOTES_ETIQUETA_EXTRA`; los códigos de muestra PAP (`MUESTRAS_PAP`) son fijos.

## Datos sensibles

`data/` (base, respaldos automáticos cada 10 min, `secret.key`) contiene **datos de pacientes** y está en
`.gitignore`: no leerla, copiarla, subirla ni pegarla en salidas salvo que se pida expresamente.

## Git

Rama `main` (origen); cada uno trabaja en su rama (`mpita`, `tiagob`) y se integra en `main`. El nombre de la carpeta, `Contigencia-Vighi`, tiene una
errata; no la renombres sin avisar.
