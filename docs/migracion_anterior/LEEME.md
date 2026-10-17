# Migración de protocolos pendientes del sistema anterior (southernbits)

Documento de traspaso para seguir el trabajo en otra sesión o en otra PC. Estado al 16/10/2026, rama `tiagob` (nada de esto está en `main`).

## Qué se quiere

Pasar al sistema nuevo **todos los protocolos pendientes de informe** de southernbits (2026; BP, PAP y CT) con: número del sistema anterior (`P1161715`, **sin número C**), datos del paciente, muestras, técnicas, macro, micro, IHQ, tracking (etapas hechas con fecha y usuario), comentarios, imágenes y órdenes escaneadas.

Decisiones ya tomadas con el usuario:
- Se extrae con Claude en Chrome sobre la sesión ya iniciada de `https://vighi.southernbits.com/gestion/` (no hay acceso a su base).
- «Pendiente de informe» = sin informe emitido (en BP coincide con el filtro *Sin diagnóstico* de Estudios).
- Repetible sin duplicar (un número ya cargado se saltea).
- Las etapas hechas se importan con fecha y usuario; los usuarios (iniciales) que no existan **se crean** y se le devuelve el listado para ajustar permisos.
- El número del sistema anterior va en el campo principal `protocolos.numero`.
- Solo 2026, todos los tipos. Los lotes se traen con el mismo código. Del nacimiento solo hay el año: queda en las observaciones, no en `fecha_nacimiento`.
- Las imágenes también se extraen y se suben a cada protocolo.

## Estado

| Parte | Estado |
|---|---|
| Lista de flujos pendientes (`flujos_lista.json`): 3033 flujos (BP 1498, PAP 1453, CT 82; 2972 protocolos) | hecha |
| Pasada 1: flujo + muestras + paciente (`flujos.jsonl`, `pacientes.jsonl`) | **hecha**: 3033 flujos y 2740 pacientes, sin errores |
| Pasada 2: formulario interno de micro (texto, diagnóstico, campos del PAP) e imágenes (`formularios.jsonl`) | **incompleta** (corría a ~0,5 flujos por segundo, ~110 min en total): es **retomable** |
| Normalizador `dominio/anterior.py`, herramienta `preparar_anterior`, servicio y pantalla `/migracion`, copia de imágenes | hechos y probados (`tests/probar_migracion_anterior.py`, D1 y PostgreSQL, datos inventados) |
| Ensayo con los datos reales | **pendiente** |
| Carga real en producción | **pendiente** (nunca se escribió nada en producción) |

El código está commiteado en la rama `tiagob` y **no se subió a `main`** (un push a `main` despliega). La pantalla es solo para administradores y no hace nada hasta que se la usa, así que subirla a `main` es seguro, pero hay que pedirle permiso al usuario antes.

## Dónde está cada cosa

- `data/migracion_anterior/` (no va a git; con OneDrive se sincroniza con la otra PC): `flujos_lista.json`, `flujos.jsonl`, `pacientes.jsonl`, `formularios.jsonl`, `protocolos_anterior.jsonl` (salida del normalizador; se regenera), `lista_*.json`.
- `docs/migracion_anterior/extractor_southernbits.js`: todo el JavaScript de la extracción, para pegarlo en la pestaña de southernbits con la herramienta `javascript_tool` de Claude en Chrome.
- `vighi/herramientas/receptor_extraccion.py`: servidor local (`127.0.0.1:8765`) que recibe lo que manda el navegador y lo guarda en `data/migracion_anterior/` (con cerrojo, una línea por registro).
- `vighi/herramientas/preparar_anterior.py`: normaliza y arma `protocolos_anterior.jsonl`; avisa de líneas dañadas y pacientes sin ficha (`pacientes_faltantes.json`).
- `vighi/dominio/anterior.py` (reglas puras), `vighi/servicios/migracion_anterior.py` (escritura en la base), `vighi/servicios/migracion_imagenes.py`, `vighi/features/migracion.py`, `vighi/templates/migracion/`, `vighi/static/migracion.js`.
- `docs/funcionalidades.md`, sección «Migración del sistema anterior»: reglas de mapeo completas.

## Cómo seguir (en orden)

1. **Receptor:** `py -m vighi.herramientas.receptor_extraccion` (en una terminal que quede abierta).
2. **Chrome:** abrir `https://vighi.southernbits.com/gestion/protocolos/` con la sesión iniciada y pegar en la consola (o con `javascript_tool`) el contenido de `extractor_southernbits.js` (Partes 1 y 2; la Parte 0 solo hace falta para rehacer las listas).
3. **Terminar la pasada 2:** `window.__pasada2(4)` y mirar `JSON.stringify(window.__ex2)`. Retoma sola (salta lo que ya está en `formularios.jsonl`). La pestaña tiene que quedar visible; no usarla para otra cosa. Los pedidos son de lectura, con 4 en paralelo.
4. **Arreglar el paciente dañado:** `pacientes.jsonl` quedó con una línea rota (línea ~2261, id 740383) por escrituras simultáneas del receptor viejo (el nuevo ya tiene cerrojo). Correr `py -m vighi.herramientas.preparar_anterior`: imprime las líneas dañadas y deja `pacientes_faltantes.json`. Borrar esas líneas de `pacientes.jsonl` y volver a pedir esos pacientes con `window.__X.parsePaciente(await window.__X.get('/gestion/pacientes/paciente/?id=<id>'))`, mandándolos a `pacientes.jsonl`. También se puede rehacer con `__pasada1` borrando esas líneas (la pasada 1 relee solo los flujos que faltan, no los pacientes).
5. **Normalizar:** `py -m vighi.herramientas.preparar_anterior` y revisar el resumen (flujos por tipo, faltantes, etapas).
6. **Ensayo:** en `/migracion` (administrador) subir `protocolos_anterior.jsonl` con *Solo ensayo* tildado: informa qué usuarios, ubicaciones, médicos, lotes y coberturas fuera de lista se crearían. Revisar con el usuario (en particular cobertura y firmantes que no se encuentran).
7. **Snapshot manual de RDS** y, recién ahí, la carga real (destildar *Solo ensayo*). Después copiar las imágenes con la segunda tarjeta (ensayo primero). La copia de imágenes baja de `s3.us-west-2.amazonaws.com/repo.southernbits.com/` desde el servidor (necesita salida a internet desde ECS, que está en subred pública) y procesa una por una: calcular un par de horas; se puede cortar y repetir.
8. Completar nombres, sectores y perfiles de los usuarios creados (la pantalla `/migracion` los lista) y avisar al usuario de los permisos `micro` para citotécnicos y `lotes_avanzar` / `etapas_deshacer`.

## Lo que se aprendió del sistema anterior

- ASP.NET WebForms. La lista de Estudios (`/gestion/externos/flujos/?sol=BP|PAP|CT`) filtra con selects que hacen postback parcial; el filtro *Actividad* es la etapa actual del flujo (usar todas las anteriores al informe, no las de archivo/entrega). La pestaña `?sol=IHQ` devuelve lo mismo que CT: se descarta (los IHQ son marcadores de un flujo BP «c/IHQ»).
- Los ids de la página (`ContentPlaceHolder1_header1_...`, `trackingactividades_rp_actividades_tracking_log_lbl_...`) son estables; están todos en el extractor.
- Flujos: `#P1161715-BP`, `-BPC` (biopsia de cuello, otro flujo del mismo protocolo), `-PAP`, `-LIQ` (citología en medio líquido, es CT); `c/IHQ` = pidió IHQ; `(U)` = urgente; `idf` es la variante del flujo.
- Las muestras de PAP no llevan letra. Las filas sin letra ni zona son prácticas: Intraoperatoria y Presencia de Patólogo (facturación, van a las observaciones), técnicas especiales (Helicobacter Pylori, Pas, Alcian Blue…) y, en flujos c/IHQ, los marcadores (CD20, Ki 67, GATA 3…).
- El comentario de una muestra se repite en todas las del protocolo (son del protocolo): se deja una vez.
- Lote de PAP: el código lleva las iniciales del citotécnico (`TP-1014.1`) y `asignado` es el citotécnico. Un PAP sin datos de paciente es normal (es el «provisorio» del sistema nuevo).
- Las imágenes están en un bucket público; cada una tiene miniatura `_thumb`. Tipos vistos: «Muestra», «Orden médica».
- El año de nacimiento es el único dato de nacimiento visible.
- La fecha de un comentario no trae año (se supone el de la recolección).

## Pendientes y dudas abiertas

- Cobertura: la lista del sistema nuevo tiene nombres largos («CENTRO DE UROLOGÍA (CDU)») y southernbits usa códigos cortos; el importador empareja por nombre o por el texto entre paréntesis y avisa lo que no encuentra.
- No se trae el estado «urgente» como campo (el sistema nuevo no lo tiene para protocolos): queda una línea en las observaciones.
- Un BP y un BPC del mismo protocolo se juntan en un solo flujo BP.
- El médico firmante del sistema anterior se busca entre los usuarios por nombre; si no está, la muestra queda sin responsable y se informa.
- Imágenes: estimadas en ~2,6 por flujo (unas 8000); la mayoría son órdenes escaneadas.
- Pantalla «Nuevo médico»: ya está en producción (`/medicos`).
