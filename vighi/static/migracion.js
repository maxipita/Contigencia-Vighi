(() => {
  const formulario = document.getElementById("form-migracion");
  if (!formulario) return;
  const porPedido = parseInt(formulario.dataset.porPedido, 10) || 20;
  const campos = ["usuarios", "ubicaciones", "medicos", "lotes", "coberturas", "sin_firmante"];
  const rotulos = {
    usuarios: "Usuarios que se crearían (solo iniciales)", ubicaciones: "Ubicaciones nuevas", medicos: "Médicos nuevos", lotes: "Lotes nuevos",
    coberturas: "Coberturas que no están en la lista del sistema", sin_firmante: "Médicos firmantes que no se encontraron entre los usuarios",
  };
  const el = id => document.getElementById(id);
  const escapar = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const mostrar = (total, acum) => {
    el("resultado-migracion").hidden = false;
    el("r-importados").textContent = acum.importados;
    el("r-existentes").textContent = acum.existentes;
    el("r-errores").textContent = acum.errores.length;
    let html = "";
    if (acum.errores.length) html += `<h3>Errores</h3><ul>${acum.errores.slice(0, 50).map(e => `<li>${escapar(e)}</li>`).join("")}</ul>`;
    for (const c of campos) {
      const lista = [...acum.nuevos[c]];
      if (lista.length) html += `<h3>${rotulos[c]} (${lista.length})</h3><p class="muted">${lista.slice(0, 200).map(escapar).join(" · ")}${lista.length > 200 ? " …" : ""}</p>`;
    }
    el("r-detalle").innerHTML = html;
  };

  formulario.addEventListener("submit", async ev => {
    ev.preventDefault();
    const archivo = el("archivo-migracion").files[0];
    if (!archivo) return;
    const ensayo = el("ensayo-migracion").checked;
    if (!ensayo && !confirm("Esto escribe en la base de datos real. ¿Cargar los protocolos?")) return;
    const boton = el("boton-migracion");
    boton.disabled = true;
    const estado = el("estado-migracion");
    const barra = el("avance-migracion");
    const lineas = (await archivo.text()).split("\n").filter(l => l.trim());
    const registros = [];
    for (const [i, l] of lineas.entries()) {
      try { registros.push(JSON.parse(l)); } catch (e) { estado.textContent = `La línea ${i + 1} del archivo no es válida.`; boton.disabled = false; return; }
    }
    const acum = { importados: 0, existentes: 0, errores: [], nuevos: Object.fromEntries(campos.map(c => [c, new Set()])) };
    barra.hidden = false;
    barra.max = registros.length;
    barra.value = 0;
    for (let i = 0; i < registros.length; i += porPedido) {
      const trozo = registros.slice(i, i + porPedido);
      let r;
      try {
        r = await fetch("/api/migracion/lote", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF": window.CSRF }, body: JSON.stringify({ registros: trozo, ensayo }) });
      } catch (e) { estado.textContent = "Se cortó la conexión. Volvé a procesar: lo ya cargado se saltea."; boton.disabled = false; return; }
      if (!r.ok) { estado.textContent = `El servidor rechazó el lote ${i / porPedido + 1}: ${(await r.text()).slice(0, 200)}. Volvé a procesar: lo ya cargado se saltea.`; boton.disabled = false; return; }
      const datos = await r.json();
      acum.importados += datos.importados;
      acum.existentes += datos.existentes;
      acum.errores.push(...datos.errores);
      for (const c of campos) (datos.nuevos[c] || []).forEach(x => acum.nuevos[c].add(x));
      barra.value = Math.min(i + porPedido, registros.length);
      estado.textContent = `${barra.value} de ${registros.length} protocolos…`;
      mostrar(registros.length, acum);
    }
    estado.textContent = ensayo ? `Ensayo terminado: ${acum.importados} protocolos se cargarían. No se escribió nada.` : `Listo: ${acum.importados} protocolos cargados.`;
    boton.disabled = false;
  });
})();

(() => {
  const formulario = document.getElementById("form-imagenes");
  if (!formulario) return;
  const el = id => document.getElementById(id);
  const escapar = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  formulario.addEventListener("submit", async ev => {
    ev.preventDefault();
    const archivo = el("archivo-imagenes").files[0];
    if (!archivo) return;
    const ensayo = el("ensayo-imagenes").checked;
    if (!ensayo && !confirm("Esto copia las imágenes a la base y al almacenamiento reales. ¿Seguir?")) return;
    const boton = el("boton-imagenes");
    boton.disabled = true;
    const estado = el("estado-imagenes");
    const barra = el("avance-imagenes");
    const protocolos = (await archivo.text()).split("\n").filter(l => l.trim()).map(l => JSON.parse(l)).filter(r => (r.imagenes || []).length);
    const total = protocolos.reduce((a, r) => a + r.imagenes.length, 0);
    const acum = { importadas: 0, existentes: 0, errores: [] };
    let hechas = 0;
    barra.hidden = false;
    barra.max = total || 1;
    barra.value = 0;
    for (const r of protocolos) {
      let datos = null;
      for (let intento = 0; intento < 3 && !datos; intento++) {
        try {
          const resp = await fetch("/api/migracion/imagenes", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF": window.CSRF }, body: JSON.stringify({ numero: r.numero, imagenes: r.imagenes, ensayo }) });
          if (resp.ok) datos = await resp.json(); else acum.errores.push(`${r.numero}: ${(await resp.text()).slice(0, 120)}`);
          if (!resp.ok) break;
        } catch (e) { await new Promise(f => setTimeout(f, 3000)); }
      }
      if (!datos) { if (!acum.errores.length || !acum.errores[acum.errores.length - 1].startsWith(r.numero)) acum.errores.push(`${r.numero}: sin respuesta`); }
      else { acum.importadas += datos.importadas; acum.existentes += datos.existentes; acum.errores.push(...datos.errores); }
      hechas += r.imagenes.length;
      barra.value = hechas;
      estado.textContent = `${hechas} de ${total} imágenes (${acum.importadas} ${ensayo ? "se copiarían" : "copiadas"}, ${acum.existentes} ya estaban, ${acum.errores.length} con error)…`;
    }
    estado.textContent = `${ensayo ? "Ensayo terminado" : "Listo"}: ${acum.importadas} ${ensayo ? "imágenes se copiarían" : "imágenes copiadas"}, ${acum.existentes} ya estaban, ${acum.errores.length} con error.`;
    el("r-imagenes").innerHTML = acum.errores.length ? `<h3>Errores</h3><ul>${acum.errores.slice(0, 50).map(e => `<li>${escapar(e)}</li>`).join("")}</ul>` : "";
    boton.disabled = false;
  });
})();
