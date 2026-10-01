# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Sistema web provisorio de contingencia del CAP Vighi (anatomía patológica): se usa cuando southernbits (el sistema
real) no está disponible. Corre en una PC del laboratorio y el resto entra por la red interna, sin internet.
El código, los textos de la interfaz y los mensajes están en español (rioplatense); mantener esa convención.
`LEEME.md` es la guía de uso para el personal; no repetirla acá.

## Comandos

No hay tests, linter ni build. Es Flask + waitress + SQLite (Python 3).

```
py -m pip install -r requirements.txt     # flask, waitress, openpyxl
py app.py                                 # servidor real en :8000 (equivale a "Iniciar contingencia.bat")
```

- **Probar sin tocar datos reales:** `Probar contingencia.bat` (fija `CONTINGENCIA_DB=data\prueba.db` y
  `CONTINGENCIA_PUERTO=8001`). Para desarrollar usar siempre este modo o esas variables; nunca `data\contingencia.db`.
- Variables de entorno: `CONTINGENCIA_PUERTO`, `CONTINGENCIA_DB`, `CONTINGENCIA_RESPALDO` (carpeta extra de
  respaldos), `CONTINGENCIA_ESTRICTO=1` (cada etapa solo la marca su sector).
- `py preparar_semillas.py` regenera `seed/*.json` leyendo Excel y CSV con **rutas fijas de OneDrive de una PC
  concreta** (ver constantes al inicio del script): no corre en otra máquina sin ajustarlas.

## Arquitectura

- `app.py` — todas las rutas Flask y las reglas de negocio (ingreso de casos, lotes, etapas, usuarios, feriados,
  exportación a Excel). Arranca con waitress en `0.0.0.0` y lanza el hilo de respaldos.
- `db.py` — **único lugar con acceso a datos**: esquema (`SCHEMA`), helpers `q` / `uno` / `ex` (usan `flask.g`) y
  respaldos. Se escribe SQL estándar con placeholders `?` para poder migrar a MySQL cambiando solo este módulo; no
  usar `INSERT OR REPLACE` ni otras extensiones de SQLite (`feriados()` en `app.py` ya lo evita con DELETE + INSERT).
- `flujos.py` — define las etapas de cada estudio (`BP`, `IHQ`, `PAP`, `CT`), qué sector realiza cada una y qué datos
  hacen falta antes de marcarla (`requisito`).
- `trazabilidad.py` — fecha límite de cada etapa en días hábiles desde la recolección (`PLAZOS`, `FERIADOS_2026`),
  para mostrar OT/LT como southernbits. Horario hábil 8–20.
- `templates/` (Jinja) y `static/` — interfaz. `seed/` — datos iniciales en JSON.
- **Visual** (`static/app.css`, `templates/base.html`): colores y tipografías de la web nueva (`NUEVAWEB/susana-vighi-web`,
  `src/styles.css`; sus valores OKLCH están pasados a hex en `:root`) y armado de pantallas de la maqueta del sistema
  (`SistemaVighi/Sistema-de-Gestion-Laboratorio-Vighi`): barra superior violeta que es el menú principal (íconos, botón "Ingresar", listas desplegables; en pantallas angostas
  se despliega con el botón de menú), cabecera con `.eyebrow`, tarjetas con banda, tablas con encabezado tenue. Para una pantalla nueva alcanza con `.eyebrow` + `h1` +
  `.tarjeta` / `table`; no hay que agregar CSS. El sistema funciona **sin internet**: nada de CDN (Font Awesome, Google Fonts);
  los íconos son SVG en el sprite de `base.html` y las fuentes se sirven desde `static/fonts/`.
- **Etiquetas y protocolos de contingencia** (`/etiquetas`, `/completar`; sección "etiquetas" de `app.py`, `templates/etiquetas.html`,
  `templates/completar.html`, tabla `etiquetas_lotes`, columnas `casos.borrador / etiqueta_lote_id / lab_etiquetado_en`).
  Flujo de tres pasos que hay que respetar al tocar cualquiera de ellos:
  1. **Recepción** (etiquetas con QR, `C000001…`): al confirmar, `db.etiquetas_confirmar` reserva el rango y **crea los
     protocolos a completar** (casos con `borrador=1`) dentro del lote abierto de hoy del tipo elegido (o lo crea). El
     estudio sale del tipo de lote (`estudio_de_lote`: PAPS→PAP, CT→CT, el resto→BP; en PAPS el lote es el del citotécnico
     y él queda como responsable). Todo en una transacción que bloquea escrituras: dos PCs no toman el mismo rango.
  2. **Por completar** (`/completar`): se cargan apellido, nombre y cantidad; con los tres el caso deja de ser borrador.
     Los borradores **no aparecen** en tablero ni en la exportación (`cargar_casos(borradores=False)`) y no admiten etapas.
  3. **Laboratorio** (PAP-Laboratorio, BP-Laboratorio): etiquetas de los protocolos ya completos; cada uno lleva tantas como
     su `cantidad`. No consumen numeración. Al confirmar se marca `lab_etiquetado_en`. Con `/etiquetas?lote=<id>` (botón
     en la página del lote) se abre la pestaña con ese lote elegido.
  Reglas generales: el **servidor manda** (numeración, validaciones, historial; `POST /api/etiquetas/confirmar`); Imprimir
  solo se habilita tras confirmar; la página es **independiente** de `base.html` a propósito (su CSS y su barra cambiarían
  las medidas de impresión: no tocar los px de las etiquetas); la fuente Finlandica está en `static/fonts/` para imprimir sin
  internet. Las listas salen del sistema: citotécnicos y patólogos de `usuarios` (sectores `citotecnico` / `firmante`), tipos
  de lote de `tipos_lote_fijos()` + `LOTES_ETIQUETA_EXTRA`; los códigos de muestra PAP (`MUESTRAS_PAP`) son fijos.

## Datos sensibles

`data/` (base, respaldos automáticos cada 10 min, `secret.key`) contiene **datos de pacientes** y está en
`.gitignore`: no leerla, copiarla, subirla ni pegarla en salidas salvo que se pida expresamente.

## Git

Ramas `main` (origen) y `tiagob` (la de trabajo actual). El nombre de la carpeta, `Contigencia-Vighi`, tiene una
errata; no la renombres sin avisar.
