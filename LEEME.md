# Sistema web de contingencia — CAP Vighi

Sistema provisorio para cuando southernbits no está disponible. Corre en **una PC del laboratorio** (servidor)
y el resto entra con el navegador por la **red interna**. La base de datos está en **Cloudflare D1**: el servidor necesita internet para funcionar
(si se corta, el sistema muestra "Sin conexión con la base de datos" y vuelve solo cuando regresa).

## Poner en marcha

0. **Una sola vez:** configurar el acceso a la base (sección *Base de datos en Cloudflare D1*, al final). Sin eso el sistema no arranca.
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
- **Flujo compartido por tipo de estudio:** el recorrido (macroscopía, procesamiento, microscopía...) es de cada **tipo** dentro del protocolo, no
  de cada estudio. Si un protocolo tiene 4 biopsias, las 4 comparten el mismo recorrido: al completar una etapa se marca en todas a la vez (y
  al deshacerla, también), y la **macroscopía, la microscopía y la IHQ se cargan una sola vez** para todas (son del recorrido, no de cada estudio). La pantalla de uno de esos estudios
  es la del recorrido completo: lista todos los estudios del tipo y tiene una sola trazabilidad.
  Si tiene una biopsia y una citología, cada una tiene su propio recorrido. Si una biopsia pide IHQ, todo el recorrido de biopsias la incluye.
  Cuando el recorrido de un tipo ya empezó no se puede sumar ni reactivar otro estudio de ese tipo (primero hay que deshacer las etapas).
- **Informe en PDF:** el informe es **uno por protocolo** y junta todos sus estudios (cada uno con su material, macroscopía, microscopía y
  diagnóstico; si hay biopsias y citologías, el título es "Informe de anatomía patológica"). En la pantalla del protocolo hay un panel
  **Informe**: se habilita cuando **todos** los estudios están informados (mientras tanto dice qué falta). **Generar informe** abre una pantalla
  que muestra lo que lleva y avisa si falta algo (diagnóstico, firma o matrícula del médico); ahí se puede sumar un comentario y
  **Generar PDF**, que se abre en una pestaña nueva para descargarlo o imprimirlo.
  **Quién firma:** el **responsable asignado al caso** (el médico firmante del estudio). Si al informar lo último que faltaba, quien lo cierra
  marca **"Quiero firmar el informe yo"**, firma esa persona (si se deshace una etapa, se pierde ese cambio). Si no hay un médico responsable,
  firma quien cerró la última etapa.
  Necesita el permiso *Generar informes en PDF* (viene en el perfil de los médicos firmantes). La firma y la matrícula de cada médico
  las carga el administrador en **Usuarios > Firma en los informes**; la imagen queda en la base, no en el repositorio.
  **Cada PDF generado queda guardado** en el sistema tal como salió: en el panel del protocolo aparece **Ver informe** y se puede volver a abrir sin generarlo de nuevo, aunque después se corrijan datos. Si hace falta corregirlo,
  **Generar de nuevo** **reemplaza** el PDF guardado (queda uno solo por protocolo, para no ocupar espacio). Cada generación queda en el
  historial del protocolo (*informe_pdf*: quién lo generó, quién firma y a quién reemplaza).
- **Lotes:** los lotes del día (`TIPO-MMDD.N`, ej. `ONCO-0930.2`; en PAP las iniciales del citotécnico, ej.
  `MAD-0930.1`), con sus estudios. Se imprimen y se **cierran** al despacharlos (un administrador los puede reabrir).
  **El lote es del protocolo, no de cada estudio:** lo marca el **primer flujo** (el primer estudio cargado) y todos los estudios del protocolo van en ese mismo
  lote. Un protocolo de biopsia con una citología agregada queda en el lote de biopsias; no hay lotes compuestos. En el formulario el lote se elige en el primer
  estudio; en la pantalla del lote se agrega o se quita el protocolo completo.
  **Tacos (lotes de biopsias):** cada lote de ENDO, NO ONCO u ONCO admite hasta **120 tacos**. Los tacos de un estudio dependen del **órgano y del tipo de lote** en que está (el mismo órgano ocupa
  distinta cantidad en ENDO, NO ONCO u ONCO) y se multiplican por la cantidad de frascos. La tabla sale de la planilla `TACOS POR LOTE MACRO.xlsx`; donde un órgano tiene varios valores en el mismo lote (por ejemplo
  Mama o Próstata en ONCO, según el procedimiento) se usa el **mayor**. El lote muestra su contador (*87 / 120 tacos*, también en la lista de lotes y en cada estudio). Cuando se **completa** un protocolo
  (o se agrega o edita un estudio) y el lote se pasaría de 120, el protocolo pasa solo al primer lote **del mismo tipo y del mismo día** que tenga lugar (o a uno nuevo) y el sistema avisa; el protocolo siempre va
  entero en un lote. Si un protocolo solo ya supera 120, queda solo en un lote nuevo. Los lotes cerrados no se tocan y, si alguien agrega un protocolo a mano a un lote que se pasa, solo se avisa. Los órganos
  sin dato de tacos para ese tipo de lote cuentan 0 y el lote avisa cuántos estudios quedaron así. **Cargar o corregir la tabla:** `py cargar_tacos.py <planilla>` con la planilla de Excel original o con un CSV
  (`organo;ENDO;NO ONCO;ONCO`, un valor por celda); muestra qué va a guardar, pide escribir `SI`, suma o corrige lo cargado y lo deja en la base y en `seed/tacos_organo.json`. Los órganos del sistema que no están
  en la planilla quedan en `organos_sin_tacos.csv` para completar y volver a cargar. Los nombres de la planilla que no coinciden con un órgano del sistema (por ejemplo "Prostata RTU") se traducen con
  `seed/alias_organos.json`.
- **Tablero:** una fila por estudio: pendientes, informados, sin cargar al sistema; filtros y búsqueda (por tipo de estudio, sector, **etapa** y semáforo).
  Arriba de la tabla está el **semáforo total**: cuántos estudios hay On time, Delayed y Late; se recalcula con los filtros (tipo, sector, etapa, pestaña y búsqueda)
  y sus cuadros sirven para filtrar por semáforo (otro clic en el elegido lo quita). Al elegir uno, los totales siguen mostrando los tres de lo que se está viendo.
- **Semáforo** (estudios pendientes, en el tablero, el protocolo y la ficha del estudio): **On time** si ni la etapa en que está ni ninguna anterior se pasó de su fecha límite;
  **Delayed** si hay atraso de menos de 1 día hábil; **Late** si llegó a 1 día hábil o más. El atraso **se arrastra**: si una etapa anterior se completó tarde, el protocolo
  lo sigue contando aunque la etapa actual todavía esté en término (se toma el peor estado de todo el recorrido, incluido el ingreso). Los informados y anulados no llevan semáforo.
- **Deshacer:** la última etapa la puede deshacer quien la registró o un administrador.
- **Feriados** (administrador): se descuentan de los plazos. Verificar la lista cada año.
- **Exportar Excel:** una fila por estudio con los datos del protocolo, para re-cargarlos en southernbits.

## Datos y respaldos

- Base de datos: **Cloudflare D1** (ver al final). **Contiene datos de pacientes.**
- Respaldo: Cloudflare D1 guarda un historial que permite restaurar la base a un momento anterior (*Time Travel*; la cantidad de días depende del plan,
  verificarlo en el panel de Cloudflare). El sistema no hace copias locales.
- Cuando todo esté re-cargado en southernbits, archivar o borrar la base según la política del laboratorio.

## Configuración

El acceso a la base va en `data\cloudflare.env` (ver al final). Además:

| Variable de entorno | Para qué | Por defecto |
|---|---|---|
| `CONTINGENCIA_PUERTO` | Puerto web | `8000` |

## Desarrollo (VS Code)

Para modificar el sistema no hace falta cerrar y abrir el `.bat` por cada cambio:

1. Abrir la carpeta del proyecto en VS Code (con la extensión de Python instalada).
2. Abrir el panel de depuración (**Ctrl+Shift+D**), dejar elegida **"Contingencia — desarrollo (Cloudflare D1)"** en el desplegable de arriba y apretar **F5**
   (o *Terminal > Ejecutar tarea > Contingencia: iniciar (desarrollo)*); abrir `http://localhost:8001`. Arriba a la izquierda dice con qué base está trabajando.
3. Al guardar un archivo alcanza con actualizar el navegador: las plantillas y el CSS se ven al instante y, si se cambia
   un `.py`, el servidor se reinicia solo. Los errores se muestran en la propia página.

Usa el puerto 8001, así que no choca con el sistema que esté corriendo en la PC servidor (puerto 8000). Solo se puede entrar desde la misma PC.
**Ojo:** trabaja sobre la base que indique `data\cloudflare.env`. Para desarrollar sin tocar los datos reales conviene tener una segunda base de pruebas en Cloudflare
(por ejemplo `contingencia-vighi-pruebas`) y usarla desde el `data\cloudflare.env` de cada desarrollador, dejando la de producción solo en la PC servidor.

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

## Base de datos en Cloudflare D1

La base es única y vive en Cloudflare D1. Cada PC que corre el sistema (la del laboratorio y las de desarrollo) necesita su archivo `data\cloudflare.env`
con el acceso a la base que le corresponda.

**Preparar Cloudflare (una sola vez, lo hace un administrador):**
1. En el panel de Cloudflare: *Storage & Databases > D1 > Create database* (nombre sugerido: `contingencia-vighi`; para pruebas, `contingencia-vighi-pruebas`). Elegir la ubicación más cercana disponible.
2. Anotar el **Account ID** (en la página principal de Workers & Pages) y el **Database ID** (en la página de la base).
3. *My Profile > API Tokens > Create Token > Create Custom Token*: permiso **Account > D1 > Edit**, limitado a esa cuenta. Copiar el token (se muestra una sola vez).
4. Copiar `cloudflare.env.ejemplo` (está en la raíz del proyecto) a `data\cloudflare.env` y completar, sin comillas ni espacios:
   `CLOUDFLARE_ACCOUNT_ID=...`, `CLOUDFLARE_D1_ID=...` y `CLOUDFLARE_API_TOKEN=...`. Opcional: `CLOUDFLARE_D1_NOMBRE=pruebas` (o `producción`) para que ese nombre aparezca arriba a la izquierda en la pantalla.
   Ese archivo es secreto (la carpeta `data` no va al repositorio): no se pega en chats ni se manda por mail. Cada persona usa su propio token (se la invita a la cuenta y crea el suyo).
5. Con `py -m pip install -r requirements.txt` hecho, el sistema crea solo las tablas y los datos iniciales (médicos, catálogo, plantillas, feriados) la primera vez que arranca sobre una base vacía.

**Subir datos de una base local vieja (opcional, una sola vez):** `py migrar_a_d1.py` toma `data\contingencia.db` (o la ruta que se le indique) y la sube a la base de Cloudflare configurada. Muestra cuántas
filas va a subir (incluye datos de pacientes), pide escribir `SI`, sube todo y verifica que las cantidades coincidan. Si la base de Cloudflare ya tiene datos, no sube nada.

Los datos son de pacientes: el uso de un servicio en la nube lo tiene que autorizar quien responda por la protección de datos del centro.
