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
  respaldos), `CONTINGENCIA_D1` (base en Cloudflare D1, ver Notas de implementación).
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
- `permisos.py` — catálogo de permisos (`PERMISOS`) y perfiles iniciales. Cada usuario tiene un perfil (tabla
  `perfiles`) más ajustes propios (`usuarios.permisos_mas` / `permisos_menos`); el admin puede todo. En `app.py` las
  rutas se protegen con `@requiere_permiso(...)` y las plantillas usan `puede('clave')` para ocultar lo que no corresponde.
  Las etapas además las marca solo el sector que las realiza. Un permiso nuevo = clave en `PERMISOS` + decorador + `puede`.
- `trazabilidad.py` — fecha límite de cada etapa en días hábiles desde la recolección (plazos de cada estudio, `FERIADOS_2026`),
  para mostrar OT/LT como southernbits. Horario hábil 8–20.
- `templates/` (Jinja) y `static/` — interfaz. `seed/` — datos iniciales en JSON.
- **Flujo compartido:** las etapas (`etapas`) siguen guardadas por `estudio_id`, pero el flujo es de cada **tipo dentro del protocolo**: los
  estudios activos del mismo tipo (`miembros_flujo`) tienen siempre las mismas etapas. `marcar_listo` las inserta en todos (y exige los requisitos de
  cada uno: macro / micro / IHQ), `deshacer` las borra en todos, `pide_ihq(protocolo, tipo)` decide si el flujo incluye IHQ (basta con que un estudio
  la pida; `ficha` y `cargar_estudios` lo usan) y `estudio_nuevo` / reactivar rechazan sumar un estudio a un tipo con `flujo_avanzado`. Al arrancar,
  `db.unificar_etapas` deja parejas las bases viejas (queda lo común). Un tipo distinto en el mismo protocolo es otro flujo, con su propio tracking.
  `protocolo_cerrado(pid)` = todos los estudios activos informados.
- `informes.py` — **informe en PDF de un PROTOCOLO** (junta todos sus estudios; título histopatológico si son todos BP, citológico si no hay BP,
  "de anatomía patológica" si hay de los dos), con el diseño de la maqueta `vighi-sistema`: `armar(pid)` junta lo cargado (paciente, médico
  solicitante y, por estudio, material, macro, micro, diagnóstico, IHQ) y `generar_pdf(datos)` lo dibuja con reportlab. Solo se genera con el protocolo
  completo y **todos** sus estudios informados, y con el permiso `informe`. **Firmante** (`informes._firmante`): 1) `protocolos.firmante_id` si quien cerró
  lo último marcó "Quiero firmar el informe yo" (`firmar_yo` en `marcar_listo`; `deshacer` lo borra), 2) el responsable asignado (primer estudio cuyo
  responsable tiene el sector `firmante`), 3) quien cerró la última etapa. Rutas: `/protocolo/<id>/informe` (revisión; `/estudio/<id>/informe` redirige acá)
  y `POST /protocolo/<id>/informe.pdf`, que **guarda el PDF** en `informes_emitidos` (BLOB, **una sola fila por protocolo**: generar de nuevo la
  reemplaza para no acumular archivos; guarda quién lo generó y quién firma), lo audita (`informe_pdf`, una línea por generación: ahí queda la
  constancia histórica) y redirige a `GET /informe/<id>.pdf`, que sirve lo guardado sin rearmarlo. La firma (imagen PNG)
  vive en la tabla `firmas` y título / MN / MP en `usuarios` (se cargan en Usuarios; nunca en el repositorio ni en `static/`). Usa la
  fuente Segoe UI o Arial de Windows para los símbolos; sin ellas cae a Helvetica. Los datos del centro (pie) están en `informes.CENTRO`.
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
  En laboratorio **nada se elige por etiqueta**: el patólogo (BP) es el responsable del estudio y el tipo de muestra (PAP) sale de su `tipo_muestra`
  (`codigo_muestra_pap`: Endocervical→ENDO, Exocervical→EXO, Cúpula→CUPULA, Líquido→DERRAME; otro, su texto en mayúsculas; y con cantidad "1/2" —un vidrio
  con mitad endo y mitad exo, la única cantidad fraccionaria— siempre ENDO/EXO). Los toma el servidor al confirmar
  y los guarda en `params` (`patos` / `muestras`, uno por etiqueta) para poder reimprimir igual.

## Notas de implementación

El código no lleva comentarios ni docstrings: lo que hay que saber para tocarlo está en este archivo y en `LEEME.md`.

- **Migraciones:** no hay herramienta. `db.inicializar()` corre en cada arranque: ejecuta `SCHEMA` (todo `CREATE ... IF NOT EXISTS`), suma con `ALTER`
  las columnas que falten (lista dentro de la función; una columna nueva va ahí y en `SCHEMA`) y hace los pasos de una sola vez detectando su estado: el permiso
  `informe` se agrega al perfil "Médico firmante" solo si `usuarios` todavía no tiene la columna `titulo`; `informes_emitidos` pasa de "por estudio" a "por protocolo"
  si no tiene `protocolo_id`; `unificar_etapas` deja parejas las etapas de estudios del mismo tipo; la versión anterior con tabla `casos` se respalda y se descarta.
- **Acceso a datos:** `app.py` no importa el motor de base: para capturar una restricción rota usa `db.IntegrityError`. Cada escritura de `db.ex` hace commit.
  Las conexiones permiten leer mientras otro escribe (WAL); `etiquetas_confirmar` usa una transacción que bloquea escrituras.
- **Informes opcionales:** si falta `reportlab` (o Pillow), `app.py` arranca igual con `informes = None`: se ocultan los botones (`informes_ok` en las plantillas) y las rutas
  avisan con `SIN_INFORMES`. Los informes ya guardados se pueden ver sin la librería. `MAX_CONTENT_LENGTH` (8 MB) existe por las imágenes de firma; `procesar_firma`
  acepta solo PNG/JPG reales, las achica y las guarda como PNG sin metadatos. Los datos del pie del PDF están en `informes.CENTRO` y los colores en las constantes del módulo.
- **Modo desarrollo** (`CONTINGENCIA_DESARROLLO=1`): el recargador de Werkzeug ejecuta `app.py` dos veces, por eso el banner se imprime solo en el proceso hijo
  (`WERKZEUG_RUN_MAIN`); `jinja_env.auto_reload` se activa a mano porque el entorno de plantillas ya está creado; escucha solo en `127.0.0.1` porque el depurador
  de Flask permite ejecutar código; usar siempre una base de prueba. `CONTINGENCIA_SIN_RECARGA=1` apaga el recargador para depurar con puntos de interrupción
  (el recargador termina el proceso con `SystemExit 3`, que el depurador de VS Code muestra como excepción: por eso F5 corre sin depurador).
- **Cloudflare D1 (opcional, `CONTINGENCIA_D1=1`):** `db._conectar()` devuelve `d1.Conexion`, que imita lo que usa el código de `sqlite3` (`execute` / `executemany` / `executescript`, filas
  accesibles por nombre o posición, `lastrowid`) hablando con la API HTTP de D1 (`POST .../d1/database/<id>/query`, un `batch` es atómico). Credenciales: variables `CLOUDFLARE_ACCOUNT_ID`,
  `CLOUDFLARE_D1_ID`, `CLOUDFLARE_API_TOKEN` o `data/cloudflare.env`; `CONTINGENCIA_D1_URL` cambia la URL base (para pruebas con un simulador). `requests` se importa recién al usar D1.
  Diferencias que hay que respetar: **no hay transacciones interactivas** (cada `execute` es un viaje a internet y se confirma solo), por eso `etiquetas_confirmar` toma un bloqueo en la tabla
  `bloqueos` y escribe todo en un único `lote` atómico usando subconsultas en vez de `lastrowid`; las escrituras no se reintentan solas (podrían duplicarse) y las lecturas sí; los archivos
  (`BLOB`) viajan como texto `~b64~...` y vuelven como `bytes`; D1 limita 100 parámetros por sentencia (`executemany` agrupa filas en `INSERT` de varias filas y lotes de 40) y no
  permite `PRAGMA journal_mode` ni `foreign_keys`. En este modo `db.q` / `db.uno` guardan las lecturas en `g` durante el pedido (se vacía al escribir con `db.ex` o `etiquetas_confirmar`), y se saltean
  `unificar_etapas`, `unificar_lotes`, el respaldo previo de la versión con `casos` y los respaldos locales. `d1.ErrorConexion` (red caída, 5xx, 401/403/429) se muestra como una pantalla 503 ("Sin conexión con la base de datos"); `d1.ErrorSQL` (un 400 de D1) no, para no taparlo.
  `migrar_a_d1.py` sube una base local (tablas en orden de claves foráneas, un archivo por sentencia) y verifica las cantidades. La latencia a Cloudflare (~200 ms por consulta medida desde el laboratorio) obliga a juntar lecturas: `db.precargar(consultas)` trae varias lecturas independientes en un solo `batch`
  y las deja en la caché del pedido (`adelantar_lecturas` en `before_request` trae usuario y cantidad de borradores; `consultas_estudios`, `consultas_ficha` y las constantes `SQL_*` de `app.py` existen
  para que la consulta precargada y la real sean exactamente el mismo texto: si se cambia una, cambiar la constante). Las tablas de referencia (`db.REFERENCIA`: feriados, listas, plantillas,
  catálogo, perfiles) se guardan en memoria del servidor 2 minutos y se borran al escribir en ellas con `db.ex`. Con eso las pantallas pasaron de 6–19 consultas a 2–5 (de ~1,9 s a ~0,7 s en promedio).
  Pendiente de optimizar: `cargar_estudios` lee las tablas `etapas` y `estudios` completas en cada pantalla, y D1 cobra por filas leídas.
- **Respaldos:** un hilo copia la base cada 10 minutos a `data/respaldos` y, si está definida, a `CONTINGENCIA_RESPALDO` (por ejemplo una carpeta de SharePoint
  sincronizada). Un respaldo que falla no tira la aplicación.
- **Pasar a MySQL:** habría que cambiar solo `db.py`: la conexión, los placeholders (`?` → `%s`), los tipos del esquema y el bloqueo de `etiquetas_confirmar`
  (`BEGIN IMMEDIATE` de SQLite → una transacción con `SELECT ... FOR UPDATE`).
- **Lotes:** el código es `TIPO-MMDD.N` y se arma igual en `app.crear_lote` y en `db._lote_abierto`: si se toca uno, tocar el otro. `tipos_lote_fijos()` suma a los de la
  base los que exige cada estudio (así una base anterior a un tipo nuevo, como HPM, no necesita migración). `orden_numero` ordena los números de protocolo como personas
  (C000009 antes que C000010). `etiquetas_confirmar` devuelve `{id, lote}` o `{error: "choque" | "existentes"}`; `borradores` es
  `{estudio, categoria, subcategoria, sitio, tipo_lote, fecha_lote, fecha_rec, responsable_id, protocolos}`.
- **Lote por protocolo:** el lote lo marca el primer estudio activo del protocolo (`primer_estudio`) y todos los activos comparten `estudios.lote_id`. `asignar_lote(protocolo_id, ...)`
  lo aplica a todos y audita una sola línea; `crear_estudio` hereda el del protocolo; solo el primer bloque de los formularios muestra el selector (CSS `.campo-lote`, y
  `sin-lote` en el formulario cuando el estudio no es el primero); `lote_agregar` y `lote_quitar` mueven el protocolo completo y exigen que el tipo de lote sirva al primer
  flujo. `db.unificar_lotes` parejea las bases que tenían lotes distintos en un mismo protocolo (queda el del primer flujo).
- **Semáforo:** `trazabilidad.semaforo(limite, ahora, feriados)` da `on_time` (hasta el límite), `delayed` (pasado el límite, antes de 1 día hábil a la misma hora) o `late`.
  `semaforo_acumulado` toma el peor de la etapa en curso y de cada etapa ya completada (incluido el ingreso) contra su propio límite, así el atraso se arrastra aunque las
  etapas siguientes se hagan en término. `cargar_estudios` lo calcula por estudio (`semaforo`, vacío si está informado, anulado o a completar); el estudio lo calcula en su ficha.
  El umbral de 1 día hábil y los nombres (`SEMAFOROS`) están en `trazabilidad.py` / `app.py`; la pastilla es el macro `templates/_semaforo.html`.
  En el tablero, `por_semaforo` (el semáforo total) se cuenta sobre los estudios que pasan todos los filtros **menos** el de semáforo; el filtro por etapa compara con `proxima[0]`.
- **Carga de macro y micro:** solo se puede editar mientras el estudio está en esa etapa (`habilitada`); `con_permiso` suma el permiso del usuario.
- **Excel de exportación:** una fila por estudio con los datos de su protocolo y sus etapas, para volver a cargarlos en southernbits.
- **Permisos:** el orden de `PERMISOS` es el orden en la pantalla de perfiles. Los usuarios que ya existían arrancan con el perfil de su sector.
- **Trazabilidad:** el horario hábil es de 12 horas por día hábil (8 a 20). `FERIADOS_2026` es la carga inicial y hay que verificarla con el calendario oficial;
  después se edita desde la pantalla Feriados. La etapa anterior a la primera es la recolección.
- **Etiquetas:** `GRUPO_NUMERACION` es ("bp", "pap"): comparten numeración porque los lotes de PAP de la versión anterior también numeraban. `LOTES_ETIQUETA_EXTRA`
  (PAPS) son los tipos del desplegable de southernbits que no son un tipo de lote de este sistema. `MUESTRAS_PAP` son los códigos de la etiqueta PAP: no coinciden con
  los tipos de muestra del catálogo, que son más descriptivos. Los lotes ya etiquetados siguen apareciendo `DIAS_ETIQUETADOS` días por si hay que reimprimir.
  El QR institucional (con el logo Vighi al centro, recortado sin borde blanco) va en la etiqueta de Recepción a 70x70 px. Las medidas de cada etiqueta imitan las del
  sistema original (Recepción 457,2x84 px; PAP 126,7x60; BP-Laboratorio una página por etiqueta): no tocarlas.
- **Formularios (`static/app.js`):** la cascada Subcategoría → Sitio → Tipo de muestra se arma con el catálogo de cada tipo (se pide una vez); sin opciones el campo queda
  deshabilitado. En PAP la subcategoría y el sitio son fijos y, al elegir el citotécnico, se propone su lote del día. Los bloques de estudio nuevos se clonan de las
  plantillas ocultas de `estudios/_bloque.html` (campos `e-N-campo`). El buscador de médico solicitante carga la lista una vez, ignora acentos y mayúsculas, busca todas las
  palabras escritas y muestra primero los apellidos que empiezan igual.
- **Visual:** los colores de la web nueva salen de `NUEVAWEB/susana-vighi-web` (`src/styles.css`, valores OKLCH pasados a hex en `:root`). El menú superior tiene tres anchos:
  completo, compacto (conserva los textos de los botones principales) y solo íconos (el activo conserva su texto, la búsqueda se abre al hacer clic); en pantallas angostas
  se despliega debajo de la barra.

## Datos sensibles

`data/` (base, respaldos automáticos cada 10 min, `secret.key`) contiene **datos de pacientes** y está en
`.gitignore`: no leerla, copiarla, subirla ni pegarla en salidas salvo que se pida expresamente.

## Git

Rama `main` (origen); cada uno trabaja en su rama (`mpita`, `tiagob`) y se integra en `main`. El nombre de la carpeta, `Contigencia-Vighi`, tiene una
errata; no la renombres sin avisar.
