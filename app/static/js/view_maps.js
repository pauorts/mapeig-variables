// ════════════════════════════════════════════════════════════════════════════
// view_maps.js — Dashboard Cobertura de Mapeos
// ════════════════════════════════════════════════════════════════════════════

// ── State ─────────────────────────────────────────────────────────────────────
const STATE = {
  currentGrup:  null,
  searchQuery:  '',
  mappedFilter: '',       // '', 'true', 'false'
  selectedIds:  new Set(),
  debounce:     null,
  categories:   [],
  globalStats:  null,
};

const varDataMap = new Map();   // ref_id → full var object for modal

const $ = id => document.getElementById(id);

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);

async function init() {
  try {
    const data = await apiFetch('/mapeos/api/stats');
    STATE.globalStats = data.stats;
    STATE.categories  = data.categories || [];
    renderProgress(data.stats);
    renderStatCards(data.stats);
    renderCategoryPills(data.categories || []);
    showCategoryGrid(data.categories || []);
  } catch (e) {
    console.error('Init error:', e);
    showState('empty', 'Error carregant el dashboard.');
  }
}

// ── API ───────────────────────────────────────────────────────────────────────
async function apiFetch(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function loadVars() {
  showState('loading');
  try {
    const params = new URLSearchParams();
    if (STATE.currentGrup)  params.set('grupo', STATE.currentGrup);
    if (STATE.searchQuery)  params.set('q', STATE.searchQuery);
    if (STATE.mappedFilter) params.set('mapped', STATE.mappedFilter);
    const qs = params.toString();
    const data = await apiFetch('/mapeos/api/vars' + (qs ? '?' + qs : ''));
    renderVarsList(data.vars || []);
  } catch (e) {
    console.error('loadVars error:', e);
    showState('empty', 'Error carregant les variables. Torna-ho a intentar.');
  }
}

async function refreshStats() {
  try {
    const params = new URLSearchParams();
    if (STATE.currentGrup) params.set('grupo', STATE.currentGrup);
    const data = await apiFetch('/mapeos/api/stats' + (params.toString() ? '?' + params : ''));
    renderProgress(data.stats);
    renderStatCards(data.stats);
  } catch (e) {
    console.error('refreshStats error:', e);
  }
}

// ── Category grid (initial state) ─────────────────────────────────────────────
function showCategoryGrid(categories) {
  if (!categories.length) {
    showState('empty', 'No hi ha categories disponibles.');
    return;
  }
  const grid = $('catGrid');
  grid.innerHTML = '';
  categories.forEach(cat => grid.appendChild(makeCatCard(cat)));
  showState('cats');
}

function makeCatCard(cat) {
  const pct = cat.percentage;
  const colorCls = pct >= 75 ? 'vm-pf--high' : pct >= 40 ? 'vm-pf--mid' : 'vm-pf--low';
  const pctCls   = pct >= 75 ? 'hi'         : pct >= 40 ? 'mid'         : 'lo';

  const div = document.createElement('div');
  div.className = 'vm-cat-card';
  div.innerHTML = `
    <div class="vm-cc-top">
      <span class="vm-cc-name">${esc(cat.tipo)}</span>
      <span class="vm-cc-pct vm-cc-pct--${pctCls}">${pct}%</span>
    </div>
    <div class="vm-cc-track">
      <div class="vm-cc-fill ${colorCls}" style="width:${pct}%"></div>
    </div>
    <div class="vm-cc-bottom">
      <span class="vm-cc-count">${cat.mapped} / ${cat.total} variables</span>
      ${cat.unmapped > 0
        ? `<span class="vm-cc-miss">${cat.unmapped} sense mapejar</span>`
        : `<span class="vm-cc-full">✓ Complet</span>`}
    </div>
  `;
  div.addEventListener('click', () => {
    activatePill(cat.tipo);
    switchToList(cat.tipo);
  });
  return div;
}

// ── Category pills ────────────────────────────────────────────────────────────
function renderCategoryPills(categories) {
  const c = $('categoryFilters');
  c.innerHTML = '';

  const allPill = makePill('Tots', null);
  allPill.classList.add('active');
  c.appendChild(allPill);

  categories.forEach(cat => c.appendChild(makePill(cat.tipo, cat.tipo)));
}

function makePill(label, grup) {
  const btn = document.createElement('button');
  btn.className = 'vm-cat-pill';
  btn.dataset.grup = grup || '';
  btn.textContent = label;
  btn.addEventListener('click', () => onPillClick(grup, btn));
  return btn;
}

function activatePill(grup) {
  document.querySelectorAll('.vm-cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.grup === (grup || ''));
  });
}

function onPillClick(grup, btn) {
  activatePill(grup);
  if (!grup && !STATE.searchQuery) {
    // Back to overview
    STATE.currentGrup  = null;
    STATE.mappedFilter = '';
    renderProgress(STATE.globalStats);
    renderStatCards(STATE.globalStats);
    showMappedFilter(false);
    showCategoryGrid(STATE.categories);
  } else {
    switchToList(grup);
  }
}

function switchToList(grup) {
  STATE.currentGrup = grup;
  showMappedFilter(true);
  refreshStats();
  loadVars();
}

// ── Render: progress + stats ──────────────────────────────────────────────────
function renderProgress(stats) {
  const pct  = stats.percentage;
  const fill = $('progressFill');
  fill.style.width = pct + '%';
  fill.className = 'vm-progress-fill ' + progressColorClass(pct);
  $('progressPct').textContent   = pct + '%';
  $('progressLabel').textContent = `${stats.mapped} de ${stats.total} variables mapejades`;
  $('progressCaption').textContent =
    stats.unmapped > 0
      ? `Queden ${stats.unmapped} variables sense mapejar`
      : stats.total > 0 ? '✓ Cobertura completa!' : '';
}

function renderStatCards(stats) {
  $('statTotal').textContent   = stats.total;
  $('statMapped').textContent  = stats.mapped;
  $('statUnmapped').textContent = stats.unmapped;
}

function progressColorClass(pct) {
  if (pct >= 75) return 'vm-pf--high';
  if (pct >= 40) return 'vm-pf--mid';
  return 'vm-pf--low';
}

// ── Render: variable list ─────────────────────────────────────────────────────
function renderVarsList(vars) {
  if (!vars.length) {
    showState('empty', 'No s\'han trobat variables per als filtres aplicats.');
    return;
  }

  varDataMap.clear();
  vars.forEach(v => varDataMap.set(v.id, v));

  const mapped   = vars.filter(v => v.is_mapped).length;
  const unmapped = vars.length - mapped;

  $('listHeader').innerHTML = `
    <div class="vm-lh-left">
      <span class="vm-lh-count">${vars.length} variables</span>
      <span class="vm-chip vm-chip--ok"><i class="fa fa-check"></i> ${mapped}</span>
      <span class="vm-chip vm-chip--ko"><i class="fa fa-times"></i> ${unmapped}</span>
    </div>
    <label class="vm-sel-all">
      <input type="checkbox" id="selAllChk" onchange="onSelectAll(this.checked)">
      Sel. tot
    </label>
  `;

  const list = $('varsList');
  list.innerHTML = '';
  vars.forEach(v => list.appendChild(makeVarRow(v)));

  showState('list');
}

function makeVarRow(v) {
  const row = document.createElement('div');
  row.className = `vm-row ${v.is_mapped ? 'vm-row--ok' : 'vm-row--ko'}`;
  row.dataset.refId = v.id;

  const statusIcon = v.is_mapped
    ? `<span class="vm-si vm-si--ok"><i class="fa fa-check"></i></span>`
    : `<span class="vm-si vm-si--ko"><i class="fa fa-times"></i></span>`;

  const grupBadge = v.grupo
    ? `<span class="vm-grup-badge">${esc(v.grupo)}</span>`
    : '';

  let localPrev;
  if (v.is_mapped && v.my_mappings.length) {
    localPrev = v.my_mappings.length === 1
      ? `<span class="vm-local-prev">→ ${esc(v.my_mappings[0].local_description || '')}</span>`
      : `<span class="vm-local-prev vm-local-prev--multi"><i class="fa fa-list"></i> ${v.my_mappings.length} variables mapejades</span>`;
  } else {
    localPrev = `<span class="vm-no-map-hint">Sense mapejar</span>`;
  }

  const hospCount = v.unique_hospital_count;
  const hospBadge = hospCount > 0
    ? `<span class="vm-hosp-badge" title="${hospCount} centre${hospCount !== 1 ? 's' : ''} amb mapeig"><i class="fa fa-hospital-o"></i> ${hospCount}</span>`
    : `<span class="vm-hosp-badge vm-hosp-badge--none">—</span>`;

  row.innerHTML = `
    <div class="vm-row-top" onclick="openVarModal(${v.id})">
      ${statusIcon}
      <span class="vm-row-name">${esc(v.variable)}</span>
    </div>
    <div class="vm-row-mid" onclick="openVarModal(${v.id})">
      ${grupBadge}${localPrev}
    </div>
    <div class="vm-row-bot">
      ${hospBadge}
      <label class="vm-cb-wrap" title="Seleccionar per exportar" onclick="event.stopPropagation()">
        <input type="checkbox" class="vm-cb" data-ref-id="${v.id}"
               onchange="onSelectItem(${v.id}, this.checked)">
        <span class="vm-cb-box"></span>
      </label>
    </div>
  `;

  return row;
}

// ── Detail modal ──────────────────────────────────────────────────────────────
function openVarModal(refId) {
  const v = varDataMap.get(refId);
  if (!v) return;

  // Header
  $('modalStatus').innerHTML = v.is_mapped
    ? `<span class="vm-modal-si vm-modal-si--ok"><i class="fa fa-check"></i> Mapeada</span>`
    : `<span class="vm-modal-si vm-modal-si--ko"><i class="fa fa-times"></i> No mapeada</span>`;
  $('modalTitle').textContent = v.variable;
  $('modalMeta').innerHTML = [
    v.grupo       ? `<span class="vm-mm-tag">${esc(v.grupo)}</span>` : '',
    v.snomed_id   ? `<span class="vm-mm-snomed">SNOMED: ${esc(v.snomed_id)}</span>` : '',
  ].join('');

  // Show/hide "anar a mapear"
  const mapLink = $('modalMapLink');
  mapLink.style.display = v.is_mapped ? 'none' : 'inline-flex';
  mapLink.href = `/map_var/?ref_id=${refId}`;

  // Body
  $('modalBody').innerHTML = buildModalBody(v);

  new bootstrap.Modal($('varModal')).show();
}

function buildModalBody(v) {
  let html = '<div class="vm-mb-grid">';

  // ── Left col: reference variable ──
  html += '<div class="vm-mb-col">';
  html += '<div class="vm-mb-section-title"><i class="fa fa-book"></i> Variable de Referència</div>';

  const refFields = [
    ['Grup',        v.grupo],
    ['Tipus',       v.tipo_variable],
    ['SNOMED CT',   v.snomed_id],
    ['Terme SNOMED',v.snomed_term],
    ['Categoria SN',v.snomed_categoria],
    ['ICD-10',      v.icd10_code],
    ['openEHR',     v.openehr_nombre],
    ['Arquetip',    v.arquetipo_id],
    ['Element AT',  v.at_code],
    ['Categoria oEHR', v.openehr_categoria],
    ['Tipus dada',  v.openehr_tipo_dato],
    ['Unitat UCUM', v.unidad_ucum],
    ['Unitat oEHR', v.unidad_openehr],
  ];

  refFields.forEach(([label, val]) => {
    if (val) html += mbRow(label, val);
  });

  if (v.descripcion_socmic) {
    html += `
      <div class="vm-mb-desc">
        <span class="vm-mb-dlabel">Descripció</span>
        <p class="vm-mb-dtext">${esc(v.descripcion_socmic)}</p>
      </div>`;
  }

  html += '</div>'; // end left col

  // ── Right col: hospital mapping ──
  html += '<div class="vm-mb-col">';

  if (v.is_mapped && v.my_mappings.length) {
    html += '<div class="vm-mb-section-title"><i class="fa fa-hospital-o"></i> El meu hospital</div>';

    v.my_mappings.forEach((m, i) => {
      if (i > 0) html += '<hr class="vm-mb-sep">';
      html += `<div class="vm-mb-mapping">`;
      html += mbRow('Variable local', m.local_description);
      if (m.tipo_local)      html += mbRow('Tipus local', m.tipo_local);
      if (m.origen_variable) html += mbRow('Origen', m.origen_variable);
      if (m.q1 || m.q2 || m.q3) {
        const qStr = [
          m.q1 != null ? `Q1: ${fmtNum(m.q1)}` : null,
          m.q2 != null ? `Q2: ${fmtNum(m.q2)}` : null,
          m.q3 != null ? `Q3: ${fmtNum(m.q3)}` : null,
        ].filter(Boolean).join(' · ');
        html += mbRow('Distribució', qStr);
      }
      if (m.porc_pats != null) html += mbRow('% Pacients', fmtNum(m.porc_pats) + '%');
      if (m.cadencia)          html += mbRow('Cadència', m.cadencia);
      if (m.count)             html += mbRow('Nº registres', fmtNum(m.count));
      html += mbRow('Mapeada per', m.username);
      html += mbRow('Data', m.created_at);
      if (m.validado) html += `<div class="vm-mb-validated"><i class="fa fa-check-circle"></i> Validat</div>`;
      html += '</div>';
    });

  } else {
    html += `
      <div class="vm-mb-section-title"><i class="fa fa-exclamation-triangle"></i> El meu hospital</div>
      <div class="vm-mb-warning">
        <p>Aquesta variable no està mapeada pel vostre hospital.</p>
        <p class="vm-mb-warning-sub">Feu clic a "Anar a Mapejar" per crear el mapeig.</p>
      </div>`;
  }

  html += '</div>'; // end right col
  html += '</div>'; // end grid

  // ── Other hospitals ──
  if (v.other_mappings.length) {
    html += `
      <div class="vm-mb-others">
        <div class="vm-mb-section-title">
          <i class="fa fa-globe"></i> Altres hospitals
          <span class="vm-mb-count">${v.other_mappings.length}</span>
        </div>
        <div class="vm-mb-others-list">`;

    v.other_mappings.forEach((m, i) => {
      if (i > 0) html += '<hr class="vm-mb-sep vm-mb-sep--light">';
      const acronim = m.hospital_acronim || m.hospital_name || '—';
      html += `<div class="vm-mb-other-card">`;
      html += `<div class="vm-mb-other-header">
        <span class="vm-mb-acronim">${esc(acronim)}</span>`;
      if (m.hospital_name && m.hospital_name !== acronim) {
        html += `<span class="vm-mb-hosp-name">${esc(m.hospital_name)}</span>`;
      }
      if (m.validado) html += `<span class="vm-mb-val-dot">✓ Validat</span>`;
      html += `</div>`;
      html += mbRow('Variable local', m.local_description);
      if (m.tipo_local)      html += mbRow('Tipus local', m.tipo_local);
      if (m.origen_variable) html += mbRow('Origen', m.origen_variable);
      if (m.q1 != null || m.q2 != null || m.q3 != null) {
        const qStr = [
          m.q1 != null ? `Q1: ${fmtNum(m.q1)}` : null,
          m.q2 != null ? `Q2: ${fmtNum(m.q2)}` : null,
          m.q3 != null ? `Q3: ${fmtNum(m.q3)}` : null,
        ].filter(Boolean).join(' · ');
        html += mbRow('Distribució', qStr);
      }
      if (m.porc_pats != null) html += mbRow('% Pacients', fmtNum(m.porc_pats) + '%');
      if (m.cadencia)          html += mbRow('Cadència', m.cadencia);
      // html += mbRow('Data', m.created_at);
      html += '</div>';
    });

    html += '</div></div>';
  }

  return html;
}

function mbRow(label, value) {
  if (!value && value !== 0) return '';
  return `
    <div class="vm-mb-row">
      <span class="vm-mb-label">${label}</span>
      <span class="vm-mb-val">${esc(String(value))}</span>
    </div>`;
}

function fmtNum(n) {
  if (n == null) return '—';
  return Number.isInteger(n) ? n.toLocaleString('ca') : parseFloat(n).toFixed(2);
}

// ── Event handlers ────────────────────────────────────────────────────────────
function onSearchInput(value) {
  STATE.searchQuery = value.trim();
  $('clearSearch').style.display = value ? 'flex' : 'none';

  if (STATE.searchQuery && !STATE.currentGrup) {
    // Search without group → show list, activate mapped filter bar
    showMappedFilter(true);
    activatePill(null);
  }

  clearTimeout(STATE.debounce);
  STATE.debounce = setTimeout(() => {
    if (STATE.searchQuery || STATE.currentGrup) {
      loadVars();
    } else {
      // Empty search + no group → back to category grid
      showMappedFilter(false);
      renderProgress(STATE.globalStats);
      renderStatCards(STATE.globalStats);
      showCategoryGrid(STATE.categories);
    }
  }, 300);
}

function clearSearch() {
  $('varSearch').value = '';
  $('clearSearch').style.display = 'none';
  STATE.searchQuery = '';

  if (!STATE.currentGrup) {
    showMappedFilter(false);
    renderProgress(STATE.globalStats);
    renderStatCards(STATE.globalStats);
    showCategoryGrid(STATE.categories);
  } else {
    loadVars();
  }
}

function onMappedFilter(val, btn) {
  document.querySelectorAll('.vm-mf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  STATE.mappedFilter = val;
  loadVars();
}

function onSelectItem(refId, checked) {
  if (checked) STATE.selectedIds.add(refId);
  else          STATE.selectedIds.delete(refId);
  updateSelUI();
}

function onSelectAll(checked) {
  document.querySelectorAll('.vm-cb').forEach(cb => {
    const id = parseInt(cb.dataset.refId);
    cb.checked = checked;
    checked ? STATE.selectedIds.add(id) : STATE.selectedIds.delete(id);
  });
  updateSelUI();
}

function updateSelUI() {
  const n = STATE.selectedIds.size;
  document.querySelectorAll('.sel-count-display').forEach(el => el.textContent = n);
  document.querySelectorAll('.sel-dep-btn').forEach(btn => btn.disabled = n === 0);
  const badge = $('exportBadge');
  if (badge) badge.style.display = n > 0 ? 'inline' : 'none';
}

function showMappedFilter(show) {
  $('mappedFilter').style.display = show ? 'flex' : 'none';
}

// ── Exports ───────────────────────────────────────────────────────────────────
function onExportMineAll() {
  window.location.href = '/mapeos/export/mine';
}

function onExportAllAll() {
  window.location.href = '/mapeos/export/all';
}

async function onExportSelectionMine() {
  if (!STATE.selectedIds.size) return;
  await _doExport('/mapeos/export/mine/selection', 'seleccio_el_meu_centre.xlsx');
}

async function onExportSelectionAll() {
  if (!STATE.selectedIds.size) return;
  await _doExport('/mapeos/export/all/selection', 'seleccio_tots_centres.xlsx');
}

async function _doExport(url, filename) {
  try {
    const res = await fetch(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ ref_ids: [...STATE.selectedIds] }),
    });
    if (!res.ok) throw new Error('Export failed');
    const blob = await res.blob();
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob), download: filename,
    });
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  } catch (e) {
    alert('Error en l\'exportació: ' + e.message);
  }
}

// ── UI state helpers ──────────────────────────────────────────────────────────
function showState(state, msg) {
  $('stateLoading').style.display = state === 'loading' ? 'flex'  : 'none';
  $('stateCats').style.display    = state === 'cats'    ? 'block' : 'none';
  $('stateEmpty').style.display   = state === 'empty'   ? 'flex'  : 'none';
  $('stateList').style.display    = state === 'list'    ? 'block' : 'none';
  if (state === 'empty' && msg) $('emptyMsg').textContent = msg;
}

// ── Utils ─────────────────────────────────────────────────────────────────────
function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
