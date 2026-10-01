// Asocia cada etiqueta con el campo que tiene debajo (lectores de pantalla y clic en la etiqueta)
document.querySelectorAll("label:not([for])").forEach((lab, i) => {
  if (lab.querySelector("input, select, textarea")) return;
  const campo = lab.nextElementSibling;
  if (!campo || !/^(INPUT|SELECT|TEXTAREA)$/.test(campo.tagName)) return;
  campo.id = campo.id || `campo_${i}`;
  lab.htmlFor = campo.id;
});

// Bloques de estudio (PAP / BP / CT) en el formulario del protocolo.
// Cascada Subcategoría -> Sitio -> Tipo de muestra con el catálogo de cada tipo (se pide una vez por tipo).
const catalogos = {};
const catalogo = tipo => (catalogos[tipo] = catalogos[tipo] || fetch(`/api/catalogo/${tipo}`).then(r => r.json()));

async function prepararBloque(bloque) {
  const campo = c => bloque.querySelector(`[data-cat="${c}"]`);
  const [sub, sitio, tm] = ["subcategoria", "sitio", "tipo_muestra"].map(campo);
  const arbol = await catalogo(bloque.dataset.tipo);
  // Sin opciones (falta elegir el paso anterior) el campo queda deshabilitado y dice qué elegir primero
  const llenar = (sel, opciones, actual, falta) => {
    sel.disabled = !opciones.length;
    const aviso = opciones.length ? "Seleccionar…" : (falta ? `Elegí ${falta} primero` : "Sin opciones");
    sel.innerHTML = `<option value="" hidden>${aviso}</option>` + opciones.map(o =>
      `<option${o === actual ? " selected" : ""}>${o.replace(/</g, "&lt;")}</option>`).join("");
  };
  const fijo = !sub;                                    // PAP: subcategoría y sitio fijos
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

  // PAP: al elegir el citotécnico, proponer su lote del día (el abierto o uno nuevo con sus iniciales)
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
  const n = siguienteBloque++;                                   // índice único de los campos e-N-
  const html = document.getElementById(`tpl-estudio-${btn.dataset.agregarEstudio}`).innerHTML.replaceAll("__N__", n);
  form.querySelector(".bloques").insertAdjacentHTML("beforeend", html);
  const nuevo = form.querySelector(".bloques").lastElementChild;
  prepararBloque(nuevo);
  nuevo.scrollIntoView({ behavior: "smooth", block: "center" });
}));

// Templates: al elegir uno de la lista, el texto aparece en el campo editable
document.querySelectorAll("select[data-templates]").forEach(sel => {
  const destino = document.getElementById(sel.dataset.destino);
  const concl = sel.dataset.conclusion ? document.getElementById(sel.dataset.conclusion) : null;
  let ultimo = sel.value;
  sel.addEventListener("change", async () => {
    const id = sel.selectedOptions[0] && sel.selectedOptions[0].dataset.id;
    if (!id) { ultimo = sel.value; return; }            // "sin template": no toca el texto
    const t = await (await fetch(`/api/template/${id}`)).json();
    const ocupado = destino.value.trim() || (concl && concl.value.trim());
    if (ocupado && !confirm("Ya hay texto escrito. ¿Reemplazarlo por el del template?")) { sel.value = ultimo; return; }
    destino.value = t.texto || "";
    if (concl) concl.value = t.conclusion || "";
    ultimo = sel.value;
    destino.focus();
  });
});

// Médico solicitante: buscador con la lista del sistema (se carga una vez y el navegador la guarda).
// Busca sin importar acentos ni mayúsculas, y todas las palabras escritas ("abad del" -> "ABAD CANDELA, Delfina").
const sinAcentos = s => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
document.querySelectorAll("input[data-medicos]").forEach(async inp => {
  const nombres = (await (await fetch("/api/medicos")).json()).map(n => [n, sinAcentos(n)]);
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
    const hallados = [...coinciden.filter(([, s]) => s.startsWith(palabras[0])),     // primero los apellidos que empiezan así
                      ...coinciden.filter(([, s]) => !s.startsWith(palabras[0]))].slice(0, 40);
    hallados.forEach(([n]) => {
      const el = document.createElement("div");
      el.textContent = n;
      el.addEventListener("mousedown", e => { e.preventDefault(); elegir(n); });
      caja.append(el);
    });
    if (!hallados.length) caja.innerHTML = '<div class="nada">Sin coincidencias (se guarda lo escrito)</div>';
    caja.hidden = false;
  };
  inp.addEventListener("input", mostrar);
  inp.addEventListener("focus", () => inp.value && mostrar());
  inp.addEventListener("blur", () => { caja.hidden = true; });
  inp.addEventListener("keydown", e => {
    if (caja.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); marcar(activo + (e.key === "ArrowDown" ? 1 : -1)); }
    else if (e.key === "Enter" && activo >= 0 && caja.children[activo].textContent) { e.preventDefault(); elegir(caja.children[activo].textContent); }
    else if (e.key === "Escape") caja.hidden = true;
  });
});

// Confirmaciones
document.querySelectorAll("form[data-confirmar]").forEach(f =>
  f.addEventListener("submit", e => { if (!confirm(f.dataset.confirmar)) e.preventDefault(); }));

// Barra superior: menú desplegable en pantallas angostas, listas desplegables y menú del usuario
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

// Ficha de usuario: muestra qué da el perfil elegido y cómo queda cada permiso con el ajuste del usuario
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
