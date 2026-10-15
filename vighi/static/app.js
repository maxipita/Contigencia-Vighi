document.querySelectorAll("label:not([for])").forEach((lab, i) => {
  if (lab.querySelector("input, select, textarea")) return;
  const campo = lab.nextElementSibling;
  if (!campo || !/^(INPUT|SELECT|TEXTAREA)$/.test(campo.tagName)) return;
  campo.id = campo.id || `campo_${i}`;
  lab.htmlFor = campo.id;
});

const catalogos = {};
const catalogo = tipo => (catalogos[tipo] = catalogos[tipo] || fetch(`/api/catalogo/${tipo}`).then(r => r.json()));

async function prepararBloque(bloque) {
  const campo = c => bloque.querySelector(`[data-cat="${c}"]`);
  const [sub, sitio, tm] = ["subcategoria", "sitio", "tipo_muestra"].map(campo);
  const arbol = await catalogo(bloque.dataset.tipo);
  const llenar = (sel, opciones, actual, falta) => {
    sel.disabled = !opciones.length;
    const aviso = opciones.length ? "Seleccionar…" : (falta ? `Elegí ${falta} primero` : "Sin opciones");
    sel.innerHTML = `<option value="" hidden>${aviso}</option>` + opciones.map(o =>
      `<option${o === actual ? " selected" : ""}>${o.replace(/</g, "&lt;")}</option>`).join("");
  };
  const fijo = !sub;
  const subVal = () => fijo ? Object.keys(arbol)[0] : sub.value;
  const sitioVal = () => fijo ? Object.keys(arbol[subVal()] || {})[0] : sitio.value;
  const actualizar = desde => {
    if (!fijo && desde === "inicio") llenar(sub, Object.keys(arbol), sub.dataset.actual);
    const sitios = arbol[subVal()] || {};
    if (!fijo && desde !== "sitio") llenar(sitio, Object.keys(sitios), desde === "inicio" ? sitio.dataset.actual : "",
                                           !subVal() && "la subcategoría");
    llenar(tm, sitios[sitioVal()] || [], desde === "inicio" ? tm.dataset.actual : "", !sitioVal() && "el sitio");
  };
  if (!fijo) {
    sub.addEventListener("change", () => actualizar("sub"));
    sitio.addEventListener("change", () => actualizar("sitio"));
  }
  actualizar("inicio");

  const cito = bloque.querySelector("select[data-lote-cito]");
  if (cito) cito.addEventListener("change", () => {
    const lote = bloque.querySelector("select[name$='-lote_id']");
    const ini = cito.selectedOptions[0] && cito.selectedOptions[0].dataset.ini;
    if (!lote || !ini || lote.value) return;
    const opcion = lote.querySelector(`option[data-tipo="${ini}"]`) || lote.querySelector(`option[value="nuevo:${ini}"]`);
    if (opcion) lote.value = opcion.value;
  });
  const quitar = bloque.querySelector("[data-quitar-bloque]");
  if (quitar) quitar.addEventListener("click", () => bloque.remove());
}

let siguienteBloque = 100;
document.querySelectorAll(".estudio-bloque").forEach(b => { if (!b.closest("template")) prepararBloque(b); });
document.querySelectorAll("[data-agregar-estudio]").forEach(btn => btn.addEventListener("click", () => {
  const form = btn.closest("form");
  const n = siguienteBloque++;
  const html = document.getElementById(`tpl-estudio-${btn.dataset.agregarEstudio}`).innerHTML.replaceAll("__N__", n);
  form.querySelector(".bloques").insertAdjacentHTML("beforeend", html);
  const nuevo = form.querySelector(".bloques").lastElementChild;
  prepararBloque(nuevo);
  nuevo.scrollIntoView({ behavior: "smooth", block: "center" });
}));

document.querySelectorAll("select[data-templates]").forEach(sel => {
  const destino = document.getElementById(sel.dataset.destino);
  const concl = sel.dataset.conclusion ? document.getElementById(sel.dataset.conclusion) : null;
  const guardados = sel.value && !sel.selectedOptions[0].dataset.id ? sel.value : "";
  const usados = guardados ? guardados.split("; ").filter(Boolean) : [];
  const oculto = document.createElement("input");
  oculto.type = "hidden";
  oculto.name = sel.name;
  sel.removeAttribute("name");
  sel.after(oculto);
  const resumen = document.createElement("div");
  resumen.className = "muted templates-usados";
  oculto.after(resumen);
  [...sel.options].forEach(o => { if (!o.dataset.id && o.value) o.remove(); });
  sel.value = "";
  const marcador = sel.options[0];
  const maestra = [...sel.options].filter(o => o.dataset.id).map(o => o.cloneNode(true));
  const panel = sel.previousElementSibling && sel.previousElementSibling.classList.contains("filtro-templates") ? sel.previousElementSibling : null;
  const normTpl = s => (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  const dibujar = () => {
    const fz = panel ? normTpl(panel.querySelector('[data-filtro="zona"]').value) : "";
    const fo = panel ? normTpl(panel.querySelector('[data-filtro="organo"]').value) : "";
    const ft = panel ? normTpl(panel.querySelector('[data-filtro="tipo"]').value) : "";
    const coinciden = [], generales = [];
    maestra.forEach(o => {
      let excluido = false, coincide = false;
      for (const [attr, f] of [[o.dataset.zona, fz], [o.dataset.organo, fo], [o.dataset.tipo, ft]]) {
        const a = normTpl(attr);
        if (!f || !a) continue;
        if (a === f) coincide = true; else { excluido = true; break; }
      }
      if (!excluido) (coincide ? coinciden : generales).push(o);
    });
    sel.innerHTML = "";
    sel.append(marcador);
    if (coinciden.length && generales.length) {
      const g1 = document.createElement("optgroup");
      g1.label = "Para esta selección";
      coinciden.forEach(o => g1.append(o.cloneNode(true)));
      const g2 = document.createElement("optgroup");
      g2.label = "Generales (sin clasificar)";
      generales.forEach(o => g2.append(o.cloneNode(true)));
      sel.append(g1, g2);
    } else {
      coinciden.concat(generales).forEach(o => sel.append(o.cloneNode(true)));
    }
    sel.value = "";
    const cuenta = panel && panel.querySelector(".cuenta-templates");
    if (cuenta) cuenta.textContent = `${coinciden.length + generales.length} de ${maestra.length} templates`;
  };
  if (panel) {
    const fz = panel.querySelector('[data-filtro="zona"]'), fo = panel.querySelector('[data-filtro="organo"]'), ft = panel.querySelector('[data-filtro="tipo"]');
    const llenar = (select, valores, actual) => {
      const primero = select.options[0];
      select.innerHTML = "";
      select.append(primero);
      valores.forEach(v => { const op = document.createElement("option"); op.textContent = v; op.value = v; select.append(op); });
      const coincide = valores.find(v => normTpl(v) === normTpl(actual));
      select.value = coincide || "";
    };
    catalogo(panel.dataset.catalogo).then(arbol => {
      const zonas = Object.keys(arbol).sort((x, y) => x.localeCompare(y, "es"));
      const unicos = lista => { const vistos = {}; lista.forEach(v => { const k = normTpl(v); if (k && !vistos[k]) vistos[k] = v; }); return Object.values(vistos).sort((x, y) => x.localeCompare(y, "es")); };
      const organosDe = z => { const set = new Set(); (z ? [z] : zonas).forEach(k => Object.keys(arbol[k] || {}).forEach(s => set.add(s))); return [...set].sort((x, y) => x.localeCompare(y, "es")); };
      const tiposDe = (z, o) => { const l = []; (z ? [z] : zonas).forEach(k => Object.entries(arbol[k] || {}).forEach(([s, ts]) => { if (!o || s === o) l.push(...ts); })); return unicos(l); };
      llenar(fz, zonas, panel.dataset.zona);
      llenar(fo, organosDe(fz.value), panel.dataset.organo);
      llenar(ft, tiposDe(fz.value, fo.value), panel.dataset.tipo);
      dibujar();
      fz.addEventListener("change", () => { llenar(fo, organosDe(fz.value), ""); llenar(ft, tiposDe(fz.value, ""), ft.value); dibujar(); });
      fo.addEventListener("change", () => { llenar(ft, tiposDe(fz.value, fo.value), ft.value); dibujar(); });
      ft.addEventListener("change", dibujar);
    });
  }
  const pintar = () => {
    oculto.value = usados.join("; ");
    resumen.textContent = "";
    if (!usados.length) return;
    resumen.append("Templates agregados: " + usados.join(" · ") + " ");
    const limpiar = document.createElement("button");
    limpiar.type = "button";
    limpiar.className = "lapiz";
    limpiar.textContent = "limpiar lista";
    limpiar.addEventListener("click", () => { usados.length = 0; pintar(); oculto.dispatchEvent(new Event("input", { bubbles: true })); });
    resumen.append(limpiar);
  };
  const sumar = (campo, texto, separador) => {
    texto = (texto || "").trim();
    if (!texto) return;
    const actual = campo.value.replace(/\s+$/, "");
    campo.value = actual ? actual + separador + texto : texto;
  };
  pintar();
  sel.addEventListener("change", async () => {
    const id = sel.selectedOptions[0] && sel.selectedOptions[0].dataset.id;
    if (!id) return;
    const titulo = sel.selectedOptions[0].value;
    const t = await (await fetch(`/api/template/${id}`)).json();
    sumar(destino, t.texto, "\n\n");
    if (concl) sumar(concl, t.conclusion, "\n");
    if (!usados.includes(titulo)) usados.push(titulo);
    pintar();
    sel.value = "";
    destino.focus();
    destino.dispatchEvent(new Event("input", { bubbles: true }));
  });
});

const sinAcentos = s => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
document.querySelectorAll("input[data-medicos], input[data-ubicaciones]").forEach(async inp => {
  const deLista = inp.hasAttribute("data-ubicaciones");
  const nombres = (await (await fetch(deLista ? "/api/ubicaciones" : "/api/medicos")).json())
    .map(n => typeof n === "string" ? [n, sinAcentos(n), n] : [n.v, sinAcentos(n.v + " " + n.n), n.n ? n.v + " — " + n.n : n.v]);
  const caja = document.createElement("div");
  caja.className = "sugerencias";
  caja.hidden = true;
  inp.after(caja);
  let activo = -1;
  const marcar = i => {
    const items = caja.children;
    if (!items.length) return;
    activo = (i + items.length) % items.length;
    [...items].forEach((el, k) => el.classList.toggle("activo", k === activo));
    items[activo].scrollIntoView({ block: "nearest" });
  };
  const elegir = nombre => { inp.value = nombre; caja.hidden = true; };
  const mostrar = () => {
    const palabras = sinAcentos(inp.value).split(/\s+/).filter(Boolean);
    caja.innerHTML = "";
    activo = -1;
    if (!palabras.length) { caja.hidden = true; return; }
    const coinciden = nombres.filter(([, s]) => palabras.every(p => s.includes(p)));
    const hallados = [...coinciden.filter(([, s]) => s.startsWith(palabras[0])),
                      ...coinciden.filter(([, s]) => !s.startsWith(palabras[0]))].slice(0, 40);
    hallados.forEach(([n, , texto]) => {
      const el = document.createElement("div");
      el.textContent = texto;
      el.dataset.valor = n;
      el.addEventListener("mousedown", e => { e.preventDefault(); elegir(n); });
      caja.append(el);
    });
    if (!hallados.length) caja.innerHTML = '<div class="nada">' + (deLista ? "Sin coincidencias: elegí una de la lista" : "Sin coincidencias (se guarda lo escrito)") + "</div>";
    caja.hidden = false;
  };
  inp.addEventListener("input", mostrar);
  inp.addEventListener("focus", () => inp.value && mostrar());
  inp.addEventListener("blur", () => { caja.hidden = true; });
  inp.addEventListener("keydown", e => {
    if (caja.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); marcar(activo + (e.key === "ArrowDown" ? 1 : -1)); }
    else if (e.key === "Enter" && activo >= 0 && caja.children[activo].dataset.valor) { e.preventDefault(); elegir(caja.children[activo].dataset.valor); }
    else if (e.key === "Escape") caja.hidden = true;
  });
});

document.querySelectorAll("input[data-filtrar]").forEach(inp => {
  const items = [...document.querySelectorAll(inp.dataset.filtrar + " > label")].map(el => [el, sinAcentos(el.textContent)]);
  inp.addEventListener("input", () => {
    const palabras = sinAcentos(inp.value).split(/\s+/).filter(Boolean);
    items.forEach(([el, s]) => { el.hidden = !palabras.every(p => s.includes(p)); });
  });
});

document.querySelectorAll("input[list]").forEach(inp => {
  const lista = document.getElementById(inp.getAttribute("list"));
  if (!lista) return;
  const opciones = [...lista.options].map(o => ({ valor: o.value, texto: o.textContent.trim(), buscar: sinAcentos(o.value + " " + o.textContent) }));
  inp.removeAttribute("list");
  const envoltorio = document.createElement("div");
  envoltorio.className = "buscador buscador-combo";
  inp.before(envoltorio);
  envoltorio.append(inp);
  const caja = document.createElement("div");
  caja.className = "sugerencias";
  caja.hidden = true;
  envoltorio.append(caja);
  let activo = -1;
  const marcar = i => {
    const items = caja.querySelectorAll("[data-valor]");
    if (!items.length) return;
    activo = (i + items.length) % items.length;
    items.forEach((el, k) => el.classList.toggle("activo", k === activo));
    items[activo].scrollIntoView({ block: "nearest" });
  };
  const elegir = valor => { inp.value = valor; caja.hidden = true; };
  const mostrar = (todo) => {
    const palabras = todo ? [] : sinAcentos(inp.value).split(/\s+/).filter(Boolean);
    const hallados = opciones.filter(o => palabras.every(p => o.buscar.includes(p))).slice(0, 60);
    caja.innerHTML = "";
    activo = -1;
    hallados.forEach(o => {
      const el = document.createElement("div");
      el.dataset.valor = o.valor;
      const b = document.createElement("b");
      b.textContent = o.valor;
      el.append(b);
      if (o.texto && o.texto !== o.valor) {
        const d = document.createElement("span");
        d.className = "desc";
        d.textContent = o.texto;
        el.append(d);
      }
      el.addEventListener("mousedown", e => { e.preventDefault(); elegir(o.valor); });
      caja.append(el);
    });
    if (!hallados.length) caja.innerHTML = '<div class="nada">Sin coincidencias (se guarda lo escrito)</div>';
    caja.hidden = false;
    ubicar();
  };
  const ubicar = () => {
    const r = inp.getBoundingClientRect();
    const abajo = window.innerHeight - r.bottom;
    caja.style.left = Math.max(8, Math.min(r.left, window.innerWidth - caja.offsetWidth - 8)) + "px";
    if (abajo < 220 && r.top > abajo) {
      caja.style.top = "auto";
      caja.style.bottom = (window.innerHeight - r.top + 2) + "px";
      caja.style.maxHeight = Math.min(260, r.top - 12) + "px";
    } else {
      caja.style.bottom = "auto";
      caja.style.top = (r.bottom + 2) + "px";
      caja.style.maxHeight = Math.min(260, abajo - 12) + "px";
    }
  };
  window.addEventListener("scroll", () => { if (!caja.hidden) ubicar(); }, true);
  window.addEventListener("resize", () => { if (!caja.hidden) ubicar(); });
  inp.addEventListener("input", () => mostrar(false));
  inp.addEventListener("focus", () => { inp.select(); mostrar(true); });
  inp.addEventListener("blur", () => { caja.hidden = true; });
  inp.addEventListener("keydown", e => {
    if (caja.hidden) {
      if (e.key === "ArrowDown") { e.preventDefault(); mostrar(false); }
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); marcar(activo + (e.key === "ArrowDown" ? 1 : -1)); }
    else if (e.key === "Enter" && activo >= 0) { e.preventDefault(); elegir(caja.querySelectorAll("[data-valor]")[activo].dataset.valor); }
    else if (e.key === "Escape") caja.hidden = true;
  });
});

document.querySelectorAll("form[data-confirmar]").forEach(f =>
  f.addEventListener("submit", e => { if (!confirm(f.dataset.confirmar)) e.preventDefault(); }));

(function () {
  var html = document.documentElement, boton = document.getElementById("alternarMenu");
  var desplegables = document.querySelectorAll(".desplegable");
  var avatar = document.getElementById("menuUsuario"), lista = document.getElementById("menuUsuarioLista");
  function cerrarListas(salvo) {
    desplegables.forEach(function (d) { if (d !== salvo) d.classList.remove("abierto"); });
    if (lista && salvo !== lista) lista.classList.remove("abierto");
  }
  if (boton) boton.addEventListener("click", function (e) { e.stopPropagation(); html.classList.toggle("menu-abierto"); });
  desplegables.forEach(function (d) {
    d.querySelector("[data-abre]").addEventListener("click", function (e) {
      e.stopPropagation();
      cerrarListas(d);
      d.classList.toggle("abierto");
    });
  });
  if (avatar && lista) {
    avatar.addEventListener("click", function (e) { e.stopPropagation(); cerrarListas(lista); lista.classList.toggle("abierto"); });
  }
  document.addEventListener("click", function (e) {
    cerrarListas(null);
    var menu = document.getElementById("menuPrincipal");
    if (menu && !menu.contains(e.target)) html.classList.remove("menu-abierto");
  });
})();

(function () {
  var tabla = document.querySelector("table.ajustes[data-perfiles]"), perfil = document.getElementById("perfil_id");
  if (!tabla || !perfil) return;
  var perfiles = JSON.parse(tabla.dataset.perfiles), admin = document.querySelector("input[name=admin]");
  function pintar() {
    var delPerfil = perfiles[perfil.value] || [];
    tabla.querySelectorAll("tr[data-permiso]").forEach(function (fila) {
      var k = fila.dataset.permiso, base = delPerfil.indexOf(k) >= 0, ajuste = fila.querySelector("select").value;
      var final = admin && admin.checked ? true : ajuste === "mas" ? true : ajuste === "menos" ? false : base;
      fila.querySelector(".del-perfil").innerHTML = base ? '<span class="si">✔</span>' : '<span class="no">—</span>';
      fila.querySelector(".resultado").innerHTML = final ? '<span class="si">✔ Puede</span>' : '<span class="no">No puede</span>';
      fila.classList.toggle("ajustado", ajuste !== "");
    });
  }
  tabla.addEventListener("change", pintar);
  perfil.addEventListener("change", pintar);
  if (admin) admin.addEventListener("change", pintar);
  pintar();
})();

(function () {
  document.querySelectorAll("form.filtros").forEach(function (form) {
    var espera, guardado = null;
    try { guardado = sessionStorage.getItem("filtro_foco"); sessionStorage.removeItem("filtro_foco"); } catch (e) {}
    form.classList.add("auto");
    form.addEventListener("change", function (e) {
      if (e.target.tagName === "SELECT") form.submit();
    });
    form.querySelectorAll("input[type=text], input:not([type])").forEach(function (campo) {
      if (guardado && campo.name === guardado) {
        campo.focus();
        campo.setSelectionRange(campo.value.length, campo.value.length);
      }
      campo.addEventListener("input", function () {
        clearTimeout(espera);
        espera = setTimeout(function () {
          try { sessionStorage.setItem("filtro_foco", campo.name); } catch (e) {}
          form.submit();
        }, 500);
      });
    });
  });
})();

document.querySelectorAll("form.edicion").forEach(function (form) {
  form.querySelectorAll("[data-editar]").forEach(b => b.addEventListener("click", () => {
    form.classList.add("editando");
    const primero = form.querySelector(".editar input, .editar select");
    if (primero) primero.focus();
  }));
  form.querySelectorAll("[data-cancelar]").forEach(b => b.addEventListener("click", () => {
    form.reset();
    form.classList.remove("editando");
  }));
});

(function () {
  const enlaces = [...document.querySelectorAll("a[data-visor]")];
  if (!enlaces.length) return;
  const visor = document.createElement("div");
  visor.className = "visor";
  visor.hidden = true;
  visor.innerHTML = '<button type="button" class="visor-x" aria-label="Cerrar">×</button><button type="button" class="visor-ant" aria-label="Anterior">‹</button>' +
    '<img alt=""><button type="button" class="visor-sig" aria-label="Siguiente">›</button><div class="visor-pie"></div>';
  document.body.append(visor);
  const img = visor.querySelector("img"), pie = visor.querySelector(".visor-pie");
  let actual = 0;
  const mostrar = i => {
    actual = (i + enlaces.length) % enlaces.length;
    img.src = enlaces[actual].href;
    pie.textContent = (enlaces[actual].title || "") + (enlaces.length > 1 ? "  (" + (actual + 1) + "/" + enlaces.length + ")" : "");
    visor.hidden = false;
  };
  const cerrar = () => { visor.hidden = true; img.removeAttribute("src"); };
  enlaces.forEach((a, i) => a.addEventListener("click", e => { e.preventDefault(); mostrar(i); }));
  visor.querySelector(".visor-x").addEventListener("click", cerrar);
  visor.querySelector(".visor-ant").addEventListener("click", () => mostrar(actual - 1));
  visor.querySelector(".visor-sig").addEventListener("click", () => mostrar(actual + 1));
  visor.addEventListener("click", e => { if (e.target === visor) cerrar(); });
  document.addEventListener("keydown", e => {
    if (visor.hidden) return;
    if (e.key === "Escape") cerrar();
    else if (e.key === "ArrowLeft") mostrar(actual - 1);
    else if (e.key === "ArrowRight") mostrar(actual + 1);
  });
})();

(function () {
  const estudio = document.querySelector("[data-tecnica-estudio]");
  if (!estudio) return;
  const form = estudio.closest("form");
  const tacos = form.querySelector("[data-tecnica-tacos]");
  const nro = form.querySelector("[data-tecnica-nro]");
  const inclusion = form.querySelector("[data-tecnica-inclusion]");
  function aplicar() {
    const op = estudio.selectedOptions[0];
    if (!op) return;
    tacos.value = op.dataset.tacos || "";
    nro.value = op.dataset.nro || "";
    if (inclusion) inclusion.value = op.dataset.inclusion || inclusion.options[0].value;
  }
  estudio.addEventListener("change", aplicar);
  aplicar();
})();

(function () {
  const grupos = document.querySelectorAll("[data-chips]");
  grupos.forEach((grupo) => {
    const destino = document.getElementById(grupo.dataset.chips);
    if (!destino) return;
    const leer = () => destino.value.split(/[,;\n]+/).map((x) => x.trim()).filter(Boolean);
    const pintar = () => {
      const marcados = leer().map((x) => x.toLowerCase());
      grupo.querySelectorAll(".chip-sel").forEach((b) => b.classList.toggle("on", marcados.includes(b.dataset.valor.toLowerCase())));
    };
    grupo.addEventListener("click", (ev) => {
      const b = ev.target.closest(".chip-sel");
      if (!b) return;
      const valor = b.dataset.valor;
      const actuales = leer();
      const i = actuales.findIndex((x) => x.toLowerCase() === valor.toLowerCase());
      if (i >= 0) actuales.splice(i, 1);
      else actuales.push(valor);
      destino.value = actuales.join(", ");
      pintar();
      destino.dispatchEvent(new Event("input", { bubbles: true }));
    });
    destino.addEventListener("input", pintar);
    pintar();
  });
})();

(function () {
  function agregar(entrada) {
    const campo = entrada.closest(".ancho");
    const lista = campo.querySelector(".checks");
    const valor = entrada.value.replace(/[,;]/g, " ").replace(/\s+/g, " ").trim().slice(0, 80);
    if (!valor) return;
    const existente = [...lista.querySelectorAll("input[type=checkbox]")].find((c) => c.value.toLowerCase() === valor.toLowerCase());
    if (existente) existente.checked = true;
    else {
      const rotulo = document.createElement("label");
      rotulo.className = "check";
      const caja = document.createElement("input");
      caja.type = "checkbox";
      caja.name = lista.dataset.nombre;
      caja.value = valor;
      caja.checked = true;
      rotulo.append(caja, " " + valor);
      lista.append(rotulo);
    }
    entrada.value = "";
    entrada.focus();
  }
  document.addEventListener("click", (ev) => {
    const boton = ev.target.closest("[data-agregar-tecnica]");
    if (boton) agregar(boton.parentElement.querySelector("[data-otra-tecnica]"));
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && ev.target.matches("[data-otra-tecnica]")) {
      ev.preventDefault();
      agregar(ev.target);
    }
  });
})();

(function () {
  const formulario = document.getElementById("form-envio");
  if (!formulario) return;
  formulario.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && ev.target.tagName === "INPUT") ev.preventDefault();
  });
  formulario.addEventListener("submit", (ev) => {
    const s = ev.submitter;
    if (!s) return;
    if (s.hasAttribute("data-borrador")) { setTimeout(() => location.reload(), 1500); return; }
    const texto = s.querySelector("span");
    setTimeout(() => { s.disabled = true; if (texto) texto.textContent = "Enviando…"; });
  });

  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-correo]");
    if (!b) return;
    const datos = new FormData(formulario);
    datos.set("modo", "mailto");
    datos.set("solo", b.dataset.solo || "");
    b.disabled = true;
    try {
      const r = await fetch(location.pathname + "/correo", { method: "POST", body: datos, headers: { "X-CSRF": formulario.querySelector("[name=_csrf]").value } });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "No se pudo preparar el mensaje.");
      location.href = d.enlace;
      setTimeout(() => location.reload(), 2000);
    } catch (e) {
      alert(e.message);
      b.disabled = false;
    }
  });

  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-wa]");
    if (!b) return;
    const numero = b.closest(".dest-fila").querySelector("[data-wa-numero]").value.trim();
    if (!numero) { alert("Escribí el número de WhatsApp."); return; }
    const ventana = window.open("about:blank", "_blank");
    const datos = new FormData();
    datos.append("numero", numero);
    datos.append("rol", b.dataset.rol);
    datos.append("texto", document.getElementById("texto_wa").value);
    b.disabled = true;
    try {
      const r = await fetch(location.pathname + "/whatsapp", { method: "POST", body: datos, headers: { "X-CSRF": formulario.querySelector("[name=_csrf]").value } });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "No se pudo abrir WhatsApp.");
      if (ventana) ventana.location = d.enlace; else location.href = d.enlace;
      setTimeout(() => location.reload(), 1500);
    } catch (e) {
      if (ventana) ventana.close();
      alert(e.message);
      b.disabled = false;
    }
  });
})();

(function () {
  const form = document.querySelector("form[data-facturar]");
  if (!form) return;
  const marcas = () => [...form.querySelectorAll(".fact-marca:not(:disabled)")];
  const resumen = document.getElementById("fact-resumen");
  const pesos = n => "$ " + n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const actualizar = () => {
    const sel = marcas().filter(c => c.checked);
    const total = sel.reduce((a, c) => a + parseFloat(c.dataset.importe || 0), 0);
    if (resumen) resumen.textContent = sel.length ? `${sel.length} estudio(s) marcados · ${pesos(total)} sin IVA` : "Marcá los estudios que querés incluir.";
  };
  const todos = form.querySelector("[data-marcar-todos]");
  if (todos) todos.addEventListener("change", () => { marcas().forEach(c => { c.checked = todos.checked; }); actualizar(); });
  form.addEventListener("change", ev => { if (ev.target.classList.contains("fact-marca")) actualizar(); });
  form.addEventListener("submit", ev => {
    if (!marcas().some(c => c.checked)) { ev.preventDefault(); alert("Marcá al menos un estudio para facturar."); }
  });
})();

(function () {
  const form = document.querySelector("form[data-cambiar-vista]");
  if (!form) return;
  const select = form.querySelector("select");
  select.addEventListener("change", () => {
    if (!select.value) return;
    form.action = form.action.replace(/\/usuarios\/\d+\/ver-como$/, "/usuarios/" + select.value + "/ver-como");
    form.submit();
  });
})();

document.querySelectorAll("[data-filtrar-filas]").forEach((entrada) => {
  const tabla = document.querySelector(entrada.dataset.filtrarFilas);
  if (!tabla) return;
  const norma = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  entrada.addEventListener("input", () => {
    const q = norma(entrada.value.trim());
    tabla.querySelectorAll("tr").forEach((fila, i) => {
      if (i === 0) return;
      const texto = norma(fila.textContent + " " + [...fila.querySelectorAll("input[name=codigo]")].map((x) => x.value).join(" "));
      fila.hidden = !!q && !texto.includes(q);
    });
  });
});

(function () {
  document.querySelectorAll("form.form-estudios").forEach((f) => {
    let enviado = false;
    const botones = () => f.querySelectorAll("button:not([type=button])");
    f.addEventListener("submit", (ev) => {
      if (enviado) { ev.preventDefault(); return; }
      enviado = true;
      setTimeout(() => botones().forEach((b) => { b.disabled = true; }));
    });
    window.addEventListener("pageshow", (ev) => { if (ev.persisted) location.reload(); });
    if (!f.dataset.soltar) return;
    window.addEventListener("pagehide", () => {
      if (enviado) return;
      const d = new FormData();
      d.append("_csrf", f.querySelector("[name=_csrf]").value);
      d.append("edicion", f.querySelector("[name=edicion]").value);
      navigator.sendBeacon(f.dataset.soltar, d);
    });
  });
})();

document.querySelectorAll("[data-alternar-anulados]").forEach((b) => {
  b.addEventListener("click", () => {
    const tabla = b.closest(".tarjeta").querySelector("table");
    const ocultas = [...tabla.querySelectorAll(".fila-anulada")];
    const ver = ocultas.some((tr) => tr.hidden);
    ocultas.forEach((tr) => { tr.hidden = !ver; });
    b.textContent = (ver ? "Ocultar anulados (" : "Ver anulados (") + b.dataset.n + ")";
  });
});

document.querySelectorAll("select[data-planes]").forEach((sel) => {
  const formulario = sel.closest("form");
  const cobertura = formulario && formulario.querySelector("select[name=cobertura]");
  if (!cobertura) return;
  const mapa = JSON.parse(sel.dataset.planes || "{}");
  const envoltorio = sel.closest(".campo-plan");
  cobertura.addEventListener("change", () => {
    const planes = mapa[cobertura.value] || [];
    sel.innerHTML = "";
    const vacio = document.createElement("option");
    vacio.value = "";
    vacio.textContent = "—";
    sel.append(vacio);
    planes.forEach((p) => {
      const o = document.createElement("option");
      o.textContent = p;
      sel.append(o);
    });
    if (envoltorio) envoltorio.hidden = !planes.length;
  });
});

(function () {
  const CAMPOS = ["template", "descripcion", "conclusion", "bethesda", "marcadores", "resultado"];
  document.querySelectorAll("form[data-autoguardar]").forEach((form) => {
    const estado = form.querySelector("[data-autoestado]");
    const csrf = form.querySelector("[name=_csrf]").value;
    const serializar = () => {
      const p = new URLSearchParams();
      for (const [k, v] of new FormData(form)) if (typeof v === "string" && CAMPOS.includes(k)) p.append(k, v);
      return p;
    };
    let base = serializar().toString();
    let temporizador = null, enCurso = false, pendiente = false;
    const mostrar = (texto, clase) => { if (estado) { estado.textContent = texto; estado.className = "autoestado" + (clase ? " " + clase : ""); } };
    async function guardar() {
      temporizador = null;
      const cuerpo = serializar();
      if (cuerpo.toString() === base) { mostrar(""); return; }
      if (enCurso) { pendiente = true; return; }
      enCurso = true;
      mostrar("Guardando…");
      cuerpo.set("_csrf", csrf);
      cuerpo.set("autoguardar", "1");
      try {
        const r = await fetch(form.action, { method: "POST", body: cuerpo, headers: { "X-CSRF": csrf, "Accept": "application/json" } });
        const d = await r.json();
        if (!r.ok || !d.ok) throw new Error(d.error || "no se pudo guardar");
        base = serializar().toString();
        mostrar("Guardado automáticamente " + d.hora, "ok");
      } catch (e) {
        mostrar("No se guardó solo: " + (e.message || "sin conexión") + ". Usá Guardar.", "error");
      }
      enCurso = false;
      if (pendiente) { pendiente = false; guardar(); }
    }
    const programar = (ev) => {
      if (!ev.target.name || !CAMPOS.includes(ev.target.name)) return;
      if (serializar().toString() === base) { mostrar(""); return; }
      mostrar("Cambios sin guardar…");
      clearTimeout(temporizador);
      temporizador = setTimeout(guardar, 1500);
    };
    form.addEventListener("input", programar);
    form.addEventListener("change", programar);
    form.addEventListener("submit", () => { clearTimeout(temporizador); base = serializar().toString(); });
    const volcar = () => {
      if (serializar().toString() === base || !navigator.sendBeacon) return;
      const cuerpo = serializar();
      cuerpo.set("_csrf", csrf);
      cuerpo.set("autoguardar", "1");
      navigator.sendBeacon(form.action, cuerpo);
      base = serializar().toString();
    };
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") volcar(); });
    window.addEventListener("pagehide", volcar);
  });
})();

(function () {
  const asunto = document.querySelector("select[data-tarea-asunto]");
  const sector = document.querySelector("select[data-tarea-sector]");
  const resp = document.querySelector("select[data-tarea-responsable]");
  if (!asunto || !sector || !resp) return;
  const opciones = [...resp.options].filter(o => o.value);
  const filtrar = () => {
    opciones.forEach(o => { o.hidden = !!sector.value && !(o.dataset.sectores || "").split(",").includes(sector.value); });
    if (resp.selectedOptions[0] && resp.selectedOptions[0].hidden) resp.value = "";
  };
  sector.addEventListener("change", filtrar);
  asunto.addEventListener("change", () => {
    const o = asunto.selectedOptions[0];
    if (!o || !o.dataset.responsable) return;
    sector.value = "";
    filtrar();
    resp.value = o.dataset.responsable;
  });
})();

(function () {
  const caja = document.querySelector("[data-ordenes-subida]");
  if (!caja) return;
  const entrada = caja.querySelector("[data-archivos]"), zona = caja.querySelector("[data-zona]");
  const lista = caja.querySelector("[data-resultados]"), fin = caja.querySelector("[data-fin]");
  const csrf = caja.dataset.csrf;
  const texto = { qr: "por QR", ocr: "por el número impreso", manual: "a mano", continuacion: "continuación de la hoja anterior" };
  let ocupado = false;
  const fila = (nombre) => {
    const li = document.createElement("li");
    li.innerHTML = '<b></b> <span class="muted">en cola…</span>';
    li.querySelector("b").textContent = nombre;
    lista.append(li);
    return li;
  };
  async function subir(archivo) {
    const li = fila(archivo.name), estado = li.querySelector("span");
    estado.textContent = "leyendo…";
    const datos = new FormData();
    datos.append("archivo", archivo);
    try {
      const r = await fetch(caja.dataset.url, { method: "POST", body: datos, headers: { "X-CSRF": csrf, "Accept": "application/json" } });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.error || "no se pudo subir");
      const bien = d.paginas.filter(p => p.estado === "adjunta"), pend = d.paginas.filter(p => p.estado === "pendiente"), rep = d.paginas.filter(p => p.estado === "repetida");
      const partes = [];
      if (bien.length) partes.push(bien.map(p => p.numero + " (" + (texto[p.metodo] || p.metodo) + ")").join(", "));
      if (pend.length) partes.push(pend.length + " sin identificar");
      if (rep.length) partes.push(rep.length + " ya estaba(n) cargada(s)");
      estado.textContent = "✔ " + partes.join(" · ");
      estado.className = pend.length ? "aviso" : "ok";
    } catch (e) {
      estado.textContent = "✖ " + (e.message || "sin conexión");
      estado.className = "error";
    }
  }
  async function procesar(archivos) {
    if (ocupado) return;
    ocupado = true;
    fin.hidden = true;
    for (const a of archivos) await subir(a);
    ocupado = false;
    fin.hidden = false;
    entrada.value = "";
  }
  entrada.addEventListener("change", () => procesar([...entrada.files]));
  zona.addEventListener("click", e => { if (e.target !== entrada) { e.preventDefault(); entrada.click(); } });
  ["dragover", "dragenter"].forEach(n => zona.addEventListener(n, e => { e.preventDefault(); zona.classList.add("encima"); }));
  ["dragleave", "drop"].forEach(n => zona.addEventListener(n, e => { e.preventDefault(); zona.classList.remove("encima"); }));
  zona.addEventListener("drop", e => procesar([...e.dataTransfer.files]));
})();
