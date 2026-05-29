let selectedreference = null;
let selectedCategoria = null;
let selectedHospitales = [];

// Handles 'Categorica' and 'Categòrica' (DB stores either form)
function isCategorica(tipo) {
  if (!tipo) return false;
  return tipo.replace(/ó/g, 'o').toLowerCase().trim() === 'categorica';
}

// Estado de ordenación por sección
let ordenActual = {
  reference: 'none',
  hospital: 'none'
};
 
// Cache de resultados originales (sin ordenar) para poder restaurar
let cacheVariables = {
  reference: [],
  hospital: []
};

// Cache de elementos del DOM
const elementos = {
  get referenceTable() { return document.querySelector('#referenceTable tbody'); },
  get hospitalTable() { return document.querySelector('#hospitalTable tbody'); },
  get referenceSelectedBadge() { return document.getElementById('referenceSelectedBadge'); },
  get hospitalSelectedBadge() { return document.getElementById('hospitalSelectedBadge'); },
  get btnMapearFinal() { return document.getElementById('btnMapearFinal'); },
  get btnLimpiarreference() { return document.getElementById('btnLimpiarreference'); },
  get btnLimpiarHospital() { return document.getElementById('btnLimpiarHospital'); }
};

// Utilidades para modales y notificaciones
function mostrarToast(titulo, mensaje, tipo = 'success') {
  const toastEl = document.getElementById('toastNotification');
  const toastTitle = document.getElementById('toastTitle');
  const toastBody = document.getElementById('toastBody');
  
  // Limpiar clases previas
  toastEl.classList.remove('toast-success', 'toast-error', 'toast-warning');
  
  // Iconos según el tipo
  const iconos = {
    success: '✅',
    error: '❌',
    warning: '⚠️',
    info: 'ℹ️'
  };
  
  toastTitle.textContent = `${iconos[tipo] || ''} ${titulo}`;
  toastBody.textContent = mensaje;
  toastEl.classList.add(`toast-${tipo}`);
  
  const toast = new bootstrap.Toast(toastEl, { delay: 3000 });
  toast.show();
}

function mostrarConfirmacion(titulo, mensaje, onConfirm) {
  const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
  const modalTitle = document.getElementById('confirmModalTitle');
  const modalBody = document.getElementById('confirmModalBody');
  const confirmBtn = document.getElementById('confirmModalBtn');
  
  modalTitle.textContent = titulo;
  modalBody.textContent = mensaje;
  
  // Limpiar listeners anteriores
  const newConfirmBtn = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
  
  newConfirmBtn.addEventListener('click', () => {
    modal.hide();
    onConfirm();
  });
  
  modal.show();
}

// Funciones auxiliares para crear botones
function crearBotonSeleccionar(variable, type, row) {
  const btn = document.createElement('button');
  btn.className = 'map-btn';
  btn.textContent = 'Seleccionar';
  btn.addEventListener('click', e => {
    e.stopPropagation();
    seleccionarVariable(variable, type, row);
  });
  return btn;
}

function crearBotonDeseleccionar(variable, type, row) {
  const btn = document.createElement('button');
  btn.className = 'unselect-btn';
  btn.textContent = 'Deseleccionar';
  btn.addEventListener('click', e => {
    e.stopPropagation();
    deseleccionarVariable(variable, type, row);
  });
  return btn;
}

function crearBotonCategorias(variable, type, row) {
  const btn = document.createElement('button');
  btn.className = 'map-cat-btn';
  btn.textContent = 'Seleccionar totes les categories';
  btn.addEventListener('click', e => {
    e.stopPropagation();
    seleccionarCategorias(variable, type, row);
  });
  return btn;
}

function crearBotonDismiss(variable, type) {
  const btn = document.createElement('button');
  btn.className = 'dismiss-row-btn';
  btn.title = 'Eliminar de la cerca';
  btn.innerHTML = '<i class="fa fa-times"></i>';
  btn.addEventListener('click', e => {
    e.stopPropagation();
    eliminarDeResultados(variable, type);
  });
  return btn;
}

function eliminarDeResultados(variable, type) {
  if (type === 'reference') {
    cacheVariables.reference = cacheVariables.reference.filter(v => v.id !== variable.id);
    if (selectedreference && selectedreference.id === variable.id) {
      selectedreference = null;
      elementos.referenceSelectedBadge.style.display = 'none';
      elementos.btnLimpiarreference.style.display = 'none';
      actualizarBotonMapeo();
    }
  } else {
    cacheVariables.hospital = cacheVariables.hospital.filter(
      v => !(v.variableid === variable.variableid && v.value === variable.value && v.tabla_origen === variable.tabla_origen)
    );
    const wasSelected = selectedHospitales.some(
      h => h.variableid === variable.variableid && h.value === variable.value && h.tabla_origen === variable.tabla_origen
    );
    if (wasSelected) {
      selectedHospitales = selectedHospitales.filter(
        h => !(h.variableid === variable.variableid && h.value === variable.value && h.tabla_origen === variable.tabla_origen)
      );
      actualizarBadgeHospitales();
      actualizarBotonMapeo();
    }
  }

  renderizarTabla(type, cacheVariables[type]);

  const containerId = type === 'hospital' ? 'hospitalTableContainer' : 'referenceTableContainer';
  const noResultsId = type === 'hospital' ? 'hospitalNoResults' : 'referenceNoResults';
  if (cacheVariables[type].length === 0) {
    document.getElementById(containerId).style.display = 'none';
    const noResults = document.getElementById(noResultsId);
    if (noResults) noResults.style.display = 'flex';
  }
}

// Auto-load category dropdowns on page load (sections start expanded)
document.addEventListener('DOMContentLoaded', async () => {
  await Promise.all([cargarCategorias('reference'), cargarCategorias('hospital')]);

  const params = new URLSearchParams(window.location.search);
  const refId = params.get('ref_id');
  
  if (refId) {
    try {
      // ⚠️ ATENCIÓN: Asegúrate de que esta URL sea exactamente la misma
      // que te devolvió el JSON blanco en tus pruebas anteriores.
      // Podría ser `/variables/reference/${refId}` o `/map_var/variables/reference/${refId}`
      const res = await fetch(`/map_var/variables/reference/${refId}`); 
      
      if (res.ok) {
        const refVar = await res.json();
        
        // 1. Guardamos la variable en el estado
        selectedreference = { ...refVar, rowRef: null };
        
        // 2. Actualizamos el Badge (Etiqueta superior)
        elementos.referenceSelectedBadge.textContent = `✓ ${refVar.nombre}`;
        elementos.referenceSelectedBadge.style.display = 'inline-block';
        elementos.btnLimpiarreference.style.display = 'inline-block';
        actualizarBotonMapeo();

        // 3. MAGIA VISUAL: Escribimos el nombre en el buscador y buscamos
        const searchInput = document.getElementById('referenceSearch');
        if (searchInput) {
            searchInput.value = refVar.nombre; // Rellenamos el buscador
            await buscarVariables('reference', 'NO'); // Disparamos la búsqueda
            
            // 4. Capturamos la fila (<tr>) que se acaba de pintar para no romper tu lógica
            const tableBody = document.querySelector('#referenceTable tbody');
            const filaSeleccionada = tableBody.querySelector('.selected-row');
            if (filaSeleccionada) {
                selectedreference.rowRef = filaSeleccionada;
            }
        }
        
        // 5. (Opcional) Ponemos el cursor en el buscador del Hospital para agilizar el trabajo
        const hospitalSearch = document.getElementById('hospitalSearch');
        if (hospitalSearch) {
            hospitalSearch.focus();
        }
      }
    } catch (e) {
      console.error('Error precargando variable de referencia:', e);
      mostrarToast('Error', 'No s\'ha pogut precarregar la variable de referència', 'error');
    }
  } else {
    // Si no entra por URL, hacemos una búsqueda inicial vacía si quieres
    // buscarVariables('reference', 'NO');
  }
});

// Mostrar/ocultar secciones
document.querySelectorAll('.section-button').forEach(btn => {
  btn.addEventListener('click', async () => {
    // this.classList.toggle('active');
    const content = btn.nextElementSibling;
    const type = btn.textContent.includes("REFERÈNCIA") ? "reference" : "hospital";
    if (content.style.display !== 'block') {
      await cargarCategorias(type);
    }
    content.style.display = content.style.display === 'block' ? 'none' : 'block';
  });
});

async function cargarCategorias(type) {
  const endpoint = `/map_var/variables/categorias/${type}`;
  const res = await fetch(endpoint);
  const data = await res.json();
  const select = document.getElementById(`${type}Tipo`);
  select.innerHTML = `<option value="">Totes les procedències</option>`;
  data.categorias.forEach(cat => {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = cat;
    select.appendChild(opt);
  });
}

async function fetchVariables(type, filtros) {
  const endpoint = type === 'reference' ? '/map_var/variables/reference' : '/map_var/variables/hospital';

  const params = new URLSearchParams(filtros).toString();
  const res = await fetch(`${endpoint}?${params}`);
  return await res.json();
}

function ordenarVariables(variables, criterio) {
  if (criterio === 'none') return [...variables];
 
  return [...variables].sort((a, b) => {
    if (criterio === 'last_value') {
      // Mas reciente primero; nulls al final
      const da = a.last_value ? new Date(a.last_value) : null;
      const db = b.last_value ? new Date(b.last_value) : null;
      if (!da && !db) return 0;
      if (!da) return 1;
      if (!db) return -1;
      return db - da;
    }
 
    if (criterio === 'porc_pats') {
      // Mayor porcentaje primero; nulls al final
      const pa = a.porc_pats ?? null;
      const pb = b.porc_pats ?? null;
      if (pa === null && pb === null) return 0;
      if (pa === null) return 1;
      if (pb === null) return -1;
      return pb - pa;
    }
 
    return 0;
  });
}

function cambiarOrden(type, criterio, elementoActivo) {
  // 1. Guardamos el criterio de ordenación
  ordenActual[type] = criterio;
  
  // 2. Gestionamos el aspecto visual SOLO si el elemento clicado es un botón
  // Si es un <select>, ignoramos este paso porque ya muestra el valor activo por defecto
  if (elementoActivo && elementoActivo.tagName === 'BUTTON') {
    document.querySelectorAll(`.btn-sort[data-type="${type}"]`).forEach(b => {
      b.classList.toggle('active', b === elementoActivo);
    });
  }
  
  // 3. Renderizamos la tabla con el nuevo orden
  if (cacheVariables[type] && cacheVariables[type].length > 0) {
    renderizarTabla(type, cacheVariables[type]);
  }
}

async function buscarVariables(type, exacta) {
  const tipo = document.getElementById(`${type}Tipo`).value;
  const search = document.getElementById(`${type}Search`).value;
  const tableBody = type === 'reference' ? elementos.referenceTable : elementos.hospitalTable;
  tableBody.innerHTML = "<tr><td colspan='2'>Carregant...</td></tr>";
 
  const variables = await fetchVariables(type, { tipo, search, exacta });
 
  // Guardar en cache (orden original del servidor)
  cacheVariables[type] = variables;
 
  renderizarTabla(type, variables);
 
  const containerId = type === 'hospital' ? 'hospitalTableContainer' : 'referenceTableContainer';
  const noResultsId = type === 'hospital' ? 'hospitalNoResults' : 'referenceNoResults';
  const hintId = type === 'hospital' ? 'hospitalHint' : 'referenceHint';

  const hint = document.getElementById(hintId);
  const noResults = document.getElementById(noResultsId);
  if (hint) hint.style.display = 'none';

  if (variables.length === 0) {
    document.getElementById(containerId).style.display = 'none';
    if (noResults) noResults.style.display = 'flex';
  } else {
    document.getElementById(containerId).style.display = 'block';
    if (noResults) noResults.style.display = 'none';
  }

  if (type === 'hospital') {
    actualizarBadgeHospitales();
  }
}
 
// Renderiza la tabla aplicando el orden activo. Es el unico punto que toca el DOM de la tabla.
function renderizarTabla(type, variables) {
  const tableBody = type === 'reference' ? elementos.referenceTable : elementos.hospitalTable;
  tableBody.innerHTML = "";
 
  const variablesOrdenadas = ordenarVariables(variables, ordenActual[type]);
 
  // Sincronizamos estadoModal para que la navegacion siga funcionando con el orden actual
  estadoModal.lista = variablesOrdenadas;
  estadoModal.tipo = type;
 
  variablesOrdenadas.forEach((v, index) => {
    const tr = document.createElement("tr");
    tr.classList.add("variable-row");
 
    let nombreContent = `<div>${v.nombre}`;
    if (v.mapeada) {
      tr.classList.add("mapped-row");
      nombreContent += `<span class="mapped-badge">Mapeada</span>`;
      nombreContent += `<div class="mapped-info"> ${type === 'hospital' ? (v.snomed_name || 'Variable snomed') : (v.hospital_name || 'Variable Hospital')}</div>`;
    }
    nombreContent += `</div>`;
 
    let yaSeleccionada = false;
    if (type === 'hospital') {
      yaSeleccionada = selectedHospitales.some(h => (h.variableid === v.variableid) && (h.value === v.value) && (h.tabla_origen === v.tabla_origen));
    } else {
      yaSeleccionada = selectedreference && selectedreference.id === v.id;
    }
 
    if (v.mapeada) {
      tr.classList.add("mapped-row");
      const tdNombreMapeada = document.createElement("td");
      tdNombreMapeada.innerHTML = nombreContent;
      const tdAccionesMapeada = document.createElement("td");
      const desmapBtn = document.createElement('button');
      desmapBtn.className = 'desmap-btn';
      desmapBtn.textContent = 'Desmapejar';
      desmapBtn.addEventListener('click', e => { e.stopPropagation(); desmapearVariable(v, type, tr); });
      tdAccionesMapeada.appendChild(desmapBtn);
      tdAccionesMapeada.appendChild(crearBotonDismiss(v, type));
      tr.appendChild(tdNombreMapeada);
      tr.appendChild(tdAccionesMapeada);

    } else if (yaSeleccionada) {
      tr.classList.add("selected-row");
      const tdNombre = document.createElement("td");
      tdNombre.innerHTML = nombreContent;
      const tdAcciones = document.createElement("td");
      tdAcciones.appendChild(crearBotonDeseleccionar(v, type, tr));
      tdAcciones.appendChild(crearBotonDismiss(v, type));
      tr.appendChild(tdNombre);
      tr.appendChild(tdAcciones);

    } else {
      const tdNombre = document.createElement("td");
      tdNombre.innerHTML = nombreContent;

      const tdAcciones = document.createElement("td");
      tdAcciones.appendChild(crearBotonSeleccionar(v, type, tr));

      if (isCategorica(v.tipo) && type === 'hospital') {
        tdAcciones.appendChild(crearBotonCategorias(v, type, tr));
      }

      tdAcciones.appendChild(crearBotonDismiss(v, type));
      tr.appendChild(tdNombre);
      tr.appendChild(tdAcciones);
    }
 
    tr.addEventListener("click", () => mostrarDetallesModal(v, type, variablesOrdenadas, index));
 
    tableBody.appendChild(tr);
  });
}

function seleccionarVariable(v, type, row) {
  if (type === 'reference') {
    // Si ya hay una reference seleccionada y es la misma → no hacer nada
    if (selectedreference && selectedreference.id === v.id) return;

    // Si ya hay otra reference seleccionada → restaurar su fila original
    if (selectedreference && selectedreference.rowRef && selectedreference.rowRef !== row) {
      const prev = selectedreference;
      const prevRow = prev.rowRef;
      prevRow.classList.remove('selected-row');
      prevRow.textContent = '';

      const tdNombrePrev = document.createElement('td');
      tdNombrePrev.textContent = prev.nombre;

      const tdAccionesPrev = document.createElement('td');
      tdAccionesPrev.appendChild(crearBotonSeleccionar(prev, 'reference', prevRow));

      prevRow.appendChild(tdNombrePrev);
      prevRow.appendChild(tdAccionesPrev);
      
      // Restaurar evento de detalles
      prevRow.addEventListener('click', () => mostrarDetallesModal(v, type));
    }

    // Actualizar reference seleccionada
    selectedreference = { ...v, rowRef: row };

    // Actualizar badge y botón limpiar
    elementos.referenceSelectedBadge.textContent = `✓ ${v.nombre}`;
    elementos.referenceSelectedBadge.style.display = 'inline-block';
    elementos.btnLimpiarreference.style.display = 'inline-block';
  }

  // Si es hospital, solo evitar duplicados
  if (type === 'hospital') {
    const yaSeleccionada = selectedHospitales.some(
      h => h.variableid === v.variableid && h.value === v.value && h.tabla_origen === v.tabla_origen
    );
    if (yaSeleccionada) return;

    selectedHospitales.push({ ...v });
    actualizarBadgeHospitales();
  }

  // Limpiar fila y reconstruirla como seleccionada
  row.textContent = '';
  row.classList.add('selected-row');

  const tdNombre = document.createElement('td');
  tdNombre.textContent = v.nombre;

  const tdAcciones = document.createElement('td');
  tdAcciones.appendChild(crearBotonDeseleccionar(v, type, row));
  tdAcciones.appendChild(crearBotonDismiss(v, type));

  row.appendChild(tdNombre);
  row.appendChild(tdAcciones);

  actualizarBotonMapeo();
}

async function seleccionarCategorias(v, type, row) { 
  // Deshabilitar botón y mostrar feedback
  const btnCat = row.querySelector('.map-cat-btn');
  if (btnCat) {
    btnCat.disabled = true;
    btnCat.textContent = 'Carregant...';
  }

  try { 
    const response = await fetch(`/map_var/variables/hospital/${v.variableid}?tabla=${v.tabla_origen}`);
    if (!response.ok) throw new Error("Error al obtener categorías"); 
    
    const categorias = await response.json();
    
    // Validar que hay categorías
    if (!categorias || categorias.length === 0) {
      alert('No s\'han trobat categories per a aquesta variable');
      return;
    }
    
    // Añadir todas las categorías que no estén ya seleccionadas 
    categorias.forEach(item => { 
      const yaSeleccionada = selectedHospitales.some(
        h => h.variableid === item.variableid && h.value === item.value && h.tabla_origen === item.tabla_origen
      ); 
      if (!yaSeleccionada && !item.mapeada) { 
        selectedHospitales.push({ ...item }); 
      } 
    }); 
    
    actualizarBadgeHospitales(); 
    actualizarBotonMapeo(); 
    
    // Recargar la búsqueda para reflejar los cambios
    buscarVariables('hospital');  
  } catch (error) { 
    console.error("Error en seleccionarCategorias:", error);
    alert('Error en carregar les categories. Torna-ho a intentar.');
  } finally {
    // Restaurar botón si todavía existe
    if (btnCat && !btnCat.disabled) {
      btnCat.disabled = false;
      btnCat.textContent = 'Seleccionar totes les categories';
    }
  }
}

function deseleccionarVariable(v, type, row) {
  // Limpiar contenido previo de la fila
  row.textContent = '';
  row.classList.remove('selected-row');

  const tdNombre = document.createElement('td');
  tdNombre.textContent = v.nombre;

  const tdAcciones = document.createElement('td');
  tdAcciones.appendChild(crearBotonSeleccionar(v, type, row));

  if (type === 'hospital') {
    // Eliminar de seleccionados
    selectedHospitales = selectedHospitales.filter(
      h => !(h.variableid === v.variableid && h.value === v.value)
    );
    actualizarBadgeHospitales();

    // Si es Categòrica, añadir botón adicional
    if (isCategorica(v.tipo)) {
      tdAcciones.appendChild(crearBotonCategorias(v, type, row));
    }

  } else if (type === 'reference') {
    selectedreference = null;
    elementos.referenceSelectedBadge.style.display = 'none';
    elementos.btnLimpiarreference.style.display = 'none';
  }

  tdAcciones.appendChild(crearBotonDismiss(v, type));
  row.appendChild(tdNombre);
  row.appendChild(tdAcciones);
  actualizarBotonMapeo();
}

function limpiarSeleccion(type) {
  if (type === 'reference') {
    selectedreference = null;
    elementos.referenceSelectedBadge.style.display = 'none';
    elementos.btnLimpiarreference.style.display = 'none';
    buscarVariables('reference');
  } else {
    selectedHospitales = [];
    actualizarBadgeHospitales();
    buscarVariables('hospital');
  }
  
  actualizarBotonMapeo();
}

function actualizarBadgeHospitales() {
  const badge = elementos.hospitalSelectedBadge;
  const btnLimpiar = elementos.btnLimpiarHospital;
  
  if (selectedHospitales.length === 0) {
    badge.style.display = 'none';
    btnLimpiar.style.display = 'none';
  } else {
    // Limitar longitud del badge si hay muchas variables
    if (selectedHospitales.length > 10) {
      const nombres = selectedHospitales.slice(0, 10).map(h => h.nombre).join(', ');
      badge.textContent = `✓ ${nombres}... (+${selectedHospitales.length - 10})`;
    } else {
      const nombres = selectedHospitales.map(h => h.nombre).join(', ');
      badge.textContent = `✓ ${nombres}`;
    }
    badge.style.display = 'inline-block';
    btnLimpiar.style.display = 'inline-block';
  }
}

function actualizarBotonMapeo() {
  // Habilitar si hay al menos una variable reference Y al menos una variable hospital seleccionada
  if (selectedreference && selectedHospitales.length > 0) {
    elementos.btnMapearFinal.disabled = false;
  } else {
    elementos.btnMapearFinal.disabled = true;
  }
}

async function realizarMapeo() {
  if (!selectedreference || selectedHospitales.length === 0) {
    mostrarToast('Selecció incompleta', 'Has de seleccionar una variable de cada tipus', 'warning');
    return;
  }
  
  mostrarConfirmacion(
    'Confirmar mapeig?',
    `Es mapejarà "${selectedreference.nombre}" amb ${selectedHospitales.length} variable(s) del centre.`,
    async () => {
      const btnMapear = elementos.btnMapearFinal;
      btnMapear.disabled = true;
      btnMapear.textContent = 'Mapeant...';

      try {
        await crearMapeo(selectedreference, selectedHospitales);
        mostrarToast('Èxit', 'Mapeig realitzat correctament', 'success');

        limpiarSeleccion('reference');
        limpiarSeleccion('hospital');
      } catch (error) {
        console.error('Error al mapeig:', error);
        mostrarToast('Error', 'No s\'ha pogut completar el mapeig', 'error');
      } finally {
        btnMapear.textContent = 'Mapejar variables';
        actualizarBotonMapeo();
      }
    }
  );
}

// 1. Estado global para la navegación del modal
let estadoModal = {
    lista: [],
    indiceActual: 0,
    tipo: ''
};

// 2. Función principal (Refactorizada)
// Ahora acepta opcionalmente la lista completa y el índice
function mostrarDetallesModal(variable, type, variables = [], index = -1) {
    console.log("Abriendo modal...");
    console.log("Longitud lista:", variables ? variables.length : "Undefined");
    console.log("Índice:", index);
    
    // Guardamos el contexto para la navegación
    if (variables.length > 0 && index !== -1) {
        estadoModal.lista = variables;
        estadoModal.indiceActual = index;
        estadoModal.tipo = type;
        
        // Mostrar/Ocultar botones de navegación según corresponda
        actualizarBotonesNavegacion();
    } else {
        // Si no se pasa lista (modo legacy), ocultamos las flechas
        document.getElementById('btnPrevVar').style.display = 'none';
        document.getElementById('btnNextVar').style.display = 'none';
    }

    renderizarContenidoModal(variable, type);

    // Solo inicializamos y mostramos el modal si NO está ya visible
    // Esto evita parpadeos al navegar
    const modalEl = document.getElementById('detallesModal');
    const isVisible = modalEl.classList.contains('show');
    
    if (!isVisible) {
        const myModal = new bootstrap.Modal(modalEl);
        myModal.show();
    }
}

function esVariableSeleccionada(variable, type) {
    if (type === 'reference') {
        // Verifica si existe selectedreference y si coincide el ID
        return (typeof selectedreference !== 'undefined' && selectedreference && selectedreference.id === variable.id);
    } else if (type === 'hospital') {
        // Verifica si está en el array de hospitales
        if (typeof selectedHospitales === 'undefined') return false;
        return selectedHospitales.some(h => 
            h.variableid === variable.variableid && 
            h.value === variable.value && 
            h.tabla_origen === variable.tabla_origen
        );
    }
    return false;
}

function actualizarEstiloBotonModal() {
    const btn = document.getElementById('btnSelectFromModal');
    const { lista, indiceActual, tipo } = estadoModal;
    const variable = lista[indiceActual];
    
    if (!variable || !btn) return;

    const estaSeleccionada = esVariableSeleccionada(variable, tipo);

    if (estaSeleccionada) {
        // ESTADO: YA SELECCIONADA -> MOSTRAR ROJO (Deseleccionar)
        btn.textContent = "✖ Deseleccionar";
        btn.className = "btn-unselect-modal"; // Rojo
    } else {
        // ESTADO: NO SELECCIONADA -> MOSTRAR VERDE (Seleccionar)
        btn.textContent = "✔ Seleccionar";
        btn.className = "btn-select-modal"; // Verde
    }
}

// 3. Lógica de renderizado (Extraída de tu función original)
function renderizarContenidoModal(variable, type) {
    const modalContent = document.getElementById("modalDetallesContent");
    const modalTitle = document.getElementById("modalLabel");

    modalContent.innerHTML = "";

    if (type === 'hospital') {
        modalTitle.innerHTML = `Detalls: <span class="text-primary">${variable.description || variable.nombre || 'Variable'}</span>`;
    } else {
        modalTitle.innerHTML = `Detalls: <span class="text-primary">${variable.nombre || variable.variable || 'Variable'}</span>`;
    }

    let html = "";
    const addItem = (label, value) => {
        if (value !== null && value !== undefined && value !== "") {
            return `
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <span class="fw-bold text-secondary">${label}</span>
                    <span class="text-dark">${value}</span>
                </li>`;
        }
        return "";
    };

    // Tu lógica original de campos...
    if (type === 'hospital') {
        html += addItem("ID Variable", variable.variableid);
        html += addItem("Valor categòric", variable.value !== -99 ? variable.value : null);
        html += addItem("Clau", variable.clave);
        html += addItem("Tipus", variable.tipo_variable || variable.tipo);
        html += addItem("Procedència", variable.origen_variable || variable.origen);
        html += addItem("Nº Registres", variable.count);
        html += addItem("Últim registre", variable.last_value);
        html += addItem("Q1", variable.q1);
        html += addItem("Q2 (Mediana)", variable.q2);
        html += addItem("Q3", variable.q3);
        html += addItem("% Pacients", variable.porc_pats ? `${variable.porc_pats}%` : null);
        html += addItem("Cadència", variable.cadencia);
        html += addItem("Codi ICD", variable.codigo);
        html += addItem("Taula origen", variable.tabla_origen);
    } else {
        html += addItem("SNOMED ID", variable.snomed_id);
        html += addItem("Categoria general", variable.categoria_socmic);
        html += addItem("Descripció", variable.descripcion);
        html += addItem("Tipus de dada", variable.tipo_var);
        html += addItem("Unitat", variable.unidad);
        html += addItem("Categoria openEHR", variable.categoria_openEHR);
        html += addItem("Codi ICD", variable.icd);
    }

    modalContent.innerHTML = html;
    actualizarEstiloBotonModal();
}

function clickSeleccionarDesdeModal() {
    const { lista, indiceActual, tipo } = estadoModal;
    const variable = lista[indiceActual];

    // 1. Buscamos la fila en la tabla (como hicimos antes)
    const tableId = tipo === 'reference' ? 'referenceTable' : 'hospitalTable';
    const tbody = document.querySelector(`#${tableId} tbody`);

    if (tbody && tbody.children[indiceActual]) {
        const row = tbody.children[indiceActual];
        
        // TRUCO INTELIGENTE:
        // En lugar de duplicar la lógica de "seleccionar" y "deseleccionar" aquí,
        // buscamos el botón dentro de la fila de la tabla y le hacemos click programáticamente.
        // Así reutilizamos tu lógica de tabla (que ya sabe crear botones, poner badges, etc).
        
        const botonEnTabla = row.querySelector('button'); // Busca el primer botón en la fila
        
        if (botonEnTabla) {
            // Simulamos el click en la tabla
            botonEnTabla.click();
            
            // Actualizamos el botón del modal inmediatamente para reflejar el cambio
            // (Verde -> Rojo o Rojo -> Verde)
            actualizarEstiloBotonModal();
            
            console.log("Acción realizada sin cerrar el modal.");
        } else {
            console.error("No se encontró botón de acción en la fila de la tabla.");
        }

    } else {
        alert("Error de sincronització amb la taula.");
    }
    
    // NOTA: Hemos quitado el modalInstance.hide() para que no se cierre.
}

// 4. Nueva función para manejar los clics en Anterior/Siguiente
function navegarModal(direccion) {
    const nuevoIndice = estadoModal.indiceActual + direccion;
    
    // Validar límites
    if (nuevoIndice >= 0 && nuevoIndice < estadoModal.lista.length) {
        estadoModal.indiceActual = nuevoIndice;
        const nuevaVariable = estadoModal.lista[nuevoIndice];
        
        // Renderizamos la nueva info sin cerrar el modal
        renderizarContenidoModal(nuevaVariable, estadoModal.tipo);
        
        // Actualizamos estado de los botones (habilitar/deshabilitar)
        actualizarBotonesNavegacion();
    }
}

// 5. Helper para UI de botones
function actualizarBotonesNavegacion() {
    const btnPrev = document.getElementById('btnPrevVar');
    const btnNext = document.getElementById('btnNextVar');
    
    // Asegurar que sean visibles
    btnPrev.style.display = 'inline-block';
    btnNext.style.display = 'inline-block';

    // Deshabilitar si es el principio o el final
    btnPrev.disabled = estadoModal.indiceActual === 0;
    btnNext.disabled = estadoModal.indiceActual === estadoModal.lista.length - 1;
}

async function crearMapeo(reference_var, hospital_vars) {
  const payload = { reference_var, hospital_vars };
  const resp = await fetch('/map_var/mapear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!resp.ok) {
    const err = await resp.json();
    throw new Error(err.error || resp.statusText);
  }
  const data = await resp.json();
  console.log("Mapeig creat:", data);
  return data;
}

async function desmapearVariable(v, type, row) {
  mostrarConfirmacion(
    'Eliminar mapeig?',
    `S'eliminarà el mapeig de "${v.nombre}".`,
    async () => {
      const payload = { v, type };

      try {
        const resp = await fetch('/map_var/desmapear', {
          method: "DELETE",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
        mostrarToast('Èxit', 'Mapeig eliminat correctament', 'success');
        limpiarSeleccion('reference');
        limpiarSeleccion('hospital');
      } catch (error) {
        console.error('Error en desmapeig:', error);
        mostrarToast('Error', 'No s\'ha pogut eliminar el mapeig', 'error');
      }
    }
  );
}