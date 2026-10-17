/*
Extractor de southernbits para la migración. Se pega por partes en la consola del navegador (o con la herramienta javascript_tool de Claude en Chrome)
dentro de una pestaña de https://vighi.southernbits.com/gestion/ con la sesión iniciada. Necesita el receptor local corriendo:
    py -m vighi.herramientas.receptor_extraccion
Todo lo que extrae se guarda en data/migracion_anterior/. Ver docs/migracion_anterior/LEEME.md.
*/

/* ============ PARTE 0: listado de flujos pendientes (una vez por pestaña BP, PAP y CT) ============
Abrir https://vighi.southernbits.com/gestion/externos/flujos/?sol=BP  (y ?sol=PAP, ?sol=CT) y pegar esto; esperar a que __prog diga "done" y mandar el resultado:
    fetch('http://127.0.0.1:8765/lista_BP.json',{method:'POST',body:JSON.stringify(window.__res.BP)})
El año y el mes de la pantalla vienen en 2026 y [ mes ]; si no, ponerlos. Después unir las tres listas en flujos_lista.json con
[{idp, idf, lista, txt, act}] (ver preparar en LEEME.md).
*/
window.__ACT = ['INGRESO: Protocolo > Cargar', 'DIAGNÓSTICOS: Macro > Informar', 'DIAGNÓSTICOS: Macro > Decal', 'LABORATORIO: Histo > Procesar', 'LABORATORIO: Cassette > Incluir',
  'LABORATORIO: Taco > Cortar', 'LABORATORIO: Taco > Cortar (nuevo corte)', 'LABORATORIO: Porta > Colorear', 'DIAGNÓSTICOS: Micro > Informar', 'TRASLADOS: Cito > Informar',
  'TRASLADOS: Lab > Colorear', 'TRASLADOS: Lab > Informar', 'TRASLADOS: Lab > Revisar', 'TRASLADOS: Lab Ext > Procesar', 'LABORATORIO: IHQ > Procesar',
  'LABORATORIO: Taco IHQ > Cortar', 'LABORATORIO: Liq > Centrifugar', 'DIAGNÓSTICOS: Micro > Interpretar', 'DIAGNÓSTICOS: Micro > Revisar'];
window.__setSel = function (suf, text) {
  return new Promise((res, rej) => {
    const s = [...document.querySelectorAll('select')].find(s => s.id.endsWith('_' + suf));
    if (!s) return rej(new Error('sin select ' + suf));
    const i = [...s.options].findIndex(o => o.text === text);
    if (i < 0) return rej(new Error('sin opcion ' + text));
    if (s.selectedIndex === i) return res('igual');
    const prm = Sys.WebForms.PageRequestManager.getInstance();
    let hecho = false;
    const h = () => { if (hecho) return; hecho = true; prm.remove_endRequest(h); setTimeout(() => res('ok'), 400); };
    prm.add_endRequest(h);
    s.selectedIndex = i;
    s.dispatchEvent(new Event('change', { bubbles: true }));
    setTimeout(() => { if (!hecho) { hecho = true; prm.remove_endRequest(h); res('timeout'); } }, 90000);
  });
};
window.__rows = function () {
  const rows = [...document.querySelectorAll('a[href*="idp="]')].map(a => { const u = new URL(a.href); return { idp: u.searchParams.get('idp'), idf: u.searchParams.get('idf'), txt: a.textContent.trim().replace(/\s+/g, ' ') }; }).filter(r => r.idp);
  const seen = new Set();
  return rows.filter(r => { const k = r.idp + '|' + r.idf; if (seen.has(k)) return false; seen.add(k); return true; });
};
window.__listar = function () {
  window.__res = {}; window.__prog = 'running';
  (async () => {
    const tab = new URL(location.href).searchParams.get('sol');
    window.__res[tab] = {};
    for (const a of window.__ACT) {
      try { const st = await window.__setSel('actividad', a); window.__res[tab][a] = { st, rows: window.__rows() }; } catch (e) { window.__res[tab][a] = 'ERR ' + e.message; }
    }
    window.__prog = 'done ' + tab;
  })();
};

/* ============ PARTE 1: leer cada flujo, sus muestras y su paciente ============ */
(() => {
  const PRE = 'ContentPlaceHolder1_';
  const el = (d, id) => d.getElementById(PRE + id) || d.getElementById(id);
  const tx = (d, id) => { const e = el(d, id); return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; };
  const multi = (d, id) => { const e = el(d, id); if (!e) return null; const c = e.cloneNode(true); c.querySelectorAll('br').forEach(b => b.replaceWith('\n')); return c.textContent.replace(/[ \t]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim(); };
  const link = (d, id) => { const e = el(d, id); if (!e) return null; const m = (e.getAttribute('href') || '').match(/[?&]id=(\d+)/); return { id: m ? m[1] : null, nombre: e.textContent.replace(/\s+/g, ' ').trim() }; };
  window.__X = {};
  window.__X.parseFlujo = function (d) {
    const f = {};
    f.numero = tx(d, 'header1_hl_protocolo'); f.tipo = tx(d, 'header1_lbl_flujo'); f.titulo = tx(d, 'lbl_titulo_flujo'); f.validado = tx(d, 'header1_lbl_validado');
    f.tipo_estudios = tx(d, 'header1_lbl_tipo_estudios'); f.estado = tx(d, 'header1_lbl_Status'); f.prioridad = tx(d, 'header1_btn_UrgenteFlagToggle');
    f.paciente = link(d, 'header1_hl_paciente'); f.edad = tx(d, 'header1_lbl_paciente_edad'); f.cobertura = tx(d, 'header1_lbl_cobertura'); f.credencial = tx(d, 'header1_lbl_nro_credencial'); f.dni = tx(d, 'header1_lbl_dni');
    f.medico = link(d, 'header1_hl_medico'); f.procedencia = link(d, 'header1_hl_ubicacion_procedencia'); f.sede = tx(d, 'header1_propiedad_sede_lbl_valor'); f.entrega = link(d, 'header1_hl_ubicacion_entrega');
    f.recorrido = tx(d, 'header1_hl_ubicacion_entrega_recorrido'); f.lote_tipo = tx(d, 'header1_lbl_sede'); f.lote = link(d, 'header1_hl_lote'); f.asignado = tx(d, 'lbl_UsuarioAsignado');
    f.macro = multi(d, 'lbl_InformeMacro_Macro'); f.micro = multi(d, 'lbl_InformeMacro_Micro'); f.autor_macro = tx(d, 'lbl_AutorInformeMacro'); f.autor_informe = tx(d, 'lbl_AutorInforme'); f.firmante = tx(d, 'lbl_MedicoFirmante');
    f.recoleccion = tx(d, 'trackingactividades_lbl_FechaRecoleccion_mobile'); f.recoleccion_largo = tx(d, 'trackingactividades_lbl_FechaRecoleccion');
    f.estimada = tx(d, 'trackingactividades_lbl_FechaEstimadaInformarMicro'); f.fecha_informe = tx(d, 'trackingactividades_lbl_FechaCompletadaInformarMicro'); f.fecha_impresion = tx(d, 'trackingactividades_lbl_FechaImpresion');
    f.tracking = [];
    for (let i = 0; i < 60; i++) {
      const a = tx(d, 'trackingactividades_rp_actividades_tracking_log_lbl_ActividadActual_' + i);
      if (a === null) break;
      f.tracking.push({ accion: a, actividad: tx(d, 'trackingactividades_rp_actividades_tracking_log_lbl_Actividad_' + i), limite: tx(d, 'trackingactividades_rp_actividades_tracking_log_lbl_FechaLimite_' + i),
        completada: tx(d, 'trackingactividades_rp_actividades_tracking_log_lbl_FechaCompletada_' + i), usuario: tx(d, 'trackingactividades_rp_actividades_tracking_log_lbl_UsuarioCompleto_' + i) });
    }
    f.pendientes = [];
    for (let i = 0; i < 30; i++) {
      const a = tx(d, 'trackingactividades_rp_actividades_tracking_lbl_ActividadActual_' + i) || tx(d, 'trackingactividades_rp_actividades_tracking_hl_ActividadActual_' + i);
      if (a === null) break;
      f.pendientes.push({ accion: a, actividad: tx(d, 'trackingactividades_rp_actividades_tracking_lbl_Actividad_' + i), limite: tx(d, 'trackingactividades_rp_actividades_tracking_lbl_FechaLimite_' + i),
        estimada: tx(d, 'trackingactividades_rp_actividades_tracking_lbl_FechaEstimada_' + i) });
    }
    f.estudios = [];
    for (let i = 0; i < 80; i++) {
      const h = el(d, 'estudios1_rp_estudios_hl_Estudio_' + i);
      if (!h) break;
      const m = (h.getAttribute('href') || '').match(/[?&]id=(\d+)/);
      f.estudios.push({ eid: m ? m[1] : null, orden: tx(d, 'estudios1_rp_estudios_lbl_OrdenLetra_' + i), nombre: h.textContent.replace(/\s+/g, ' ').trim(), libre: tx(d, 'estudios1_rp_estudios_lbl_DescripcionLibreEstudio_' + i),
        organo: tx(d, 'estudios1_rp_estudios_lbl_organo_' + i), tacos: tx(d, 'estudios1_rp_estudios_lbl_tacos_cant_' + i), tecnicas_pub: tx(d, 'estudios1_rp_estudios_lbl_TecnicasPublicadas_' + i) });
    }
    f.tecnicas = [];
    for (let i = 0; i < 80; i++) {
      const e = el(d, 'tecnicas_rp_tecnicas_lbl_Estudio_' + i);
      if (!e) break;
      const c = e.closest('tr,li,.row') || e.parentElement;
      f.tecnicas.push(c.textContent.replace(/\s+/g, ' ').trim());
    }
    const hm = d.querySelector('[id$="hl_informar_micro_bp"],[id$="hl_informar_micro"]');
    f.informar_href = hm ? (hm.getAttribute('href') || '').split('?')[0] : null;
    return f;
  };
  window.__X.parseEstudio = function (d) {
    const c = [];
    for (let i = 0; i < 60; i++) {
      const u = tx(d, 'comentarios_rp_comentarios_lbl_usuario_creador_' + i);
      if (u === null) break;
      c.push({ usuario: u, fecha: tx(d, 'comentarios_rp_comentarios_lbl_fecha_hora_creacion_' + i), texto: multi(d, 'comentarios_rp_comentarios_lbl_Comentario_' + i) });
    }
    return { nomenclador: tx(d, 'lbl_Nomenclatura'), unidades: tx(d, 'lbl_Unidades'), tipo: tx(d, 'lbl_Estudio'), zona: tx(d, 'lbl_tipo_biopsia'), organo: tx(d, 'lbl_Organo'), tacos: tx(d, 'lbl_tacos_cant'),
      libre: tx(d, 'lbl_descripcion_libre'), actividad: tx(d, 'lbl_ActividadActual'), comentarios: c };
  };
  window.__X.parsePaciente = function (d) {
    return { nombre: tx(d, 'lbl_Paciente'), dni: tx(d, 'lbl_DNI'), sexo: tx(d, 'lbl_Sexo'), edad: tx(d, 'lbl_edad'), telefono: tx(d, 'lbl_Telefono'), email: tx(d, 'lbl_Email'), domicilio: tx(d, 'lbl_Domicilio'),
      cobertura: tx(d, 'lbl_Cobertura'), credencial: tx(d, 'lbl_NroCredencial'), iva: tx(d, 'lbl_IVA'), observaciones: tx(d, 'lbl_Observaciones') };
  };
  window.__X.get = async function (u) {
    const r = await fetch(u, { credentials: 'include' });
    const b = await r.arrayBuffer();
    const cs = ((r.headers.get('content-type') || '').match(/charset=([^;]+)/) || [])[1] || 'utf-8';
    if (r.status !== 200) throw new Error('HTTP ' + r.status + ' ' + u.split('?')[0]);
    return new DOMParser().parseFromString(new TextDecoder(cs).decode(b), 'text/html');
  };
  window.__X.flujo = async function (idp, idf) {
    const d = await window.__X.get('/gestion/flujos/flujo/?idp=' + idp + '&idf=' + idf);
    const f = window.__X.parseFlujo(d);
    f.idp = idp; f.idf = idf;
    for (const e of f.estudios) if (e.eid) e.detalle = window.__X.parseEstudio(await window.__X.get('/gestion/estudios/estudio/?id=' + e.eid));
    return f;
  };
})();

/* Lanza la primera pasada (retoma sola: salta lo que ya está en flujos.jsonl). Seguir el avance con JSON.stringify(window.__ex). Los pacientes que falten
(pacientes_faltantes.json) se vuelven a pedir borrando de pacientes.jsonl las líneas dañadas y relanzando. */
window.__pasada1 = async function (concurrencia = 4) {
  const lista = await (await fetch('http://127.0.0.1:8765/f/flujos_lista.json')).json();
  const hechos = new Set();
  try { const t = await (await fetch('http://127.0.0.1:8765/f/flujos.jsonl')).text(); if (t.length > 3) t.split('\n').forEach(l => { const m = l.match(/"idp":"(\d+)","idf":"(\d+)"/); if (m) hechos.add(m[1] + '|' + m[2]); }); } catch (e) { }
  const pend = lista.filter(x => !hechos.has(x.idp + '|' + x.idf));
  window.__ex = { total: lista.length, previos: hechos.size, hechos: 0, errores: [], pacientes: 0, estado: 'corriendo', t0: Date.now() };
  const pacs = new Set();
  let i = 0;
  async function una(x) {
    for (let intento = 0; intento < 3; intento++) {
      try {
        const f = await window.__X.flujo(x.idp, x.idf);
        f.lista = x.lista; f.act = x.act;
        const r = await fetch('http://127.0.0.1:8765/flujos.jsonl', { method: 'POST', body: JSON.stringify(f) });
        if (!r.ok) throw new Error('receptor');
        if (f.paciente && f.paciente.id && !pacs.has(f.paciente.id)) {
          pacs.add(f.paciente.id);
          const p = window.__X.parsePaciente(await window.__X.get('/gestion/pacientes/paciente/?id=' + f.paciente.id));
          p.id = f.paciente.id;
          await fetch('http://127.0.0.1:8765/pacientes.jsonl', { method: 'POST', body: JSON.stringify(p) });
          window.__ex.pacientes++;
        }
        window.__ex.hechos++;
        return;
      } catch (e) { if (intento === 2) window.__ex.errores.push(x.idp + '|' + x.idf + ': ' + e.message); else await new Promise(r => setTimeout(r, 1500)); }
    }
  }
  async function obrero() { while (i < pend.length) { const x = pend[i++]; await una(x); } }
  await Promise.all(Array.from({ length: concurrencia }, obrero));
  window.__ex.estado = 'terminado';
};

/* ============ PARTE 2: formulario interno de micro (BP/CT y PAP) e imágenes de cada flujo ============ */
window.__g = async function (u) {
  const r = await fetch(u, { credentials: 'include' });
  const b = await r.arrayBuffer();
  const cs = ((r.headers.get('content-type') || '').match(/charset=([^;]+)/) || [])[1] || 'utf-8';
  return new DOMParser().parseFromString(new TextDecoder(cs).decode(b), 'text/html');
};
window.__F = {};
window.__F.parseForm = function (d) {
  const campos = {};
  d.querySelectorAll('input,textarea,select').forEach(e => {
    const id = (e.id || '').replace('ContentPlaceHolder1_', '');
    if (!id || e.type === 'hidden' || e.type === 'file') return;
    if (/tb_protocolo_buscar|Filtro|filtro|emplates|id_protocolo|dd_tipos|fu1/i.test(id)) return;
    let v;
    if (e.tagName === 'SELECT') { v = ((e.options[e.selectedIndex] || {}).text || '').trim(); if (/^\[ ?N\/D ?\]$|^\[ .* \]$/.test(v)) v = ''; }
    else if (e.type === 'checkbox') v = e.checked ? '1' : '';
    else v = (e.value || '').trim();
    if (v !== '') campos[id] = v;
  });
  const imgs = [];
  d.querySelectorAll('a[href*="repo.southernbits.com"]').forEach(a => {
    const im = a.querySelector('img'); const cont = a.parentElement; const lab = cont ? (cont.querySelector('small') || {}).textContent : '';
    imgs.push({ url: a.getAttribute('href').split('?')[0], thumb: im ? im.getAttribute('src').split('?')[0] : null, tipo: (lab || '').trim() });
  });
  return { campos, imagenes: imgs };
};
window.__F.una = async function (idp, idf) {
  const d0 = await window.__g('/gestion/flujos/flujo/?idp=' + idp + '&idf=' + idf);
  const as = [...d0.querySelectorAll('a[href*="informar/micro"]')];
  if (!as.length) return { idp, idf, sin_form: true };
  const out = [], vistos = new Set();
  for (const a of as) {
    const u = new URL(a.getAttribute('href'), 'https://vighi.southernbits.com/gestion/flujos/flujo/');
    if (vistos.has(u.pathname)) continue;
    vistos.add(u.pathname);
    out.push({ form: u.pathname.replace(/^.*informar\//, ''), ...window.__F.parseForm(await window.__g(u.pathname + u.search)) });
  }
  return { idp, idf, formularios: out };
};
window.__pasada2 = async function (concurrencia = 4) {
  const lista = await (await fetch('http://127.0.0.1:8765/f/flujos_lista.json')).json();
  const hechos = new Set();
  try { const t = await (await fetch('http://127.0.0.1:8765/f/formularios.jsonl')).text(); if (t.length > 3) t.split('\n').forEach(l => { const m = l.match(/"idp":"(\d+)","idf":"(\d+)"/); if (m) hechos.add(m[1] + '|' + m[2]); }); } catch (e) { }
  const pend = lista.filter(x => !hechos.has(x.idp + '|' + x.idf));
  window.__ex2 = { total: lista.length, previos: hechos.size, hechos: 0, errores: [], estado: 'corriendo', t0: Date.now(), imagenes: 0 };
  let i = 0;
  async function una(x) {
    for (let intento = 0; intento < 3; intento++) {
      try {
        const r = await window.__F.una(x.idp, x.idf);
        const p = await fetch('http://127.0.0.1:8765/formularios.jsonl', { method: 'POST', body: JSON.stringify(r) });
        if (!p.ok) throw new Error('receptor');
        window.__ex2.hechos++;
        window.__ex2.imagenes += (r.formularios || []).reduce((a, f) => a + f.imagenes.length, 0);
        return;
      } catch (e) { if (intento === 2) window.__ex2.errores.push(x.idp + '|' + x.idf + ': ' + e.message); else await new Promise(r => setTimeout(r, 1500)); }
    }
  }
  async function obrero() { while (i < pend.length) { const x = pend[i++]; await una(x); } }
  await Promise.all(Array.from({ length: concurrencia }, obrero));
  window.__ex2.estado = 'terminado';
};
