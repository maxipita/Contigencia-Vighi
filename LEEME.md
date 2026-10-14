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
- **Imágenes:** en la ficha del protocolo (y en la pantalla de cada estudio, junto a donde se escribe el informe) hay una tarjeta *Imágenes*: se pueden subir varias fotos a la vez (JPG, PNG o WEBP), con una descripción opcional, verlas
  ampliadas con un clic (flechas para pasar de una a otra) y borrarlas. Quedan asociadas al protocolo, hasta 30, y se achican solas para ocupar poco. Suben y borran quienes pueden editar protocolos o cargar macro o micro.
- **Ficha del estudio:** **trazabilidad** (fecha límite de cada etapa en días hábiles desde la recolección, OT/LT,
  demora) con el botón **✔ Completar**; macroscopía / microscopía con **templates** (solo editables mientras el
  estudio está en esa etapa), IHQ, y "Anular estudio" (anula solo ese estudio).
- **Listados (administrador, menú Más → Listados):** se cargan, uno por línea, las **técnicas especiales** y los **marcadores de IHQ**. Las técnicas especiales se tildan al agregar o editar un estudio de
  biopsia o citología (y se ven en la ficha del estudio); ahí mismo, **"Otra técnica…"** suma una que no esté: queda en el estudio y se agrega sola al listado para los siguientes y llegan ya cargadas a la microscopía (ahí solo se ven, no se eligen de nuevo); los marcadores se eligen al cargar la IHQ de la biopsia cuando el diagnóstico la solicita.
- **Avanzar un lote completo:** en la pantalla del lote, el botón **✔ Avanzar lote: completar <etapa>** marca la etapa pendiente en todos sus protocolos de una sola vez. Solo se ofrece si **todas** las muestras están en la misma
  etapa (si no, la pantalla dice cuántas hay en cada una), si no hay protocolos a completar y si cada flujo cumple lo que pide esa etapa (por ejemplo macro y técnicas cargadas en macroscopía, diagnóstico en microscopía). Es todo o nada:
  si algún protocolo no cumple, no se avanza ninguno y se indica cuál falta. Respeta los sectores como el botón de cada estudio, y deja una línea en el historial de cada protocolo.
- **Varios templates en la macro y la micro:** al elegir un template se **suma** al texto que ya está (separado por una línea en blanco; la conclusión, en una línea nueva) en vez de reemplazarlo, así se pueden usar varios cuando el caso
  tiene más de una muestra. Debajo del selector queda la lista de los templates agregados (con "limpiar lista"); el texto se puede seguir editando a mano.
- **Tablero:** una fila por **protocolo** (con la cantidad de estudios). Si sus flujos están en estados distintos, la celda de Estado muestra uno debajo del otro; el semáforo es el peor de ellos y "Vence" la fecha más próxima. Para ver cada
  estudio se entra al protocolo. Los contadores de las pestañas cuentan protocolos.
- **Etiquetas de laboratorio y técnicas:** las etiquetas de BP-Laboratorio salen una por frasco; si el estudio ya tiene técnicas cargadas en la macro, salen **una por cada cassette** y llevan el Nro de la técnica junto al N° de protocolo
  (por ejemplo "C000001 · A", o "A 1/2" y "A 2/2" cuando una técnica tiene dos cassettes).
- **Templates por órgano y tipo (administrador, Más → Templates):** cada template de macro y micro puede tener **zona del cuerpo, órgano y tipo de muestra**. En la pantalla se filtra por esos datos, se marcan varios y se les asigna de una vez.
  Al informar, el selector de templates de la macro y la micro trae tres filtros (zona, órgano, tipo) ya puestos con los datos del estudio: primero salen los templates de esa selección y después los generales (sin clasificar);
  se pueden cambiar o vaciar los filtros para ver todos.
- **Administración / Facturación (sector "Facturación", permiso "Facturación y tarifario"):** el botón **Facturación** de la barra superior abre el panel **Administración** (Finanzas): a la izquierda Ingresos (Nueva factura, Facturas emitidas,
  Tarifario, Nomencladores), Reclamos (carga del reclamo de pagos), Presupuestos y Autorizaciones API (estos tres, próximamente) y, a la derecha, **Cobros previstos**: las facturas emitidas todavía sin cobrar, agrupadas por mes de su fecha estimada de cobro (el mes actual incluye lo atrasado),
  con la fecha, un punto de estado, la cobertura (link a la factura) y el importe, y el total de cada mes. Cada fila lleva un **semáforo**: el color dice si el cobro llega en fecha (verde), está atrasado (naranja) o lleva más
  de 5 días de atraso (rojo), y el símbolo dice si la fecha es tentativa (**?**) o está confirmada / ya cargada (**✓**). **Al registrar el cobro, la factura sale de la lista.** Al emitir (o después, en la factura) se elige la fecha estimada y de
  qué tipo es.
  - **Nomencladores:** cada tipo de muestra se asocia a un nomenclador (código y descripción). Se puede afinar por sitio; si no hay asignación para el sitio se usa la del tipo de muestra y, si no, la general del tipo de estudio (BP, CT, PAP).
  - **Tarifario:** una tarifa (por ejemplo TARIFA GENERAL, OSDE…) tiene un importe por nomenclador con "vigente desde". Se ve **Vigentes** o **Todas** (historial); **Cargar una nueva**, **Modificar** (un importe nuevo con su fecha, sin perder el
    anterior) y **Modificar en bloque** (aumento en %). Cada tarifa tiene su IVA y las coberturas que la usan; las que no tienen una propia usan la TARIFA GENERAL, que también completa lo que le falte a otra tarifa.
  - **Facturar:** la pantalla previa a generar la factura. Se busca por fecha de recolección (arranca con el mes en curso), cobertura, procedencia, IVA, flujo (BP, CT, PAP, IHQ), estudios (zona del cuerpo), tipo (biopsias, citologías, IHQ),
    informados o no, ya facturados o no y prioridad de técnicos (IHQ, técnicas especiales); se marcan y se genera el **borrador** de una factura (una sola cobertura). El importe es el vigente a la fecha del estudio.
    Los estudios sin nomenclador o sin importe se muestran con el motivo y no se pueden marcar. Nunca se factura dos veces el mismo estudio.
  - **Factura:** en borrador se editan código, cantidad, importe unitario e IVA de cada ítem y se pueden quitar ítems; **Emitir** pide el número del comprobante, la fecha de factura (FF) y, si se quiere, la fecha estimada de cobro (FEC); **Marcar como cobrada** registra la fecha en que se cobró;
    **Anular** (borrador o emitida, con motivo) devuelve los estudios a "sin facturar". Se descarga en CSV. El IVA es del 21 % sobre lo gravado; un protocolo marcado como **exento** se factura siempre como exento.
  - **Facturación:** listado con filtros por cobertura, año, mes y estado (borrador, emitida, cobrada, sin cobrar, anulada) y totales de exento, gravado, IVA y total.
- **Ver el sistema como otro usuario (administradores):** en Usuarios → **Editar** de cada usuario activo (arriba de la pantalla, en una tarjeta aparte del formulario y con confirmación para evitar clics por error), el botón **Ver como** abre el sistema tal como lo ve esa persona (menú, permisos, pantallas y botones). Arriba aparece una franja amarilla
  con quién se está mirando, un selector para pasar a otro usuario y **Volver a mi usuario**. Es **solo para mirar**: mientras dura no se puede guardar ningún cambio (para que nada quede registrado a nombre de otra persona) y las
  pantallas de administración quedan vedadas, igual que para ese usuario. Cada vez que se entra en la vista de alguien queda anotado en el historial.
- **Buscador de la barra superior:** escribiendo el número de un protocolo abre **directamente ese protocolo**, sin filtrar el tablero. Alcanza con la parte numérica: `1`, `001`, `c1` o `C000001` van al C000001 (se ignoran los ceros a
  la izquierda y la C). Si el protocolo no existe, avisa. Lo que no es un número (apellido, DNI, lote…) sigue buscando en el tablero.
- **Macro > Decal (biopsias):** en la tarjeta de Macroscopía hay un condicional **"Macro > Decal"**. Si se tilda, el tracking suma la etapa **Decalcificación** (sector Laboratorio) entre la macroscopía y el procesamiento, y las
  fechas límite de las etapas siguientes se corren un día hábil. Se puede tildar o destildar mientras el estudio no haya pasado por la decalcificación ni el procesamiento (si ya pasó, hay que deshacer esas etapas).
- **Técnicas (biopsias):** antes de la macroscopía, la ficha del estudio tiene la tarjeta **Técnicas**: por cada estudio del flujo se registra el número (Nro), los fragmentos, si la inclusión
  fue **Reserva** (parcial) o **Inclusión total**, los tacos (los predeterminados del órgano, solo lectura) y los cassettes, con comentarios opcionales. Hace falta **al menos una técnica por estudio** para
  completar la macroscopía; se pueden agregar y borrar mientras la macro es editable. El N° de cassettes de la macro es la suma de las técnicas.
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
  sin dato de tacos para ese tipo de lote cuentan 0 y el lote avisa cuántos estudios quedaron así. **Cargar o corregir la tabla:** `py -m vighi.herramientas.cargar_tacos <planilla>` con la planilla de Excel original o con un CSV
  (`organo;ENDO;NO ONCO;ONCO`, un valor por celda); muestra qué va a guardar, pide escribir `SI`, suma o corrige lo cargado y lo deja en la base y en `seed/tacos_organo.json`. Los órganos del sistema que no están
  en la planilla quedan en `organos_sin_tacos.csv` para completar y volver a cargar. Los nombres de la planilla que no coinciden con un órgano del sistema (por ejemplo "Prostata RTU") se traducen con
  `seed/alias_organos.json`.
- **Tablero:** una fila por estudio: pendientes, informados, sin cargar al sistema; filtros y búsqueda (por tipo de estudio, sector, **etapa** y semáforo).
  Arriba de la tabla está el **semáforo total**: cuántos estudios hay On time, Delayed y Late; se recalcula con los filtros (tipo, sector, etapa, pestaña y búsqueda)
  y sus cuadros sirven para filtrar por semáforo (otro clic en el elegido lo quita). Al elegir uno, los totales siguen mostrando los tres de lo que se está viendo.
- **Semáforo** (estudios pendientes, en el tablero, el protocolo y la ficha del estudio): **On time** si ni la etapa en que está ni ninguna anterior se pasó de su fecha límite;
  **Delayed** si hay atraso de menos de 1 día hábil; **Late** si llegó a 1 día hábil o más. El atraso **se arrastra**: si una etapa anterior se completó tarde, el protocolo
  lo sigue contando aunque la etapa actual todavía esté en término (se toma el peor estado de todo el recorrido, incluido el ingreso). Los informados y anulados no llevan semáforo.
- **Usuarios:** por defecto solo los administradores. Con el permiso *Usuarios* (se tilda por perfil o por persona, y solo lo da un administrador) alguien más puede crear y editar personas, ponerles clave temporal y cargar firmas; no puede tocar a los administradores, ni hacer administrador a nadie, ni dar permisos que no tiene. *Perfiles y permisos* queda siempre solo para administradores.
- **Cambiar el tipo de muestra de un estudio** (por ejemplo de Biopsia a Resección): en la ficha del protocolo, tabla de Estudios, el lápiz de la columna *Muestra* (permiso de edición de protocolos). El cambio queda en el historial. El tipo de estudio (biopsia, PAP o citología) no cambia.
- **Deshacer:** la última etapa la puede deshacer quien la registró o un administrador.
- **Feriados** (administrador): se descuentan de los plazos. Verificar la lista cada año.
- **Ubicaciones** (menú Más › Ubicaciones): lista de lugares con **abreviatura** (lo principal: es lo que se escribe y elige), **nombre completo** (el que sale en el informe), dirección, **contactos**, **a quién se envían los informes** (e-mails y WhatsApp) y
  **médicos asociados**. «Lugar recolección» y «Lugar entrega» del protocolo se **eligen de esta lista** (escribí parte de la abreviatura o del nombre y elegí; si falta, se crea desde Ubicaciones). El **tablero** se filtra por ubicación
  (recolección o entrega) y la ficha del protocolo muestra la de entrega con sus e-mails de informes. Con el permiso *Ubicaciones* se crean, editan (cambiar la abreviatura actualiza los protocolos), eliminan (solo si ningún protocolo la usa), se asocian o
  quitan médicos y se **importa un CSV** (`abreviatura, nombre, direccion, medicos, telefonos` y opcional `emails_informes`, médicos y e-mails separados con « | »): suma lo que falte y completa nombres, direcciones y contactos vacíos, sin borrar nada. Los e-mails que aparezcan en los contactos se copian al campo de e-mails.
- **Enviar el informe** (botón *Enviar informe* en la ficha del protocolo, con el informe ya generado y vigente; permiso *Informe*): muestra una tarjeta por destinatario, cada una con su propio botón *Enviar informe* (manda solo a esa tarjeta): el **paciente** (e-mail y WhatsApp de su ficha, editables), el **médico** solicitante (su e-mail se guarda en su ficha al enviar, tildando la casilla), la **ubicación**
  (los e-mails y WhatsApp de informes de la entrega y de la recolección; vienen tildados los de la entrega que corresponden al protocolo) y **otro** (cualquier e-mail o número). Por **e-mail** sale el PDF adjunto, un mensaje por destinatario (no se ven entre sí), con asunto («Informe Adjunto : PACIENTE») y texto de introducción editables; el mensaje sale con el formato del e-mail de southernbits (franja con el lema, datos del informe: protocolo, fecha de recolección, paciente y médico, y el pie del centro).
  Por **WhatsApp** se abre la conversación con el texto ya escrito y el PDF se agrega a mano (WhatsApp no deja adjuntar desde una página). Todo queda en el *Registro de envíos* (quién, cuándo, a quién, qué emisión del informe y si falló) y en el historial del protocolo;
  los e-mails ya enviados de la emisión vigente se marcan. **A quién se envía en cada ubicación** se configura en su ficha (Ubicaciones › la ubicación › *Envío de informes*): cada e-mail o WhatsApp lleva el tilde **Informes** (solo esos se ofrecen) y se puede limitar por **tipo de estudio y malignidad** (biopsia, PAP o citología × sospechoso, maligno o no maligno); sin marcar nada recibe todos. Si el protocolo no tiene un estudio que le corresponda, el destino aparece sin tildar con el aviso «No corresponde». La **malignidad** se asigna en la ficha del protocolo, en el panel *Malignidad* (aparece cuando el estudio está informado): botones **Sospechoso** (amarillo), **Maligno** (rojo) y **No maligno** (verde), uno por tipo de estudio; se puede cambiar o quitar. Mientras no esté asignada, los destinos limitados por malignidad salen sin tildar con el aviso «Falta cargar la malignidad». Se pueden cargar desde el CSV (columna `emails_informes`, quedan con Informes tildado) o a mano. **Sin cuenta de correo en el sistema** (lo más simple en contingencia): el botón *Enviar informe* de cada tarjeta (abre un mensaje nuevo en tu programa de correo con los destinatarios, el asunto y el texto; el PDF se adjunta a mano, con el enlace *Descargar el PDF*) y *Con PDF adjunto* (un archivo que al abrirlo en Outlook ya trae el mensaje con el PDF adjunto) no necesitan ninguna configuración: se envía desde tu propia casilla de Outlook. Para el envío automático desde el sistema, el servidor necesita la cuenta de correo en `data/cloudflare.env` (`SMTP_HOST`, `SMTP_DESDE` y, según el proveedor, `SMTP_USUARIO`, `SMTP_CLAVE`, `SMTP_PORT`, `SMTP_SEGURIDAD`); sin eso la pantalla lo avisa y solo queda WhatsApp. Los administradores tienen **Administración › Correo**: muestra si el correo está configurado, cómo completarlo y permite mandar un mensaje de prueba antes de enviar informes de verdad; al guardar `data/cloudflare.env` se vuelve a leer solo.
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

`py -m vighi.herramientas.preparar_semillas` regenera `seed/*.json` desde el Excel y los CSV. Las semillas se cargan
solo en una base nueva (vacía).

## Estructura

- `app.py` — entrada del sistema (arranca el servidor); el código está en el paquete `vighi/`
- `vighi/features/` — una carpeta de código por funcionalidad: tablero, protocolos, estudios, informes, lotes, etiquetas, usuarios, facturación, listados
- `vighi/dominio/estudios/` — **un módulo por tipo de estudio** (`pap.py`, `bp.py`, `ct.py`): etapas, plazos, lotes, cantidades,
  responsable y requisitos. Para sumar un tipo nuevo se agrega un módulo y se registra en `vighi/dominio/estudios/__init__.py`.
- `vighi/dominio/trazabilidad.py` — fechas límite, OT/LT y demoras
- `vighi/core/db.py` — **todo el acceso a datos** (SQL estándar, vale para D1 y PostgreSQL)
- `vighi/templates/`, `vighi/static/` — interfaz · `seed/` — datos iniciales · `tests/` — pruebas automáticas · `docs/` — manual y planillas

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


Los datos son de pacientes: el uso de un servicio en la nube lo tiene que autorizar quien responda por la protección de datos del centro.

## PostgreSQL y archivos en la nube (preparación para producción)

El sistema puede usar **PostgreSQL** en lugar de Cloudflare D1: alcanza con definir `DATABASE_URL` en `data\cloudflare.env` (modelo en `cloudflare.env.ejemplo`); sin esa línea sigue usando D1.
Las imágenes, firmas y PDF pueden guardarse en una carpeta (`ALMACEN_DIR`) o en un bucket de S3 (`S3_BUCKET`) en lugar de dentro de la base.

**Copiar los datos de D1 a PostgreSQL (solo lee D1, no lo modifica):**
1. Con `DATABASE_URL` apuntando a una base PostgreSQL vacía: `py -m vighi.herramientas.migrar_d1_a_pg --contar` muestra cuántas filas tiene cada tabla.
2. `py -m vighi.herramientas.migrar_d1_a_pg` copia todo (pide escribir `SI`), mueve los archivos al almacén configurado y verifica cantidades y contenido de cada archivo.
Si la base de destino ya tiene datos, no copia nada.
