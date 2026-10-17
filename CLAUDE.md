# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Sistema web provisorio de contingencia del CAP Vighi (anatomía patológica): se usa cuando southernbits (el sistema real) no está disponible. Flask + waitress (Python 3).
**Producción corre en AWS desde el 15/10/2026** (ECS Fargate + RDS PostgreSQL + S3); la base de desarrollo es Cloudflare D1 o PostgreSQL. El código, los textos de la interfaz y los mensajes están en español (rioplatense); mantener esa convención.
`LEEME.md` es la guía de uso para el personal; `docs/funcionalidades.md` es el detalle de cómo está armada cada funcionalidad (tablas, rutas, helpers, reglas): consultarlo antes de tocar una feature, no repetirlo acá.

## Reglas que no se pueden saltear

- **Un push a `main` despliega a producción** (ver *Despliegue*). Trabajar en una rama propia (`mpita`, `tiagob`) e integrar en `main`. La carpeta se llama `Contigencia-Vighi` (errata): no renombrar sin avisar.
- **SQL que valga en SQLite (D1) y en PostgreSQL**, con placeholders `?`: nada de `INSERT OR REPLACE` ni funciones propias de SQLite; todo lo no agregado va en el `GROUP BY`; no comparar texto con enteros.
- **Todo acceso a datos está en `vighi/core/db.py`** y en los helpers `q` / `uno` / `ex`. Los módulos web no importan el motor: para capturar una restricción rota usan `db.IntegrityError`.
- **Un módulo de `vighi/features/` nunca importa a otro**: lo compartido va en `vighi/servicios/`. `tests/probar_arquitectura.py` verifica las capas.
- El código no lleva comentarios ni docstrings; lo que hay que saber está en este archivo y en `docs/funcionalidades.md`.
- `data/` (`cloudflare.env` con el token de la base, `secret.key`, y si quedó una base local vieja) tiene **datos de pacientes** y está en `.gitignore`: no leerla, copiarla, subirla ni pegarla salvo que se pida expresamente. Los datos reales no se cargan en bases de desarrollo: se usan los de `tests/datos_informe.py`.

## Comandos

No hay linter ni build. En algunas PCs el comando es `python` en vez de `py`.

```
py -m pip install -r requirements.txt     # dependencias (flask, waitress, psycopg, boto3, reportlab, ...)
py app.py                                 # servidor real en :8000 (equivale a "Iniciar contingencia.bat", con waitress)
```

- **No hay modo SQLite local.** Los datos de acceso van en `data/cloudflare.env` (plantilla: `cloudflare.env.ejemplo`); sin ellos `app.py` no arranca. Para desarrollar sin tocar datos reales, usar una segunda base D1 de pruebas desde el `cloudflare.env` de cada desarrollador, o `DATABASE_URL` a un PostgreSQL propio.
- **Desarrollo con recarga:** en VS Code, F5 con «Contingencia — desarrollo (Cloudflare D1)» (`.vscode/launch.json`, puerto 8001) o la tarea «Contingencia: iniciar (desarrollo)». Equivale a `CONTINGENCIA_DESARROLLO=1` + `py app.py`: servidor de Flask con recargador, solo en `127.0.0.1` (el depurador de Flask ejecuta código). `CONTINGENCIA_SIN_RECARGA=1` lo apaga para usar puntos de interrupción.
- Variables de entorno: `CONTINGENCIA_PUERTO`, `CLOUDFLARE_*` (alternativa al archivo), `CONTINGENCIA_D1_URL` (solo para probar contra un simulador), `DATABASE_URL`, `S3_BUCKET` / `ALMACEN_DIR`, `CONTINGENCIA_SECRET_KEY` (obligatoria con más de una instancia), `CONTINGENCIA_HTTPS=1`, `SMTP_*`.
- Herramientas de una sola vez (`vighi/herramientas/`): `py -m vighi.herramientas.<nombre>` — `cargar_tacos`, `cargar_templates`, `cargar_tarifas`, `cargar_cobros`, `codigos_por_cobertura`, `preparar_anterior`, `migrar_d1_a_pg`. `preparar_semillas` regenera `seed/*.json` con **rutas fijas de OneDrive de una PC concreta**: no corre en otra máquina sin ajustarlas.

## Pruebas

Un `probar_*.py` por tema en `tests/`; cada uno arma su base con `datos_informe.preparar()` y no toca datos reales. Un comando las corre todas:

```
py tests/correr.py                                   # contra el simulador de D1
py tests/correr.py --pg postgresql://usuario:clave@host/base    # además contra PostgreSQL (borra el esquema public de esa base)
py tests/correr.py --solo facturacion                # solo las que contienen ese texto
```

Una prueba nueva es `probar_<tema>.py` que imprime `  OK   ...` / `  FALLA ...` y termina con `FALLAS: ninguna`; `correr.py` la detecta sola. Las pruebas de PDF usan PyMuPDF (`fitz`), que no está en `requirements.txt`. `probar_migracion_pg.py` no usa `--pg`: tiene su propia URL fija (`127.0.0.1:55138`, usuario `postgres` sin clave). `probar_d1.py` mide el tope de consultas a internet por pantalla: una consulta nueva en una pantalla puede romperlo.

## Arquitectura

`app.py` es solo la entrada (`crear_app()` y waitress); todo el código está en el paquete `vighi/`:

- `core/` — infraestructura: `db.py` (esquema `SCHEMA`, acceso a datos, caché por pedido en `flask.g`), `d1.py` y `pg.py` (los dos motores), `almacen.py` (archivos), `permisos.py`, `sesion.py` (usuario actual, decoradores `requiere_*`, CSRF, modo «ver como»), `fechas.py`, `texto.py`, `config.py`, `opcionales.py`. `core` no depende de `servicios` ni de `features`.
- `dominio/` — reglas del laboratorio sin rutas: `estudios/` (un módulo por tipo, `pap.py` / `bp.py` / `ct.py`, registrados en `REGISTRO`: un tipo nuevo es un módulo nuevo; `base.py` tiene sectores, etapas y la clase `Estudio`), `trazabilidad.py` (plazos en días hábiles, feriados, semáforo), `facturacion.py`, `informes.py`, `anterior.py`, `soporte.py`.
- `servicios/` — consultas y operaciones compartidas entre pantallas. Usan `db` y pueden usar Flask, pero no definen rutas.
- `features/` — un blueprint por funcionalidad con sus rutas. Los endpoints llevan el nombre del blueprint (`url_for('protocolos.protocolo', pid=...)`); la barra (`base.html`) compara por la parte final.
- `templates/<funcionalidad>/` (Jinja; `base.html` en la raíz, parciales compartidos en `compartidos/`) y `static/` (`app.css`, `app.js`, fuentes e íconos propios: la interfaz no depende de CDN). Una pantalla nueva alcanza con `.eyebrow` + `h1` + `.tarjeta` / `table`; no hace falta CSS.
- `seed/` datos iniciales en JSON (solo se cargan en una base vacía); `docs/` manual y planillas; `deploy/Dockerfile`; `infra/` Terraform.

**Modelo:** un **protocolo** (número `C000001`, fecha de recolección, paciente) agrupa **flujos** (uno por tipo: BP / CT / PAP, `flujos (protocolo_id, tipo)`) y cada flujo agrupa sus **estudios** (muestras, `estudios.flujo_id`). El seguimiento (`etapas`), la macro, la micro y la IHQ son **del flujo** (clave `flujo_id`) y valen para todos sus estudios; técnicas, tacos, tipo de muestra, responsable y anulación son **por estudio**; el lote es **del protocolo**. Con un PAP solo van muestras ginecológicas. No hay tabla de pacientes: sus datos viven en cada protocolo y se sincronizan por DNI. Detalle en `docs/funcionalidades.md`.

**Permisos:** cada usuario tiene un perfil (tabla `perfiles`) más ajustes propios (`usuarios.permisos_mas` / `permisos_menos`); el admin puede todo. Las rutas se protegen con `@requiere_permiso(...)` y las plantillas usan `puede('clave')`. Las etapas además las marca solo el sector que las realiza. Un permiso nuevo = clave en `PERMISOS` (el orden es el de la pantalla de perfiles) + decorador + `puede`; los usuarios existentes arrancan con el perfil de su sector.

**Una función nueva de administración** se agrega solo a la pantalla `Configuraciones` (`features/sistema.py`) y, si debe quedar marcada, su endpoint a la lista `ep` del botón «Más» de `base.html`.

## Bases de datos y archivos

- `db._conectar()` devuelve `pg.Conexion` si hay `DATABASE_URL` (variable o línea de `data/cloudflare.env`) y `d1.Conexion` si no; sacar la variable es volver a D1. Los dos imitan la interfaz de `sqlite3` que usa el código (`execute` / `executemany` / `executescript` / `lote`, `Fila`, `lastrowid`).
- **D1:** habla con la API HTTP de Cloudflare. **No hay transacciones interactivas**: cada `execute` es un viaje a internet y se confirma solo; lo atómico va en un `lote` (`db.lote_ex`) y las operaciones que compiten (numeración de etiquetas, lotes, facturas) toman `db.bloqueo(...)` (tabla `bloqueos`). Las escrituras no se reintentan solas, las lecturas sí. Máximo 100 parámetros por sentencia (`executemany` agrupa). La latencia (~200 ms por consulta) obliga a juntar lecturas con `db.precargar(consultas)`; la consulta precargada y la real deben tener exactamente el mismo texto (constantes `SQL_*`). `d1.ErrorConexion` se muestra como pantalla 503; `d1.ErrorSQL` no.
- **PostgreSQL (`pg.py`)** traduce SQL en el camino: `?`→`%s`, `AUTOINCREMENT`→identidad, `BLOB`→`BYTEA`, `LIKE`→`ILIKE`, `PRAGMA table_info` / `sqlite_master`→`information_schema`; un `INSERT` en tabla con `id` identidad agrega `RETURNING id`; `lote` es una transacción real; las violaciones de integridad salen como `sqlite3.IntegrityError`. El orden de textos sigue la colación de la base (PostgreSQL ordena con acentos como una persona; D1 por bytes).
- **Caché de referencia** (`db.REFERENCIA`: feriados, listas, plantillas, catálogo, perfiles): 120 s por proceso, se vacía al escribir con `db.ex`. Con varias instancias, un cambio tarda hasta 2 minutos en verse en la otra.
- **Migraciones:** no hay herramienta. `db.inicializar()` corre en cada arranque: ejecuta `SCHEMA` (todo `CREATE ... IF NOT EXISTS`), suma con `ALTER` las columnas que falten (una columna nueva va en la lista de la función **y** en `SCHEMA`) y hace los pasos de una sola vez detectando su estado o con una marca en `pasos_unicos`. `migrar_a_flujos` y la etapa Revisión son ejemplos.
- **Archivos** (imágenes, firmas, PDF, órdenes, adjuntos de facturas) pasan por `almacen.guardar/leer/borrar`: con `S3_BUCKET` o `ALMACEN_DIR` el objeto va afuera y la columna guarda `~obj~<clave>`; sin ninguno, dentro de la base. `leer` acepta las dos formas.
- **D1 → PostgreSQL:** `py -m vighi.herramientas.migrar_d1_a_pg` (`--contar`, `--si`) solo lee D1, se niega a correr si el destino tiene datos y verifica cantidades y SHA-256 de cada archivo. La D1 de producción quedó congelada como respaldo: no se vuelve a cargar nada en ella.
- `/salud` es el chequeo de estado sin login. La app usa `datetime.now()` para auditoría, plazos y semáforo, por eso la imagen Docker fija `TZ` de Argentina.

## Despliegue

- **AWS (`infra/`, Terraform, perfil `terraform-vighi-contingencia`, sa-east-1):** `https://contingencia.sistemacapvighi.com` → ALB → ECS Fargate ARM64 (subred pública sin NAT, solo acepta al ALB) → RDS PostgreSQL 17 en subred privada; archivos en el bucket `sistemacapvighi-archivos`. `infra/bootstrap/` crea una sola vez el bucket del estado (queda local y fuera de git). **Terraform no corre en CI**: los cambios de infraestructura se aplican a mano. RDS, ALB y los buckets tienen protección contra borrado.
- `DATABASE_URL` y `CONTINGENCIA_SECRET_KEY` los genera Terraform en SSM (`/vighi-contingencia/...`). Los parámetros `SMTP_*` también van en SSM, pero Terraform solo los crea con un valor provisorio y nunca toca su valor: se cargan a mano (`aws ssm put-parameter --overwrite`; el repo es público, nunca en el código). La app los lee al arrancar: después de cambiar uno, `aws ecs update-service --force-new-deployment`. Office 365 desactiva el SMTP con usuario y clave a fines de diciembre de 2026: habrá que pasar a OAuth 2.0 o que el admin lo rehabilite.
- Tamaño de la tarea: variables `memoria` (2048 MB) y `tareas` en el código de Terraform (no en un `.tfvars`: un `apply` sin ese archivo volvería `tareas` a 0).
- **Un push a `main` despliega** (`.github/workflows/desplegar.yml`): corre la batería contra D1 y PostgreSQL 17 y, si pasa, arma la imagen ARM64, la sube a ECR con el commit como tag (inmutable) y como `produccion`, y fuerza un deploy de ECS (rolling; si la tarea nueva no queda sana, vuelve a la anterior). Al final compara la imagen en servicio con la subida y falla si ECS volvió atrás. No despliegan los cambios que solo tocan `*.md`, `docs/`, `infra/` ni `.vscode/`. GitHub entra a AWS por OIDC con el rol `vighi-contingencia-github` (solo rama `main`; usa el `sub` inmutable de GitHub, variable `github_sub`). Para volver atrás: *Re-run* del workflow de ese commit o `git revert`.
- **Migraciones y producción:** el despliegue no ensaya contra datos reales. Un cambio aditivo (`ALTER … ADD`, `CREATE … IF NOT EXISTS`) se despliega como cualquier push; uno que renombre o recree tablas rompe a las tareas viejas mientras conviven con la nueva, así que se despliega con una ventana corta (servicio en 0 tareas, push, de nuevo en 1) y un snapshot manual antes, ensayado antes sobre una copia. Las migraciones deben ser atómicas (`lote`); RDS guarda respaldos 7 días (*point-in-time restore* a una instancia nueva y después apuntar `DATABASE_URL`).

## Convenciones que cuesta descubrir

- **Lotes:** el código es `TIPO-MMDD.N` y se arma en `servicios/lotes.crear_lote`, en `db.etiquetas_confirmar` (lote de Recepción) y se anticipa en `servicios/etiquetas.lotes_previstos`: si se toca uno, tocar los otros. Un lote de biopsias admite hasta 120 tacos (`estudios/bp.py`); el protocolo siempre va entero en un lote.
- **Formularios con clase `filtros`** se envían solos 0,5 s después de escribir (`static/app.js`): un alta o cualquier formulario que no sea un filtro **no** debe usar esa clase.
- **Etiquetas:** la vista previa va en un shadow DOM (`#etiquetas`) con su propio CSS, y las medidas en px imitan las del sistema original: no tocarlas ni sacar la vista previa del shadow DOM. El flujo de tres pasos (Recepción → Por completar → Laboratorio) está en `docs/funcionalidades.md`.
- **Informes en PDF:** `reportlab` y Pillow son opcionales (`core/opcionales.py`); sin ellos el sistema arranca y oculta los botones. Fuente Segoe UI / Arial en Windows y Liberation Sans en Linux. La firma y la matrícula viven en la base, nunca en el repositorio ni en `static/`.
- **Trazabilidad:** horario hábil de 8 a 20; `FERIADOS_2026` es solo la carga inicial (se edita en Feriados y hay que verificarla cada año).
- **Tablero y exportación** no pasan por `cargar_estudios` (arman sus datos en `servicios/tablero.py` y `servicios/exportacion.py`, paginados / por tandas) para no cargar tablas completas en memoria; `cargar_estudios` sigue leyendo `etapas` y `estudios` enteras en las pantallas de protocolo, estudio, lote, `/facturar` y Completar.
