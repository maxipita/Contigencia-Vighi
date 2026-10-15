# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Sistema web provisorio de contingencia del CAP Vighi (anatomía patológica): se usa cuando southernbits (el sistema
real) no está disponible. Corre en una PC del laboratorio y el resto entra por la red interna; la base está en Cloudflare D1, así que el servidor necesita internet.
El código, los textos de la interfaz y los mensajes están en español (rioplatense); mantener esa convención.
`LEEME.md` es la guía de uso para el personal; no repetirla acá.

## Comandos

No hay linter ni build. Es Flask + waitress + Cloudflare D1 (SQL estilo SQLite, vía HTTP) (Python 3). En algunas PCs el comando es `python` en vez de `py`.

```
py -m pip install -r requirements.txt     # flask, waitress, openpyxl
py app.py                                 # servidor real en :8000 (equivale a "Iniciar contingencia.bat")
```

- **No hay modo local (SQLite):** la base es Cloudflare D1 o PostgreSQL (`DATABASE_URL`, ver más abajo). Los datos de acceso van en `data/cloudflare.env` (plantilla: `cloudflare.env.ejemplo`); sin ellos `app.py` no arranca y lo dice.
  Para desarrollar sin tocar datos reales se usa una segunda base D1 de pruebas apuntada desde el `cloudflare.env` de cada desarrollador.
- **Desarrollo con recarga automática:** en VS Code, F5 con "Contingencia — desarrollo (Cloudflare D1)" elegida en el desplegable del panel de depuración (`.vscode/launch.json`, puerto 8001) o la tarea
  "Contingencia: iniciar (desarrollo)". Equivale a `CONTINGENCIA_DESARROLLO=1` + `py app.py`: usa el servidor de Flask con recargador
  (plantillas y CSS se ven al refrescar; un cambio en `.py` reinicia solo) y escucha solo en `127.0.0.1`.
  El `.bat` usa waitress (producción) y **no** recarga: es para la PC servidor, no para desarrollar.
- Variables de entorno: `CONTINGENCIA_PUERTO`, `CLOUDFLARE_*` (alternativa al archivo) y `CONTINGENCIA_D1_URL` (solo para probar contra un simulador de la API).
- **PostgreSQL (camino a producción en AWS):** si hay `DATABASE_URL` (variable o línea en `data/cloudflare.env`) `db._conectar()` devuelve `pg.Conexion` en vez de `d1.Conexion`; sin ella
  sigue usando D1, así que volver atrás es sacar esa variable. `pg.py` imita la misma interfaz (`execute`/`executemany`/`executescript`/`lote`, `Fila`, `Cursor.lastrowid`) sobre psycopg 3
  con una conexión por hilo en autocommit y traduce el SQL en el camino: `?`→`%s` (respetando comillas), `AUTOINCREMENT`→identidad, `BLOB`→`BYTEA`, `REAL`→`DOUBLE PRECISION`, `VARCHAR(n)`→`TEXT`,
  `LIKE`→`ILIKE` (SQLite no distingue mayúsculas), `GLOB '[0-9]*'` y `CAST(x AS INTEGER)` (solo el uso de `servicios/tacos.py`), `PRAGMA table_info` y `sqlite_master` contra `information_schema`; un `INSERT`
  en una tabla con `id` identidad agrega `RETURNING id` para `lastrowid`; `lote` es una transacción real; las violaciones de integridad salen como `sqlite3.IntegrityError`. **Escribir SQL que
  valga en los dos motores**: todo lo no agregado debe figurar en el `GROUP BY` (PostgreSQL es estricto), no comparar texto con enteros ni usar funciones propias de SQLite.
  El orden de los textos (`ORDER BY nombre`) sigue la colación de la base: PostgreSQL ordena con acentos como una persona ("ARÉVALO" junto a "AREVALO"); D1/SQLite ordena por bytes. Es la única
  diferencia visible entre motores que se verificó con los datos reales.
  Con varias instancias, la caché de referencia (`db._fijas`, 120 s) es por proceso: un cambio de plantillas o listas tarda hasta 2 minutos en verse en la otra instancia.
- **Archivos (`almacen.py`):** imágenes, miniaturas, firmas y PDF de informes pasan por `almacen.guardar/leer/borrar`. Con `S3_BUCKET` (boto3, credenciales por rol de la instancia) o `ALMACEN_DIR`
  (carpeta local, pruebas) el objeto va afuera y en la columna queda la marca `~obj~<clave>`; sin ninguno se guarda dentro de la base como antes. `leer` acepta las dos formas, así que se
  pueden mezclar filas viejas y nuevas. La parte de S3 está escrita pero todavía no se probó contra un bucket real.
- **Migración D1 → PostgreSQL (`py -m vighi.herramientas.migrar_d1_a_pg`):** solo lee D1; crea el esquema en PostgreSQL, copia todas las tablas (incluidas las heredadas que ya no usa el sistema: `envios`,
  `ubicacion_*`), mueve los archivos a `almacen`, reinicia las secuencias y verifica cantidades y huellas SHA-256 de cada archivo. Se niega a correr si el destino ya tiene datos. `--contar`
  solo cuenta, `--si` no pregunta. Variables de despliegue: `CONTINGENCIA_SECRET_KEY` (firma de sesiones, obligatoria con más de una instancia), `CONTINGENCIA_HTTPS=1` (cookie segura y
  encabezados del proxy), `/salud` (chequeo de estado sin login). Hay `Dockerfile` (puerto 8080) para App Runner.
- `py -m vighi.herramientas.preparar_semillas` regenera `seed/*.json` leyendo Excel y CSV con **rutas fijas de OneDrive de una PC
  concreta** (ver constantes al inicio del script): no corre en otra máquina sin ajustarlas.

## Pruebas

La batería vive en `tests/` (un `probar_*.py` por tema; cada uno arma una base de pruebas con `datos_informe.preparar()` y no toca datos reales). Un comando las corre todas:

```
py tests/correr.py                                   # contra el simulador de D1
py tests/correr.py --pg postgresql://usuario:clave@host/base    # además contra PostgreSQL (borra el esquema public de esa base)
py tests/correr.py --solo facturacion                # solo las que contienen ese texto
```

`probar_arquitectura.py` verifica las capas (los módulos de `features` no se importan entre sí, `core` no depende de `servicios` ni `features`, etc.). Una prueba nueva es un archivo
`probar_<tema>.py` que imprime `  OK   ...` / `  FALLA ...` y termina con `FALLAS: ninguna`; `correr.py` lo detecta solo.

## Arquitectura

- **Modelo:** un **protocolo** (número, fecha de recolección, datos del paciente, "cargado en sistema") tiene uno o más
  **estudios** (PAP / BP / CT), cada uno con su muestra, cantidad, responsable, lote, etapas, macro/micro/IHQ y anulación
  propios. Regla de combinación (`validar_combinacion`): con un PAP solo van muestras ginecológicas.
- **Estructura del repositorio** (`app.py` en la raíz es solo la entrada: `crear_app()` y waitress; todo el código está en el paquete `vighi/`):
  - `vighi/__init__.py` — fábrica `crear_app()`: configuración, filtros de plantilla y registro de los blueprints.
  - `vighi/core/` — infraestructura: `db.py` (**único lugar con acceso a datos**: esquema `SCHEMA`, helpers `q` / `uno` / `ex`, que usan `flask.g`), `d1.py` y `pg.py` (los dos motores),
    `almacen.py` (archivos), `permisos.py` (catálogo de permisos y perfiles iniciales), `sesion.py` (usuario actual, `requiere_login` / `requiere_permiso` / `requiere_admin`, CSRF, modo "ver como",
    variables globales de plantilla), `fechas.py` (filtros y `hoy`), `texto.py`, `config.py` y `opcionales.py` (informes PDF si hay reportlab).
  - `vighi/dominio/` — reglas del laboratorio: `estudios/` (un módulo por tipo de estudio: `pap.py`, `bp.py`, `ct.py`, con su flujo de etapas, plazos, tipos de lote, cantidades, responsable y
    requisitos; `base.py` tiene sectores, etapas y la clase `Estudio`; `__init__.py` el registro `REGISTRO`: un tipo nuevo es un módulo nuevo), `trazabilidad.py` (fecha límite de cada etapa en días
    hábiles desde la recolección, `FERIADOS_2026`, horario hábil 8–20), `facturacion.py` e `informes.py`.
  - `vighi/servicios/` — consultas y operaciones compartidas entre pantallas (estudios, tacos, lotes, protocolos, fichas, etiquetas, facturas, imágenes). Usan `db` y pueden usar Flask, pero no
    definen rutas.
  - `vighi/features/` — una funcionalidad por módulo, cada uno un blueprint con sus rutas: `auth`, `tablero`, `protocolos`, `estudios`, `informes`, `imagenes`, `lotes`, `etiquetas`, `plantillas`,
    `usuarios`, `facturacion`, `listados`, `sistema`. **Un módulo de `features` nunca importa a otro**: lo compartido va en `servicios`. Los endpoints llevan el nombre del blueprint
    (`url_for('protocolos.protocolo', pid=...)`); la barra de navegación (`base.html`) compara por la parte final del nombre.
  - `vighi/templates/<funcionalidad>/` (Jinja; `base.html` en la raíz y los parciales compartidos en `compartidos/`) y `vighi/static/`. `vighi/herramientas/` — comandos de una sola vez
    (`py -m vighi.herramientas.cargar_tacos`, `preparar_semillas`, `migrar_d1_a_pg`). `vighi/servidor.py` — arranque (waitress o modo desarrollo).
  - `seed/` — datos iniciales en JSON. `tests/` — la batería (ver *Pruebas*). `docs/` — manual de usuario y planillas de clasificación de templates. `deploy/` — `Dockerfile`
    (`docker build -f deploy/Dockerfile .`).
- **Permisos:** cada usuario tiene un perfil (tabla `perfiles`) más ajustes propios (`usuarios.permisos_mas` / `permisos_menos`); el admin puede todo. Las rutas se protegen con
  `@requiere_permiso(...)` y las plantillas usan `puede('clave')` para ocultar lo que no corresponde. Las etapas además las marca solo el sector que las realiza. Un permiso nuevo = clave en
  `PERMISOS` + decorador + `puede`.
- **Datos:** se escribe SQL que valga en SQLite y en PostgreSQL, con placeholders `?`; no usar `INSERT OR REPLACE` ni otras extensiones de SQLite (`feriados` en `features/usuarios.py` ya lo
  evita con DELETE + INSERT).
- **Macro / micro / IHQ por flujo:** también son del flujo (protocolo + tipo), no de cada estudio. Se guardan en el estudio **cabecera** (el activo de menor `id` del tipo; `DUENO` en `vighi/servicios/fichas.py` lo
  resuelve en SQL y `ficha` lo devuelve como `e["dueno"]`) y todas las rutas leen y escriben ahí, así que `/estudio/<id>` de cualquiera de los estudios del tipo muestra y guarda lo mismo. Un estudio
  anulado conserva sus propios datos. `db.consolidar_diagnosticos` (en el arranque, si `flujos_por_consolidar`, y en `anular` / reactivar) junta en la cabecera lo que haya quedado en otros estudios
  (concatena textos y suma cassettes). El informe tiene una sección por flujo (`eids` con todos sus estudios) y la exportación a Excel repite en cada estudio lo del flujo.
- **Flujo compartido:** las etapas (`etapas`) siguen guardadas por `estudio_id`, pero el flujo es de cada **tipo dentro del protocolo**: los
  estudios activos del mismo tipo (`miembros_flujo`) tienen siempre las mismas etapas. `marcar_listo` las inserta en todos (y exige los requisitos del flujo:
  macro / micro / IHQ, que son uno solo), `deshacer` las borra en todos, `pide_ihq(protocolo, tipo)` decide si el flujo incluye IHQ (basta con que un estudio
  la pida; `ficha` y `cargar_estudios` lo usan) y `estudio_nuevo` / reactivar rechazan sumar un estudio a un tipo con `flujo_avanzado`. Al arrancar,
  Un tipo distinto en el mismo protocolo es otro flujo, con su propio tracking.
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
- **Visual** (`vighi/static/app.css`, `templates/base.html`): colores y tipografías de la web nueva (`NUEVAWEB/susana-vighi-web`,
  `src/styles.css`; sus valores OKLCH están pasados a hex en `:root`) y armado de pantallas de la maqueta del sistema
  (`SistemaVighi/Sistema-de-Gestion-Laboratorio-Vighi`): barra superior violeta que es el menú principal (íconos, botón "Ingresar", listas desplegables; en pantallas angostas
  se despliega con el botón de menú), cabecera con `.eyebrow`, tarjetas con banda, tablas con encabezado tenue. Para una pantalla nueva alcanza con `.eyebrow` + `h1` +
  `.tarjeta` / `table`; no hay que agregar CSS. La interfaz no depende de CDN externos (Font Awesome, Google Fonts):
  los íconos son SVG en el sprite de `base.html` y las fuentes se sirven desde `vighi/static/fonts/`.
- **Etiquetas y protocolos de contingencia** (`/etiquetas`, `/completar`; módulos `features/etiquetas.py` y `servicios/etiquetas.py`, `templates/etiquetas/etiquetas.html`,
  `templates/tablero/completar.html`, tabla `etiquetas_lotes`, columnas `protocolos.borrador / etiqueta_lote_id` y `estudios.lab_etiquetado_en`).
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
  previa del shadow DOM; la fuente Finlandica está en `vighi/static/fonts/` para imprimir sin
  internet. Las listas salen del sistema: citotécnicos y patólogos de `usuarios` (sectores `citotecnico` / `firmante`), tipos
  de lote de `tipos_lote_fijos()` + `LOTES_ETIQUETA_EXTRA`; los códigos de muestra PAP (`MUESTRAS_PAP`) son fijos.
  Los casos de laboratorio (`etiquetas_casos`) salen ordenados por lote y después por N° de protocolo (`orden_numero`) y estudio, así las etiquetas de un mismo protocolo quedan juntas y en orden.
  Las etiquetas de BP-Laboratorio salen **una por frasco** (`cantidad`) y, si el estudio ya tiene técnicas cargadas en la macro (`tecnicas`), **una por cassette** (`rotulos_cassettes`: "A" o "A 1/2", "A 2/2" cuando una técnica tiene
  varios cassettes), con ese Nro después del N° de protocolo en la primera línea; `etiquetas_casos` los manda en `nros` y la confirmación los guarda en `params` (`nros`, uno por etiqueta) para reimprimir igual.
  En laboratorio **nada se elige por etiqueta**: el patólogo (BP) es el responsable del estudio y el tipo de muestra (PAP) sale de su `tipo_muestra`
  (`codigo_muestra_pap`: Endocervical→ENDO, Exocervical→EXO, Cúpula→CUPULA, Líquido→DERRAME; otro, su texto en mayúsculas; y con cantidad "1/2" —un vidrio
  con mitad endo y mitad exo, la única cantidad fraccionaria— siempre ENDO/EXO). Los toma el servidor al confirmar
  y los guarda en `params` (`patos` / `muestras`, uno por etiqueta) para poder reimprimir igual.

## Notas de implementación

El código no lleva comentarios ni docstrings: lo que hay que saber para tocarlo está en este archivo y en `LEEME.md`.

- **Migraciones:** no hay herramienta. `db.inicializar()` corre en cada arranque: ejecuta `SCHEMA` (todo `CREATE ... IF NOT EXISTS`), suma con `ALTER`
  las columnas que falten (lista dentro de la función; una columna nueva va ahí y en `SCHEMA`) y hace los pasos de una sola vez detectando su estado: el permiso
  `informe` se agrega al perfil "Médico firmante" solo si `usuarios` todavía no tiene la columna `titulo`; `informes_emitidos` pasa de "por estudio" a "por protocolo"
  si no tiene `protocolo_id`.
- **Acceso a datos:** Los módulos web no importan el motor de base: para capturar una restricción rota usa `db.IntegrityError`. Cada escritura de `db.ex` hace commit.
  `etiquetas_confirmar` usa un bloqueo (tabla `bloqueos`) y un lote atómico.
- **Informes opcionales:** si falta `reportlab` (o Pillow), el sistema arranca igual con `informes = None` (`vighi/core/opcionales.py`): se ocultan los botones (`informes_ok` en las plantillas) y las rutas
  avisan con `SIN_INFORMES`. Los informes ya guardados se pueden ver sin la librería. `MAX_CONTENT_LENGTH` (8 MB) existe por las imágenes de firma; `procesar_firma`
  acepta solo PNG/JPG reales, las achica y las guarda como PNG sin metadatos. Los datos del pie del PDF están en `informes.CENTRO` y los colores en las constantes del módulo.
- **Modo desarrollo** (`CONTINGENCIA_DESARROLLO=1`): el recargador de Werkzeug ejecuta `app.py` dos veces, por eso el banner se imprime solo en el proceso hijo
  (`WERKZEUG_RUN_MAIN`); `jinja_env.auto_reload` se activa a mano porque el entorno de plantillas ya está creado; escucha solo en `127.0.0.1` porque el depurador
  de Flask permite ejecutar código; usar siempre una base de prueba. `CONTINGENCIA_SIN_RECARGA=1` apaga el recargador para depurar con puntos de interrupción
  (el recargador termina el proceso con `SystemExit 3`, que el depurador de VS Code muestra como excepción: por eso F5 corre sin depurador).
- **Cloudflare D1 (única base):** `db._conectar()` devuelve `d1.Conexion`, que imita lo que usa el código de `sqlite3` (`execute` / `executemany` / `executescript`, filas
  accesibles por nombre o posición, `lastrowid`) hablando con la API HTTP de D1 (`POST .../d1/database/<id>/query`, un `batch` es atómico). Credenciales: variables `CLOUDFLARE_ACCOUNT_ID`,
  `CLOUDFLARE_D1_ID`, `CLOUDFLARE_API_TOKEN` o `data/cloudflare.env` (más `CLOUDFLARE_D1_NOMBRE`, opcional, que se muestra en la pantalla); `CONTINGENCIA_D1_URL` cambia la URL base (para pruebas con un simulador).
  Diferencias que hay que respetar: **no hay transacciones interactivas** (cada `execute` es un viaje a internet y se confirma solo), por eso `etiquetas_confirmar` toma un bloqueo en la tabla
  `bloqueos` y escribe todo en un único `lote` atómico usando subconsultas en vez de `lastrowid`; las escrituras no se reintentan solas (podrían duplicarse) y las lecturas sí; los archivos
  (`BLOB`) viajan como texto `~b64~...` y vuelven como `bytes`; D1 limita 100 parámetros por sentencia (`executemany` agrupa filas en `INSERT` de varias filas y lotes de 40) y no
  permite `PRAGMA journal_mode` ni `foreign_keys`. `db.q` / `db.uno` guardan las lecturas en `g` durante el pedido (se vacía al escribir con `db.ex` o `etiquetas_confirmar`),. `d1.ErrorConexion` (red caída, 5xx, 401/403/429) se muestra como una pantalla 503 ("Sin conexión con la base de datos"); `d1.ErrorSQL` (un 400 de D1) no, para no taparlo.
  La latencia a Cloudflare (~200 ms por consulta medida desde el laboratorio) obliga a juntar lecturas: `db.precargar(consultas)` trae varias lecturas independientes en un solo `batch`
  y las deja en la caché del pedido (`adelantar_lecturas` en `before_request` trae usuario y cantidad de borradores; `consultas_estudios`, `consultas_ficha` y las constantes `SQL_*` de `vighi/servicios/` existen
  para que la consulta precargada y la real sean exactamente el mismo texto: si se cambia una, cambiar la constante). Las tablas de referencia (`db.REFERENCIA`: feriados, listas, plantillas,
  catálogo, perfiles) se guardan en memoria del servidor 2 minutos y se borran al escribir en ellas con `db.ex`. Con eso las pantallas pasaron de 6–19 consultas a 2–5 (de ~1,9 s a ~0,7 s en promedio).
  Pendiente de optimizar: `cargar_estudios` lee las tablas `etapas` y `estudios` completas en cada pantalla, y D1 cobra por filas leídas.
- **Respaldos:** los hace Cloudflare (*Time Travel*); el sistema no copia nada localmente.
- **Pasar a MySQL:** habría que cambiar solo `vighi/core/db.py`: la conexión, los placeholders (`?` → `%s`), los tipos del esquema y el bloqueo de `etiquetas_confirmar` (hoy la tabla `bloqueos`).
- **Lotes:** el código es `TIPO-MMDD.N` y se arma igual en `app.crear_lote` y en `db._lote_abierto`: si se toca uno, tocar el otro. `tipos_lote_fijos()` suma a los de la
  base los que exige cada estudio (así una base anterior a un tipo nuevo, como HPM, no necesita migración). `orden_numero` ordena los números de protocolo como personas
  (C000009 antes que C000010). `etiquetas_confirmar` devuelve `{id, lote}` o `{error: "choque" | "existentes"}`; `borradores` es
  `{estudio, categoria, subcategoria, sitio, tipo_lote, fecha_lote, fecha_rec, responsable_id, protocolos}`.
- **Lote por protocolo:** el lote lo marca el primer estudio activo del protocolo (`primer_estudio`) y todos los activos comparten `estudios.lote_id`. `asignar_lote(protocolo_id, ...)`
  lo aplica a todos y audita una sola línea; `crear_estudio` hereda el del protocolo; solo el primer bloque de los formularios muestra el selector (CSS `.campo-lote`, y
  `sin-lote` en el formulario cuando el estudio no es el primero); `lote_agregar` y `lote_quitar` mueven el protocolo completo y exigen que el tipo de lote sirva al primer
  flujo.
- **Tacos por lote:** `estudios/bp.py` define `tacos_por_lote = 120` (solo lotes de biopsias). La tabla `tacos_organo (organo, tipo_lote, tacos)` (tabla de referencia, `db.REFERENCIA`) dice cuántos tacos **por frasco** ocupa
  un órgano en cada tipo de lote (ENDO / NO ONCO / ONCO): `organo` es el `sitio` exacto del catálogo y `tipo_lote` el del lote en que está el estudio, así que el mismo órgano cambia de valor según el lote. `cargar_estudios`
  la trae como `tacos_muestra` y calcula `tacos` del estudio = frascos (`cantidad`, 1 si no es número) × tacos_muestra (None si no hay dato). `tacos_por` / `tacos_de_lote` / `tacos_de_protocolo` suman en SQL (sin
  dato = 0 y cuentan `sin_dato`). `ubicar_en_lote(protocolo_id, usuario_id)` corre bajo `db.bloqueo('lotes')` en protocolo nuevo, al completar un borrador, al agregar o editar un estudio y al reactivar uno: si el lote
  del protocolo (abierto y de biopsias) con sus otros protocolos se pasaría de la capacidad, lo pasa al primer lote abierto del mismo tipo y de hoy con lugar (o crea uno) con `asignar_lote`, deja `lote_lleno` en el
  historial y `avisar_lote_lleno` lo muestra; un protocolo que solo supera la capacidad no se mueve si ya está solo. `lote_agregar` solo avisa. `py -m vighi.herramientas.cargar_tacos` lee el Excel original (bloques "Organo / Tipo lote /
  Tacos") o un CSV ancho, resuelve los nombres contra los sitios del catálogo (sin tildes ni mayúsculas, más `seed/alias_organos.json` para los que no coinciden), usa el mayor cuando un órgano y lote tienen varios
  valores, **suma o corrige** (no reemplaza todo), actualiza `seed/tacos_organo.json` (las bases nuevas se siembran de ahí) y escribe `organos_sin_tacos.csv` con los órganos sin ningún dato.
- **Ficha del protocolo:** arriba una franja con Paciente / Médico / Recolección / Lote (el resto de los datos del paciente se edita desde su ficha; `protocolo_editar` queda solo para completar borradores y para el "modificar" de la trazabilidad del estudio). Cada dato lleva su botón de lápiz ("cambiar", clase `.lapiz`): es un
  `form.edicion` propio que alterna entre `.ver` y `.editar` (`vighi/static/app.js`) y guarda con `POST /protocolo/<id>/datos` (`protocolo_datos`: actualiza solo los campos de `CAMPOS_RAPIDOS` que llegan, permiso `protocolo_editar`,
  audita los que cambiaron; los borradores se completan por el formulario completo).
- **Completar un borrador (una sola persona, un solo envío):** la tabla `ediciones (protocolo_id, usuario_id, token, desde, vence)` reserva el protocolo mientras se completa (`servicios/protocolos.py`: `tomar_edicion`, `edicion_propia`, `soltar_edicion`, vigencia
  `VIGENCIA_EDICION` = 15 min). `GET /protocolo/<id>/editar` de un borrador toma la reserva y el formulario lleva su `token` (`edicion`); otra persona que lo abre vuelve a `/completar` con el aviso de quién lo tiene, y esa lista muestra "Lo está completando X". El mismo
  usuario con otra ventana recibe un token nuevo y la ventana vieja queda desactualizada. El POST corre dentro de `db.bloqueo("completar-<id>")` y exige el token propio; al guardar se libera la reserva, así que un segundo envío (doble clic, F5) no crea estudios ni repite
  "completar". `POST /protocolo/<id>/editar/soltar` (beacon al salir de la página) la libera. En `vighi/static/app.js` los `form.form-estudios` deshabilitan el botón al enviar. **Quitar un estudio** desde la ficha del protocolo: botón por fila (permiso `estudio_anular`) que pide el
  motivo y usa `estudios.anular` con `volver=protocolo`; los anulados quedan ocultos tras "Ver anulados".
- **Modificar datos del estudio sin salir de la pantalla:** en la tabla de estudios de la ficha del protocolo y en la tarjeta «Estudio» de la pantalla del estudio, cada dato lleva un lápiz (permiso `protocolo_editar`, protocolo no borrador, estudio no anulado) que guarda con su propia ruta de `features/estudios.py`: `estudio_sitio` (órgano, entre los del catálogo para el mismo tipo y subcategoría; si la muestra actual no existe en el órgano nuevo se reemplaza por la más parecida y se avisa; PAP no, su sitio es fijo), `estudio_muestra` (tipo de muestra del catálogo para ese órgano, `catalogo.muestras_posibles`), `estudio_cantidad` (frascos / vidrios: los **tacos** son `cantidad` × tacos del órgano, así que se cambian por acá), `estudio_responsable` (usuarios del sector responsable del tipo) y `estudio_lote` (del **protocolo**: solo desde su primer estudio activo; `validar_lote` / `concretar_lote` / `asignar_lote`, con «nuevo lote» o «sin lote»). Desde la pantalla del estudio el formulario manda `volver=estudio` y la ruta vuelve ahí; si no, a la ficha del protocolo. Sitio, cantidad y lote corren `ubicar_en_lote`. No cambian el tipo de estudio (BP / PAP / CT) ni el flujo. Auditan `cambiar_sitio` / `cambiar_muestra` / `cambiar_cantidad` / `cambiar_responsable` / `lote` con el antes y el después. Las opciones salen de `protocolos.opciones_de_edicion` y las macros de `templates/compartidos/_edicion_estudio.html`; sus consultas (`SQL_RESPONSABLES`, `SQL_LOTES_ABIERTOS`) se precargan con la pantalla para no pasar del tope de consultas a internet que mide `probar_d1.py`. `tests/probar_muestra.py`, `tests/probar_estudio_datos.py`.
- **Ficha del paciente:** no hay tabla de pacientes (los datos viven en cada protocolo). `GET /paciente/<id de un protocolo>` (`paciente`, `templates/protocolos/paciente.html`; el id va en la URL para no exponer el DNI) junta todos los protocolos con
  el mismo DNI (sin DNI: mismo apellido, nombre y fecha de nacimiento); el título y los datos son los del protocolo de origen y, si otro protocolo trae un nombre distinto, se ve debajo de su número. Muestra sus estudios, estados, lotes y el informe vigente (`Ver informe` si tiene el permiso `informe`). Se entra desde el nombre en la ficha del protocolo. La tarjeta Datos edita **todos** los datos del paciente (`POST /paciente/<id>/datos`, `paciente_datos`, permiso `protocolo_editar`): los aplica a todos sus protocolos en un solo lote (`db.lote_ex`) con una línea de auditoría `editar_paciente` por protocolo, y rechaza un DNI que ya tenga otro paciente.
- **Datos del paciente compartidos:** el paciente se identifica por DNI y sus datos (`CAMPOS_PACIENTE`: apellido, nombre, nacimiento, sexo, cobertura, afiliado, exento, e-mail, teléfono) se copian a todos sus protocolos al guardar
  (`sincronizar_paciente`, en protocolo nuevo, completar/editar y edición rápida), así todos muestran lo más reciente. Al crear o completar solo se copian los campos con dato; al editar, solo los que cambiaron. Si se
  corrige el propio DNI de un protocolo no se copia nada (evita pisar a otro paciente). Médico, recolección, lugares y observaciones son del protocolo y no se copian.
- **Imágenes del protocolo:** tabla `imagenes` (por protocolo, `imagen` y `miniatura` como BLOB; el listado `SQL_IMAGENES` nunca trae los BLOB). Parcial `templates/compartidos/_imagenes.html`, incluido en la ficha del protocolo y en la del estudio
  (el área de escritura de macro/micro/diagnóstico), con visor ampliado en `vighi/static/app.js`. `POST /protocolo/<id>/imagenes` (`imagenes_subir`, permisos `protocolo_editar`, `macro` o `micro`) acepta JPG/PNG/WEBP de hasta 15 MB, máximo 30 por
  protocolo y 40 MB por envío; `procesar_imagen` (Pillow) corrige la orientación y las guarda como JPEG de hasta 1,2 MB (D1 limita la fila a 2 MB y los BLOB viajan en base64, 4/3 más) más una miniatura de 360 px. Se sirven por `/imagen/<id>` y
  `/imagen/<id>/mini` (con sesión, `Cache-Control: private`); borrar con `POST /imagen/<id>/borrar`. Subir y borrar quedan en el historial (`imagenes`, `imagen_borrada`). Los informes en PDF todavía no las incluyen.
- **Semáforo:** `trazabilidad.semaforo(limite, ahora, feriados)` da `on_time` (hasta el límite), `delayed` (pasado el límite, antes de 1 día hábil a la misma hora) o `late`.
  `semaforo_acumulado` toma el peor de la etapa en curso y de cada etapa ya completada (incluido el ingreso) contra su propio límite, así el atraso se arrastra aunque las
  etapas siguientes se hagan en término. `cargar_estudios` lo calcula por estudio (`semaforo`, vacío si está informado, anulado o a completar); el estudio lo calcula en su ficha.
  El umbral de 1 día hábil y los nombres (`SEMAFOROS`) están en `vighi/dominio/trazabilidad.py` / `vighi/core/config.py`; la pastilla es el macro `templates/compartidos/_semaforo.html`.
  El tablero muestra **una fila por protocolo** (sin columna de estudio): los estudios se agrupan por `protocolo_id`; las pestañas y sus conteos se evalúan sobre el protocolo (pendiente = algún estudio activo con `proxima`, informado = todos
  los activos informados) y los filtros de tipo / sector / etapa deciden qué estudios aportan a la fila (estados distintos, muestras, responsables). El semáforo de la fila es el peor de sus estudios y "Vence" el más próximo.
  `por_semaforo` (el semáforo total) cuenta filas que pasan todos los filtros **menos** el de semáforo; el filtro por etapa compara con `proxima[0]`.
- **Comentarios:** son del **protocolo** (tabla `comentarios`), no del estudio: la tarjeta es el parcial `templates/compartidos/_comentarios.html`, incluido en la ficha del protocolo y en la de cada estudio, y muestra los mismos. Cualquier usuario con sesión comenta; borra el autor o un admin (no hay permiso propio). `comentario_nuevo` / `comentario_borrar` vuelven a la página de origen (`volver_a_comentarios`) y auditan (`comentario`, `comentario_borrado`). El tablero muestra `n_comentarios` como insignia.
- **Ubicaciones** (rutas en `features/ubicaciones.py`, helpers en `servicios/ubicaciones.py`): tablas `ubicaciones (abreviatura único, nombre, direccion, contactos, emails)` (`emails` quedó de la versión anterior: ya no se lee ni se escribe, solo se usó para migrar), `ubicacion_medicos (ubicacion_id, medico_id)` (el médico es el de `medicos`) y `ubicacion_destinos` (ver *Envío de informes*). La **abreviatura** es lo principal (en southernbits es el código que figura
  bajo el título, p. ej. ACOYTE1200): es lo que se elige en el protocolo, lo que ve el tablero y lo que guardan `protocolos.lugar_recoleccion` y `lugar_entrega`, que siguen siendo **texto** (así el Excel y los datos viejos no cambian). El
  **nombre completo** (`nombre`) es el que sale en el informe (`informes._institucion`; sin nombre completo cae a la abreviatura). El vínculo con el protocolo es por abreviatura y `error_ubicaciones` obliga a elegir una existente al crear /
  editar / editar rápido (un valor sin cambios se acepta). Cambiar la abreviatura (`ubicacion_editar`) actualiza los dos campos de los protocolos en un lote. `preparar_esquema` migra la versión anterior (columna `nombre` → `abreviatura`).
  Pantallas `/ubicaciones` (lista con búsqueda por abreviatura, nombre, dirección, contacto o médico), `/ubicaciones/<id>` (datos, médicos, estudios) y `/ubicaciones/nueva`; ver es libre y el permiso `ubicaciones` (Administración; el perfil
  "Ingreso" lo recibe al crearse la tabla) permite crear, editar, eliminar, asociar médicos e importar. `servicios/ubicaciones_csv.py` lee el CSV (`abreviatura, nombre, direccion, medicos, telefonos` y, opcional, `emails_informes`; `leer_csv` une repetidas, saca los e-mails de esa columna y de los
  contactos, y lo que en `emails_informes` no sea un e-mail (teléfonos, aclaraciones) lo suma a los contactos) y `db.ubicaciones_importar` lo aplica sin borrar (médicos por `clave_nombre`: sin tildes, mayúsculas ni comas; los que no están se agregan a `medicos`). El campo del formulario usa el buscador de `vighi/static/app.js` (como el médico;
  `data-ubicaciones`, `/api/ubicaciones` devuelve `{v: abreviatura, n: nombre}` y se busca por ambos). El tablero filtra con `ubicacion` (recolección o entrega) y el desplegable lista solo las usadas. El envío de informes usa `ubicacion_destinos`.
- **Envío de informes** (rutas en `features/envios.py`, helpers en `servicios/entrega.py`; la malignidad se asigna desde `features/protocolos.py`): `GET/POST /protocolo/<id>/enviar` (`envio`, `envio_enviar`, `templates/envios/envio.html`, permiso `informe`) y `POST /protocolo/<id>/enviar/whatsapp` (`envio_whatsapp`, devuelve el enlace `wa.me`). Solo con el informe guardado **vigente**
  (`informe_para_enviar`). Destinatarios: paciente (`protocolos.email` / `telefono`; con "guardarlo en la ficha" se actualiza con `sincronizar_paciente`), ubicación (`ubicacion_destinos` de entrega y recolección, `lugares_de_envio`) y otro. `servicios/mensajeria.py` envía por SMTP
  (`smtplib`; un mensaje por destinatario, PDF adjunto, hasta `MAX_DESTINOS`; la config sale de variables de entorno o de `data/cloudflare.env`: `SMTP_HOST`, `SMTP_DESDE` obligatorios; `SMTP_USUARIO`, `SMTP_CLAVE`, `SMTP_PORT`, `SMTP_NOMBRE`, `SMTP_SEGURIDAD` = `ssl` / `ninguna` / vacío
  = STARTTLS, `SMTP_RESPONDER_A`) y normaliza los números (`whatsapp_numero` → `549…`). El mensaje (`mensajeria.armar_mensaje`) sale en texto y HTML (franja violeta con el lema, datos del informe —protocolo, fecha de recolección, paciente, médico— y pie del centro, como el e-mail de southernbits); lo único editable en la pantalla de envío es el texto de introducción y el asunto (por defecto "Informe Adjunto : PACIENTE"). El remitente es `SMTP_DESDE` / `SMTP_NOMBRE` (en el sistema anterior es `no-reply@susanavighi.com.ar`; con `SMTP_RESPONDER_A` las respuestas van a otra casilla). `mensajeria.config()` vuelve a leer `data/cloudflare.env` solo cuando cambia su fecha (no hace falta reiniciar para cargar el correo) y cada mensaje lleva `Date` y `Message-ID` propios. La pantalla `/correo` (`correo`, solo administradores, menú Administración › Correo) muestra el estado de la configuración sin la clave, explica cómo completarla y manda un mensaje de prueba (audita `correo_prueba`). **Sin cuenta de correo** (plan de contingencia): `POST /protocolo/<id>/enviar/correo` (`envio_correo`, comparte `destinos_del_formulario` con `envio_enviar`) prepara el mensaje para el correo propio de quien lo usa: `modo=mailto` devuelve un enlace `mailto:` (un destinatario en Para, varios en copia oculta; no puede adjuntar) y `modo=eml` descarga un borrador `.eml` (`mensajeria.armar_borrador`: `X-Unsent: 1`, remitente `SMTP_DESDE` / `SMTP_NOMBRE` si están cargados —para que Outlook proponga la casilla del laboratorio—, HTML y PDF adjunto) que Outlook abre como mensaje nuevo. Se registra como canal `correo`, estado `abierto`. WhatsApp **no adjunta**: el sistema abre la conversación y registra el intento (`estado='abierto'`). Cada intento queda en la tabla `envios` (canal, rol, destino, estado
  `enviado` / `error` / `abierto`, emisión del informe, quién) y una línea de auditoría `informe_envio` por pedido; la pantalla marca los e-mails ya enviados de la emisión vigente. **Destinos por ubicación** (`ubicacion_destinos`: `canal` email / whatsapp, `destino`, `informes` = tilde "Informes" de southernbits, `alcance` = pares `TIPO.MALIGNIDAD` separados por coma, p. ej. `BP.MALIGNO,PAP.NMA`; tipos `BP` / `PAP` / `CT`, malignidades `SOSPECHOSO` / `MALIGNO` / `NMA` = no maligno; `mensajeria.TIPOS_ESTUDIO`, `MALIGNIDADES`): solo los destinos con `informes` se ofrecen al enviar; `alcance` vacío = todos los estudios. `mensajeria.evaluar(alcance, estudios)` da `si` (algún estudio activo del protocolo coincide en tipo y malignidad), `no` o `falta` (hay un estudio del tipo pedido sin `estudios.malignidad` cargada). **`estudios.malignidad`** (`SOSPECHOSO` / `MALIGNO` / `NMA`) se asigna **por flujo** (protocolo + tipo) desde el panel *Malignidad* de la ficha del protocolo, con tres botones de color (amarillo / rojo / verde), solo cuando todos los estudios activos de ese tipo están informados (`malignidad_por_flujo`; `POST /protocolo/<id>/malignidad`, `malignidad_asignar`, permiso `micro` o `informe`, escribe en todos los estudios activos del tipo, se puede cambiar o quitar y audita `malignidad`). Mientras esté vacía, los destinos con límite por malignidad quedan sin tildar con el aviso "Falta cargar la malignidad"; la pantalla de envío muestra la malignidad vigente y un enlace para asignarla. Lo que no corresponde se muestra sin tildar (pero se puede tildar) con el aviso "No corresponde". Se administran en la ficha de la ubicación (tarjeta `#envio`, permiso `ubicaciones`: `ubicacion_destino_agregar` / `ubicacion_destino_editar`, que también borra). `db.inicializar` pasó los `ubicaciones.emails` viejos a esta tabla una sola vez (detecta que la tabla no existía) y `ubicaciones_importar` suma los e-mails del CSV sin pisar los tildes de los existentes. Pendiente: no hay envío automático ni WhatsApp Business API, y no hay WhatsApp del médico. **Pantalla de envío:** una tarjeta por destinatario (paciente, médico, ubicación, otro), cada una con su botón *Enviar informe* que manda **solo a esa tarjeta** (`solo` = `paciente` / `medico` / `ubicacion` / `otro` en `destinos_del_formulario`, que ignora lo escrito en las demás; Enter no envía). Con SMTP configurado el botón envía por `envio_enviar`; sin SMTP abre el mensaje en el correo propio (`data-correo`, `data-solo`) y suma *Con PDF adjunto* (`envio_correo?modo=eml`). El e-mail del paciente (`guardar_paciente`) y el del médico (`medicos.email`, `guardar_medico`, auditoría `editar_medico`; `medico_de(p)` lo busca por nombre o `clave_nombre`) se guardan al enviar si se tilda la casilla (viene tildada cuando falta el dato; permiso `protocolo_editar`) con `guardar_correos_del_formulario`.
- **Listados (técnicas especiales e IHQ):** valores en la tabla `listas` (`nombre` = `tecnicas_especiales` / `ihq_marcadores`, tabla de referencia), que el administrador edita en `/listados` (`listados`, un valor por línea; comas y punto y coma
  se reemplazan por espacios; reemplaza la lista entera con `db.lote_ex`, que también vacía la caché de referencia de 120 s). Las técnicas pedidas al agregar el estudio se guardan en `estudios.tecnicas_especiales` (texto separado
  por `; `, casillas del bloque del estudio solo si la clase tiene `pide_tecnicas`: BP y CT); en la microscopía solo se muestran (`tecnicas_pedidas`, la unión de las de los estudios del flujo; `guardar_micro` ya no escribe `micro.tecnicas_especiales`, que queda como respaldo de datos viejos para el informe y el Excel). Los marcadores de IHQ
  se eligen con botones (`.chips`, `data-chips` en `vighi/static/app.js`) que completan `ihq.marcadores`. `recordar_tecnicas` suma al listado (en `crear_estudio` y en las dos actualizaciones de estudio) las técnicas nuevas escritas desde "Otra técnica…" (`data-otra-tecnica` en `vighi/static/app.js`), sin distinguir mayúsculas.
  `seed/listas.json` ya trae las técnicas especiales iniciales; los marcadores de IHQ arrancan vacíos.
- **Buscador de la barra:** `GET /buscar?q=` (`buscar_protocolo`): si el texto es `[C]` + dígitos (hasta 6, ceros a la izquierda ignorados) arma el número con `numero_protocolo` y redirige a `protocolo`; si no existe, avisa y vuelve al tablero; si
  coincide exacto con un número cargado a mano (por ejemplo "P1165658-BP") también abre ese protocolo; cualquier otro texto cae en el tablero con `ver=todos&q=`.
- **Ver como otro usuario:** el botón está arriba de `templates/usuarios/usuario.html` (Editar usuario, en su propia tarjeta fuera del formulario y con confirmación; no en la lista). `POST /usuarios/<id>/ver-como` (`ver_como`) guarda en la sesión `real_uid` (el administrador, que se revalida activo y admin en cada pedido) y pone `uid` del usuario visto, así `usuario_actual()`, `puede()` y todo el
  menú reflejan sus permisos; `POST /dejar-de-ver-como` deshace. `modo_vista` (before_request) rechaza **todo POST** mientras haya `real_uid` (JSON 403 en `/api/`), salvo `ver_como`, `dejar_de_ver_como` y `logout`, y `requiere_login` no
  fuerza el cambio de clave del usuario visto. La franja (`.banner-vista` en `base.html`) la arma `globales` con `vista_como`. Cada inicio se audita (`ver_como`). Un `real_uid` falsificado no sirve: sin admin activo detrás, no se muestra nada.
- **Administración (panel de Finanzas):** `/administracion` (`administracion`, permiso `facturacion`; es el botón "Facturación" de la barra, con el ícono $) reproduce el `AdminView` de la maqueta: menú (Ingresos; Reclamos / reclamo de pagos, Presupuestos y Autorizaciones, estos tres
  deshabilitados, "próximamente") y "Cobros previstos" con las facturas `emitida` agrupadas por mes de `fecha_estimada_cobro` (lo vencido va a la columna del mes actual; siempre se muestran el mes actual y el siguiente). Semáforo de la fila (como el sistema original): `color` = `atr5` (atraso > 5 días, rojo),
  `atr` (atraso > 0, naranja) u `ok` (en fecha, verde) y `simbolo` = `tent` (`fec_tipo` tentativa, "?") o `conf` (confirmada o cargada, tilde); íconos `i-cobro-tent` / `i-cobro-conf`; importes sin decimales (`peso0`). Una factura `cobrada` sale del listado. `fec_tipo` y la fecha se fijan en `factura_emitir` y se corrigen en `factura_fec` mientras la factura está emitida.
- **Facturación:** permiso `facturacion` y sector `facturacion` ("Facturación", sin etapas: solo agrupa usuarios; perfil inicial "Facturación" con `facturacion` y `exportar`, que `db.inicializar` crea si no hay ningún perfil con ese permiso). Lógica en
  `vighi/dominio/facturacion.py` (sin rutas, como `informes.py`); rutas en `vighi/features/facturacion.py`: `facturacion_lista`, `facturar`, `factura*`, `tarifario`, `nomencladores`. Modelo, como en el sistema original: un **nomenclador** (`nomencladores`: código y descripción) por
  tipo de muestra (`nomenclador_muestras`: tipo BP/CT/PAP, sitio y tipo de muestra, vacíos = cualquiera) y un **importe por tarifa con vigencia** (`tarifarios`, cada uno con su IVA; `tarifario_valores`: tarifa, código, importe y `vigente_desde`;
  el vigente es el último con fecha ≤ la del estudio). `tarifario_coberturas` asigna cada cobertura a una tarifa; las demás usan `TARIFA GENERAL`, que además completa los nomencladores que a otra tarifa le falten. `facturacion.contexto()` lee todo en
  pocas consultas y `resolver(ctx, cobertura, tipo, sitio, tipo_muestra, fecha)` devuelve `{ok, codigo, descripcion, importe, iva, tarifario}` o `{ok: False, motivo}`: `codigo_de` prueba (sitio, muestra), (muestra), (sitio) y (tipo); los tipos de muestra se
  comparan sin acentos ni mayúsculas. `numero()` lee importes en formato argentino ("12.000", "11.051,46"). Pantalla del tarifario: tarifa elegida, Vigentes / Todas, cargar un importe (con vigencia, no pisa el historial), modificar en bloque (%), importar,
  asignar coberturas. `facturas` (estado `borrador` / `emitida` / `cobrada` / `anulada`, cobertura, FF = `fecha_factura`, FEC = `fecha_estimada_cobro` (fecha *estimada* de cobro, opcional al emitir; `fecha_cobro` es el cobro real), totales y `alicuota` guardados) y `factura_items` (una fila por estudio con **copia** de protocolo, paciente,
  afiliado, código e importes, así la factura no cambia si después se edita el protocolo). IVA de la línea: `exento` si el protocolo tiene `exento = Si`, si no el de la tarifa; `IVA = gravado × alicuota` (`ALICUOTA_IVA` = 21 %). Un estudio está
  "facturado" si figura en una factura no anulada (`ids_facturados`); el borrador se crea bajo `db.bloqueo("facturas")` y escribe los ítems con un `db.lote_ex` (INSERT multifila, 7 filas por sentencia por el límite de 100 parámetros de D1). Solo el
  borrador es editable; anular libera los estudios. La maqueta `VIGHI-Sistema` (`features/facturar` / `features/facturas`, y el HTML original en el historial: `Sistema/facturar.html`, `facturas.html`) aporta las dos pantallas. Facturar trae todos sus filtros: desde / hasta (mes en curso al abrir), cobertura,
  plan (deshabilitado: los protocolos no guardan el plan), procedencia (`lugar_recoleccion`), IVA, flujo (BP / CT / PAP / IHQ), estudios (zona), tipo (biopsias / citologías / inmunohistoquímicas), informados, prioridad de técnicos (IHQ y técnicas
  especiales; congelaciones y nuevos cortes no existen en este sistema) y el de facturados; el filtro de diagnóstico (MA / NE / NG / NMA / SP) no se incluyó porque el diagnóstico no se guarda codificado. Pendientes: refacturación y débitos, presupuestos y autorizaciones, y sumar a la factura IHQ y técnicas especiales como ítems propios (150169 / 150162 / 150167 en el nomenclador de ejemplo).
- **Avanzar lote:** `POST /lotes/<id>/avanzar` (`lote_avanzar`, permiso `etapas`, más el sector de la etapa) completa la etapa pendiente de todos los flujos del lote. `plan_avance_de` arma el plan desde `cargar_estudios` (activos, sin
  borradores, todos con la misma `proxima`; la pantalla del lote usa lo mismo para ofrecer o explicar por qué no) y `motivo_no_listo` (compartido con `marcar_listo`) valida los requisitos de cada flujo con macro / micro / IHQ / técnicas
  traídas en bloque por lote. Escribe todo en un único `db.lote_ex` (INSERT multifila en `etapas` y `auditoria`, "listo … (lote X)"), así que es todo o nada; el formulario manda `etapa` para detectar que el lote cambió de etapa.
- **Templates por órgano y tipo:** `templates.tipo_biopsia` es la **zona** (subcategoría del catálogo); se suman `organo` (sitio) y `tipo_muestra`. `/templates` (`templates_admin`, solo admin) lista con filtros y asigna en bloque
  (`POST` con `ids`, `zona` / `organo` / `tipo`; `""` = no cambiar, `__vaciar__` = borrar; un órgano con una única zona en el catálogo completa la zona). `SQL_TEMPLATES` los trae como `zona` / `organo` / `tipo`. En la ficha del estudio,
  el macro `select_template` arma `.filtro-templates` (zona / órgano / tipo, tomados del estudio y de `/api/catalogo/BP`) y el JS de `select[data-templates]` reconstruye el selector: cada eje con valor excluye a los templates de otro
  valor, los vacíos son generales y los que coinciden salen primero ("Para esta selección" / "Generales (sin clasificar)"); la comparación ignora acentos y mayúsculas porque el catálogo tiene variantes ("Reseccion" / "Resección").
- **Templates acumulables:** el JS de `select[data-templates]` (`vighi/static/app.js`) suma el texto del template al `textarea` (y la conclusión) en lugar de reemplazarlo; guarda los títulos usados, separados por `; `, en un `input hidden`
  que toma el `name="template"` del select (así `macro.template` / `micro.template` guardan todos) y vuelve el select al placeholder para poder elegir el mismo u otro de nuevo. Al cargar la página, el valor guardado se muestra como lista de usados.
- **Decalcificación (Macro > Decal):** columna `macro.decal` (es del flujo, vive en la macro de la cabecera y `consolidar_diagnosticos` la junta con `max`). La etapa `decal` (`ETAPAS`, sector laboratorio, acción "Macro > Decal") entra en `Estudio.flujo`
  entre `macroscopia` y `procesamiento` cuando el flujo la pide. El segundo parámetro de `flujo` / `estado` / `ultima_etapa` (`solicita`, antes un bool de IHQ) es ahora un `estudios.Variante`, un `int` (0/1 = IHQ, así las comparaciones de verdad
  siguen valiendo) con el atributo `.decal` (`con_decal(v)`); `variante_de(protocolo, tipo)` / `SQL_VARIANTE` lo arman en `ficha`, y `cargar_estudios` y `informes.armar` con `SQL_CON_IHQ` / `SQL_CON_DECAL`. Los plazos pasan por
  `Estudio.plazo(etapa, decal)`: `decal` vence `DIAS_DECAL` (1) día hábil después de la macro y las etapas siguientes se corren ese día (`trazabilidad.limite` / `semaforo_acumulado` / `calcular` reciben `decal`). `guardar_macro` solo cambia
  el valor si llega `decal_presente` y el flujo no pasó por `procesamiento` ni `decal` (así la casilla deshabilitada no lo borra); audita "agrega / quita Macro > Decal".
- **Técnicas:** tabla `tecnicas` (por estudio: `numero`, `fragmentos`, `inclusion` = `INCLUSIONES` ("Reserva" / "Inclusión total"), `tacos` = los del estudio al cargarla, `cassettes`, `comentarios`, quién y cuándo). Tarjeta
  `#tecnicas` de `templates/estudios/estudio.html` (solo tipos con sección `macro`, hoy BP) sobre la macro, que lista las de todos los estudios activos del flujo (`SQL_TECNICAS`) y permite agregar (`tecnica_nueva`) o borrar (`tecnica_borrar`) con
  las mismas reglas y permisos que la macro (`macro_editable`; permiso `macro` o `micro`). `marcar_listo` no deja completar la macroscopía si algún estudio del flujo no tiene técnicas (`estudios_sin_tecnicas`).
  `macro.cassettes` ya no se carga a mano: `sumar_cassettes` lo recalcula como suma de las técnicas del flujo. Las auditorías son `tecnica` y `tecnica_borrada`.
- **Carga de macro y micro:** solo se puede editar mientras el estudio está en esa etapa (`habilitada`); `con_permiso` suma el permiso del usuario. La macro además se puede corregir cuando el estudio llega a la etapa de microscopía (`macro_editable`), con permiso `macro` o `micro`.
- **Excel de exportación:** una fila por estudio con los datos de su protocolo y sus etapas, para volver a cargarlos en southernbits.
- **Permiso `usuarios`:** abre Usuarios (listado, alta, edición, clave temporal, firma) a quien no es administrador; Perfiles y permisos y "Ver como" siguen siendo solo del administrador (`requiere_admin`). Quien lo tiene no puede editar administradores, ni marcar "Administrador", ni dar permisos o perfiles que él no tenga (`otorgables` en `features/usuarios.py`; el permiso `usuarios` solo lo da un administrador); los permisos que no puede tocar se conservan al guardar (los selects salen deshabilitados). `tests/probar_usuarios.py`.
- **Permisos:** el orden de `PERMISOS` es el orden en la pantalla de perfiles. Los usuarios que ya existían arrancan con el perfil de su sector.
- **Trazabilidad:** el horario hábil es de 12 horas por día hábil (8 a 20). `FERIADOS_2026` es la carga inicial y hay que verificarla con el calendario oficial;
  después se edita desde la pantalla Feriados. La etapa anterior a la primera es la recolección.
- **Etiquetas:** `GRUPO_NUMERACION` es ("bp", "pap"): comparten numeración porque los lotes de PAP de la versión anterior también numeraban. `LOTES_ETIQUETA_EXTRA`
  (PAPS) son los tipos del desplegable de southernbits que no son un tipo de lote de este sistema. `MUESTRAS_PAP` son los códigos de la etiqueta PAP: no coinciden con
  los tipos de muestra del catálogo, que son más descriptivos. Los lotes ya etiquetados siguen apareciendo `DIAS_ETIQUETADOS` días por si hay que reimprimir.
  El QR institucional (con el logo Vighi al centro, recortado sin borde blanco) va en la etiqueta de Recepción a 70x70 px. Las medidas de cada etiqueta imitan las del
  sistema original (Recepción 457,2x84 px; PAP 126,7x60; BP-Laboratorio una página por etiqueta): no tocarlas.
- **Formularios (`vighi/static/app.js`):** la cascada Subcategoría → Sitio → Tipo de muestra se arma con el catálogo de cada tipo (se pide una vez); sin opciones el campo queda
  deshabilitado. En PAP la subcategoría y el sitio son fijos y, al elegir el citotécnico, se propone su lote del día. Los bloques de estudio nuevos se clonan de las
  plantillas ocultas de `templates/estudios/_bloque.html` (campos `e-N-campo`). El buscador de médico solicitante carga la lista una vez, ignora acentos y mayúsculas, busca todas las
  palabras escritas y muestra primero los apellidos que empiezan igual.
- **Visual:** los colores de la web nueva salen de `NUEVAWEB/susana-vighi-web` (`src/styles.css`, valores OKLCH pasados a hex en `:root`). El menú superior tiene tres anchos:
  completo, compacto (conserva los textos de los botones principales) y solo íconos (el activo conserva su texto, la búsqueda se abre al hacer clic); en pantallas angostas
  se despliega debajo de la barra.

## Datos sensibles

`data/` (`secret.key`, `cloudflare.env` con el token de la base y, si quedó, una base local vieja con **datos de pacientes**) está en
`.gitignore`: no leerla, copiarla, subirla ni pegarla en salidas salvo que se pida expresamente.

## Git

Rama `main` (origen); cada uno trabaja en su rama (`mpita`, `tiagob`) y se integra en `main`. El nombre de la carpeta, `Contigencia-Vighi`, tiene una
errata; no la renombres sin avisar.
