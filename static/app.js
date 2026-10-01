// Asocia cada etiqueta con el campo que tiene debajo (lectores de pantalla y clic en la etiqueta)
document.querySelectorAll("label:not([for])").forEach((lab, i) => {
  if (lab.querySelector("input, select, textarea")) return;
  const campo = lab.nextElementSibling;
  if (!campo || !/^(INPUT|SELECT|TEXTAREA)$/.test(campo.tagName)) return;
  campo.id = campo.id || `campo_${i}`;
  lab.htmlFor = campo.id;
});

// Cascada Subcategoría -> Sitio -> Tipo de muestra (formulario de ingreso)
(async function cascada() {
  const f = document.querySelector("form[data-tipo]");
  if (!f) return;
  const [sub, sitio, tm] = ["subcategoria", "sitio", "tipo_muestra"].map(n => f.elements[n]);
  const arbol = await (await fetch(`/api/catalogo/${f.dataset.tipo}`)).json();
  const llenar = (sel, opciones, actual) => {
    sel.innerHTML = '<option value=""></option>' + opciones.map(o =>
      `<option${o === actual ? " selected" : ""}>${o.replace(/</g, "&lt;")}</option>`).join("");
  };
  const actualizar = (desde) => {
    if (sub.tagName === "SELECT" && desde === "inicio") llenar(sub, Object.keys(arbol), sub.dataset.actual);
    const sitios = arbol[sub.value] || {};
    if (sitio.tagName === "SELECT" && desde !== "sitio") llenar(sitio, Object.keys(sitios), desde === "inicio" ? sitio.dataset.actual : "");
    llenar(tm, sitios[sitio.value] || [], desde === "inicio" ? tm.dataset.actual : "");
  };
  sub.addEventListener("change", () => actualizar("sub"));
  sitio.addEventListener("change", () => actualizar("sitio"));
  actualizar("inicio");
})();

// Templates: al elegir el título, el texto aparece en el campo editable
document.querySelectorAll("input[data-templates]").forEach(inp => {
  const lista = document.getElementById(inp.getAttribute("list"));
  const destino = document.getElementById(inp.dataset.destino);
  const concl = inp.dataset.conclusion ? document.getElementById(inp.dataset.conclusion) : null;
  let ultimo = inp.value;
  inp.addEventListener("change", async () => {
    const op = [...lista.options].find(o => o.value === inp.value);
    if (!op || inp.value === ultimo) return;
    const t = await (await fetch(`/api/template/${op.dataset.id}`)).json();
    const ocupado = destino.value.trim() || (concl && concl.value.trim());
    if (ocupado && !confirm("Ya hay texto escrito. ¿Reemplazarlo por el del template?")) { inp.value = ultimo; return; }
    destino.value = t.texto || "";
    if (concl) concl.value = t.conclusion || "";
    ultimo = inp.value;
    destino.focus();
  });
});

// Confirmaciones
document.querySelectorAll("form[data-confirmar]").forEach(f =>
  f.addEventListener("submit", e => { if (!confirm(f.dataset.confirmar)) e.preventDefault(); }));

// PAP: al elegir el citotécnico, proponer su lote del día (el abierto o uno nuevo con sus iniciales)
document.querySelectorAll("select[data-lote-cito]").forEach(function (sel) {
  sel.addEventListener("change", function () {
    var lote = sel.form.querySelector("select[name=lote_id]");
    var ini = sel.selectedOptions[0] && sel.selectedOptions[0].dataset.ini;
    if (!lote || !ini || lote.value) return;
    var abierto = lote.querySelector('option[data-tipo="' + ini + '"]');
    var nuevo = lote.querySelector('option[value="nuevo:' + ini + '"]');
    if (abierto || nuevo) lote.value = (abierto || nuevo).value;
  });
});

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
