/* ═══════════════════════════════════════════════════════
   CarAnalyser — app.js
   ═══════════════════════════════════════════════════════ */

'use strict';

// ─── SETTINGS ────────────────────────────────────────────
const DEFAULT_SETTINGS = { costs: 2000, targetMarkup: 10000 };
let settings = loadSettings();

function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem('caranalyser_settings') || '{}');
    return { ...DEFAULT_SETTINGS, ...s };
  } catch { return { ...DEFAULT_SETTINGS }; }
}
function saveSettings() {
  localStorage.setItem('caranalyser_settings', JSON.stringify(settings));
}

// ─── STATE ────────────────────────────────────────────────
let allListings = [];
let filtered   = [];
let activeFilter = 'all';
let sortMode     = 'margin_desc';
let searchText   = '';

// ─── INIT ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  applySettingsToUI();
  bindEvents();
  await loadListings();
});

// ─── EVENT BINDING ────────────────────────────────────────
function bindEvents() {
  // Search
  $('#btn-search').addEventListener('click', handleSearch);
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && document.activeElement?.closest('.search-panel')) handleSearch();
  });

  // Clear all
  $('#btn-clear-all').addEventListener('click', async () => {
    if (!confirm('Remover todos os anúncios da lista?')) return;
    await apiFetch('/api/listings', { method: 'DELETE' });
    allListings = [];
    applyFilters();
    renderCards();
    toast('Lista limpa.', 'info');
  });

  // Quick filters
  $$('.qf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.qf-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      applyFilters();
      renderCards();
    });
  });

  // Sort
  $('#sort-select').addEventListener('change', e => {
    sortMode = e.target.value;
    applyFilters();
    renderCards();
  });

  // Filter search
  $('#filter-search').addEventListener('input', e => {
    searchText = e.target.value.toLowerCase();
    applyFilters();
    renderCards();
  });

  // Settings modal
  $('#btn-settings').addEventListener('click', () => openModal('modal-settings'));
  $('#btn-save-settings').addEventListener('click', () => {
    settings.costs        = Number($('#cfg-costs').value) || 0;
    settings.targetMarkup = Number($('#cfg-markup').value) || 0;
    saveSettings();
    updateDeductionDisplay();
    closeModal('modal-settings');
    applyFilters();
    renderCards();
    toast('Configurações salvas.', 'success');
  });
  $('#cfg-costs, #cfg-markup').forEach(el =>
    el.addEventListener('input', updateDeductionDisplay)
  );

  // Manual add modal
  $('#btn-add-manual').addEventListener('click', () => openModal('modal-add'));
  $('#btn-save-add').addEventListener('click', handleAddManual);

  // Modal overlays close on bg click
  $$('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) closeModal(overlay.id);
    });
  });

  // Modal close buttons
  $$('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.close));
  });
}

// ─── SEARCH ──────────────────────────────────────────────
async function handleSearch() {
  const sources = [];
  if ($('#src-webmotors').checked) sources.push('webmotors');
  if ($('#src-icarros').checked)   sources.push('icarros');

  if (!sources.length) { toast('Selecione pelo menos uma fonte.', 'error'); return; }

  const filters = {
    sources,
    brand:     $('#f-brand').value.trim()     || undefined,
    model:     $('#f-model').value.trim()     || undefined,
    price_min: Number($('#f-price-min').value) || undefined,
    price_max: Number($('#f-price-max').value) || undefined,
    year_min:  Number($('#f-year-min').value)  || undefined,
    year_max:  Number($('#f-year-max').value)  || undefined,
    km_max:    Number($('#f-km-max').value)    || undefined,
  };

  setSearchStatus('Buscando anúncios…', 'loading', true);
  setSearchButtonLoading(true);

  try {
    const data = await apiFetch('/api/search', { method: 'POST', body: filters });
    const { total, added, errors } = data;

    let msg = `${total} anúncio(s) encontrado(s). ${added} novo(s) adicionado(s).`;
    if (errors?.length) msg += ` ⚠️ ${errors.join('; ')}`;

    setSearchStatus(msg, errors?.length ? 'error' : 'success');
    await loadListings();
  } catch (err) {
    setSearchStatus(`Erro: ${err.message}`, 'error');
  } finally {
    setSearchButtonLoading(false);
  }
}

function setSearchButtonLoading(loading) {
  const btn = $('#btn-search');
  if (loading) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Buscando…`;
  } else {
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Buscar Carros`;
  }
}

function setSearchStatus(msg, type, sticky = false) {
  const el = $('#search-status');
  el.textContent = msg;
  el.className = `search-status ${type}`;
  el.classList.remove('hidden');
  if (!sticky) setTimeout(() => el.classList.add('hidden'), 6000);
}

// ─── LOAD LISTINGS ────────────────────────────────────────
async function loadListings() {
  const data = await apiFetch('/api/listings');
  allListings = data.listings || [];
  applyFilters();
  renderCards();
}

// ─── FILTERING & SORTING ──────────────────────────────────
function applyFilters() {
  let list = allListings.map(car => ({
    car,
    margin: calcMargin(car),
    risk:   calcRisk(car),
  }));

  list.forEach(item => {
    item.rec = getRecommendation(item.margin, item.risk);
  });

  if (activeFilter !== 'all') {
    list = list.filter(item => item.rec.status === activeFilter);
  }

  if (searchText) {
    list = list.filter(({ car }) => {
      const haystack = `${car.brand} ${car.model} ${car.version} ${car.city} ${car.state}`.toLowerCase();
      return haystack.includes(searchText);
    });
  }

  list.sort((a, b) => {
    switch (sortMode) {
      case 'price_asc':      return a.car.price - b.car.price;
      case 'km_asc':         return a.car.km - b.car.km;
      case 'year_desc':      return b.car.year - a.car.year;
      case 'discount_desc':  return (b.margin.discountPct || 0) - (a.margin.discountPct || 0);
      case 'margin_desc':
      default:               return (b.margin.netMargin || -Infinity) - (a.margin.netMargin || -Infinity);
    }
  });

  filtered = list;
  updateStats();
}

function updateStats() {
  const all = allListings.map(car => {
    const margin = calcMargin(car);
    const risk   = calcRisk(car);
    return getRecommendation(margin, risk).status;
  });
  $('#stat-total').textContent = allListings.length;
  $('#stat-buy').textContent   = all.filter(s => s === 'buy').length;
  $('#stat-check').textContent = all.filter(s => s === 'check').length;
  $('#stat-avoid').textContent = all.filter(s => s === 'avoid').length;
}

// ─── MARGIN & RISK ────────────────────────────────────────
function calcMargin(car) {
  const fipe   = car.fipe_price || 0;
  const listed = car.price      || 0;
  const costs  = settings.costs;
  const target = settings.targetMarkup;

  if (!fipe || !listed) return { fipe, listed, grossMargin: null, netMargin: null, maxBuyPrice: null, discountPct: null };

  const grossMargin = fipe - listed;
  const netMargin   = grossMargin - costs;
  const maxBuyPrice = fipe - (target + costs);
  const discountPct = fipe > 0 ? ((fipe - listed) / fipe) * 100 : 0;

  return { fipe, listed, grossMargin, netMargin, maxBuyPrice, discountPct, costs, target };
}

function calcRisk(car) {
  let score = 0;
  const factors = [];
  const currentYear = new Date().getFullYear();
  const age = currentYear - (car.year || currentYear);

  // KM
  if (car.km > 100000) {
    score += 2;
    factors.push({ type: 'danger', icon: '⚠️', text: `KM alto: ${fmtKm(car.km)} km` });
  } else if (car.km > 60000) {
    score += 1;
    factors.push({ type: 'warning', icon: '⚡', text: `KM moderado: ${fmtKm(car.km)} km` });
  } else if (car.km > 0) {
    factors.push({ type: 'success', icon: '✓', text: `KM baixo: ${fmtKm(car.km)} km` });
  }

  // Year
  if (age > 7) {
    score += 2;
    factors.push({ type: 'danger', icon: '⚠️', text: `Ano antigo: ${car.year}` });
  } else if (age > 4) {
    score += 1;
    factors.push({ type: 'warning', icon: '⚡', text: `Ano moderado: ${car.year}` });
  } else if (car.year) {
    factors.push({ type: 'success', icon: '✓', text: `Ano recente: ${car.year}` });
  }

  // Flags
  if (car.risk_flags?.auction) {
    score += 3;
    factors.push({ type: 'critical', icon: '🚨', text: 'Histórico de leilão — cuidado!' });
  }
  if (car.risk_flags?.recall) {
    score += 1;
    factors.push({ type: 'warning', icon: '⚡', text: 'Recall pendente' });
  }

  // Owners
  if ((car.owners || 1) >= 3) {
    score += 1;
    factors.push({ type: 'warning', icon: '⚡', text: `Múltiplos donos: ${car.owners}` });
  } else if ((car.owners || 1) === 1) {
    factors.push({ type: 'success', icon: '✓', text: 'Único dono' });
  }

  // Color liquidity
  const popColors = ['branco', 'prata', 'cinza', 'preto', 'white', 'silver', 'gray', 'black', 'grey'];
  const colorLow  = (car.color || '').toLowerCase();
  if (car.color) {
    if (popColors.some(c => colorLow.includes(c))) {
      factors.push({ type: 'success', icon: '✓', text: `Cor popular (${car.color}) — boa liquidez` });
    } else {
      score += 1;
      factors.push({ type: 'warning', icon: '⚡', text: `Cor menos popular (${car.color}) — liquidez menor` });
    }
  }

  const level = score === 0 ? 'minimal' : score <= 2 ? 'low' : score <= 4 ? 'medium' : 'high';
  const levelLabel = { minimal: 'Mínimo', low: 'Baixo', medium: 'Moderado', high: 'Alto' }[level];

  return { score, level, levelLabel, factors };
}

function getRecommendation(margin, risk) {
  if (margin.netMargin === null) {
    return { status: 'unknown', label: 'Sem FIPE', icon: '❓', css: 'unknown' };
  }

  const target = settings.targetMarkup;
  const { netMargin } = margin;
  const { level } = risk;

  if (netMargin >= target && (level === 'minimal' || level === 'low')) {
    return { status: 'buy',   label: 'Boa Compra', icon: '✅', css: 'buy'   };
  }
  if (netMargin >= target && level === 'medium') {
    return { status: 'check', label: 'Verificar',  icon: '⚠️', css: 'check' };
  }
  if (netMargin >= target && level === 'high') {
    return { status: 'check', label: 'Alto Risco', icon: '🔴', css: 'check' };
  }
  if (netMargin > 0) {
    return { status: 'check', label: 'Margem Baixa', icon: '⚡', css: 'check' };
  }
  return   { status: 'avoid', label: 'Evitar',     icon: '🚫', css: 'avoid' };
}

// ─── RENDER ───────────────────────────────────────────────
function renderCards() {
  const grid = $('#cards-grid');

  if (!filtered.length) {
    grid.innerHTML = `
      <div class="empty-state">
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="1.5"><path d="M5 17H3a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h11l4 4 1 4H5z"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/></svg>
        <p>${allListings.length ? 'Nenhum resultado para os filtros aplicados.' : 'Nenhum anúncio ainda.'}</p>
        <p class="empty-sub">${allListings.length ? 'Tente ajustar os filtros.' : 'Use o formulário acima para buscar carros no Webmotors e iCarros.'}</p>
      </div>`;
    return;
  }

  grid.innerHTML = filtered.map(({ car, margin, risk, rec }) => buildCard(car, margin, risk, rec)).join('');

  // Card click → detail modal
  grid.querySelectorAll('.car-card').forEach(card => {
    card.addEventListener('click', e => {
      if (e.target.closest('.btn-link') || e.target.closest('.btn-delete')) return;
      const id = card.dataset.id;
      const item = filtered.find(i => i.car.id === id);
      if (item) openDetail(item.car, item.margin, item.risk, item.rec);
    });
  });

  // Delete buttons
  grid.querySelectorAll('.btn-delete').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const id = btn.dataset.id;
      await apiFetch(`/api/listing/${id}`, { method: 'DELETE' });
      allListings = allListings.filter(c => c.id !== id);
      applyFilters();
      renderCards();
      toast('Anúncio removido.', 'info');
    });
  });
}

function buildCard(car, margin, risk, rec) {
  const title    = [car.brand, car.model].filter(Boolean).join(' ') || 'Sem título';
  const subtitle = car.version || '';
  const specs    = buildSpecTags(car);
  const srcClass = sourceBadgeClass(car.source);

  const photoHtml = car.photo
    ? `<img class="card-photo-img" src="${esc(car.photo)}" alt="${esc(title)}" loading="lazy" onerror="this.parentNode.innerHTML=placeholderSVG()" />`
    : `<div class="card-photo-placeholder">${carSVG(48)}</div>`;

  const priceHtml = fmtBRL(car.price);

  const fipeHtml = margin.fipe
    ? `<span class="price-fipe-label">FIPE</span>
       <span class="price-fipe-value">${fmtBRL(margin.fipe)}</span>
       <span class="${margin.discountPct >= 0 ? 'price-fipe-disc' : 'price-fipe-over'}">
         ${margin.discountPct >= 0 ? '-' : '+'}${Math.abs(margin.discountPct).toFixed(1)}%
       </span>`
    : `<span class="price-fipe-label" style="color:#d97706">FIPE não encontrada</span>`;

  const marginCss  = marginClass(margin, rec);
  const marginLabel = margin.netMargin !== null
    ? `Margem estimada: <strong>${fmtBRL(margin.netMargin)}</strong>`
    : 'Aguardando FIPE';

  const riskBadge = `<span class="badge badge-risk-${risk.level === 'minimal' || risk.level === 'low' ? 'low' : risk.level}">${risk.levelLabel}</span>`;

  const location = [car.city, car.state].filter(Boolean).join(' / ');

  return `
<div class="car-card status-${rec.css}" data-id="${esc(car.id)}">
  <div class="card-badges">
    <span class="badge badge-${srcClass}">${esc(car.source_label || car.source)}</span>
    <span class="badge badge-${rec.css}">${rec.label}</span>
  </div>

  <div class="card-photo">${photoHtml}</div>

  <div class="card-body">
    <div>
      <div class="card-title">${esc(title)}</div>
      ${subtitle ? `<div class="card-version">${esc(subtitle)}</div>` : ''}
    </div>

    <div class="card-specs">${specs}</div>

    <div class="card-price-block">
      <div class="price-listed">${priceHtml}</div>
      <div class="price-fipe-row">${fipeHtml}</div>
    </div>

    <div class="card-margin ${marginCss}">
      <div class="margin-row">
        <span class="margin-label">${marginLabel}</span>
        ${riskBadge}
      </div>
    </div>
  </div>

  <div class="card-footer">
    <span class="card-location">
      ${location ? `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>${esc(location)}` : ''}
    </span>
    <div style="display:flex;gap:6px">
      <a class="btn-link" href="${esc(car.source_url || '#')}" target="_blank" rel="noopener" onclick="event.stopPropagation()">
        Ver anúncio <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </a>
      <button class="btn-delete" data-id="${esc(car.id)}" title="Remover">✕</button>
    </div>
  </div>
</div>`;
}

function buildSpecTags(car) {
  const tags = [];
  if (car.year)         tags.push(car.year);
  if (car.km)           tags.push(fmtKm(car.km) + ' km');
  if (car.transmission) tags.push(car.transmission);
  if (car.fuel)         tags.push(car.fuel);
  if (car.color)        tags.push(car.color);
  return tags.map(t => `<span class="spec-tag">${esc(String(t))}</span>`).join('');
}

function marginClass(margin, rec) {
  if (margin.netMargin === null) return 'margin-unknown';
  if (rec.status === 'buy')   return 'margin-positive';
  if (rec.status === 'check') return 'margin-warn';
  return 'margin-negative';
}

function sourceBadgeClass(source) {
  const map = { webmotors: 'webmotors', icarros: 'icarros', facebook: 'facebook' };
  return map[source] || 'manual';
}

// ─── DETAIL MODAL ─────────────────────────────────────────
function openDetail(car, margin, risk, rec) {
  const title = [car.brand, car.model, car.version].filter(Boolean).join(' ') || 'Detalhes';
  $('#detail-title').textContent = title;

  const body = $('#detail-body');

  // Recommendation box
  const recBox = `
    <div class="recommendation-box ${rec.css}">
      <span class="rec-icon">${rec.icon}</span>
      <div>
        <div style="font-size:13px;font-weight:500;opacity:.8">Recomendação</div>
        <div>${rec.label}</div>
      </div>
    </div>`;

  // Photo
  const photoHtml = car.photo
    ? `<div class="detail-photo-wrap"><img src="${esc(car.photo)}" alt="${esc(title)}" style="width:100%;border-radius:8px" onerror="this.parentNode.innerHTML='<div class=detail-photo-placeholder>${carSVG(48)}</div>'" /></div>`
    : `<div class="detail-photo-placeholder">${carSVG(48)}</div>`;

  // Specs
  const specs = [
    ['Marca',         car.brand],
    ['Modelo',        car.model],
    ['Versão',        car.version],
    ['Ano fab./mod.', [car.year, car.year_model].filter(Boolean).join('/')],
    ['Quilometragem', car.km ? fmtKm(car.km) + ' km' : '—'],
    ['Cor',           car.color],
    ['Câmbio',        car.transmission],
    ['Combustível',   car.fuel],
    ['Cidade',        [car.city, car.state].filter(Boolean).join(' / ')],
    ['Nº de donos',   car.owners ?? '—'],
    ['Vendedor',      car.seller_name],
    ['Tipo anunc.',   car.seller_type],
  ].filter(([, v]) => v).map(([l, v]) => `
    <div class="detail-spec">
      <span class="detail-spec-label">${l}</span>
      <span class="detail-spec-value">${esc(String(v))}</span>
    </div>`).join('');

  // Margin table
  const hasFipe = margin.fipe && margin.listed;
  const maxBuyNote = hasFipe
    ? `<div class="max-buy-callout">
         💡 Para garantir margem de <strong>${fmtBRL(settings.targetMarkup)}</strong> com custos de <strong>${fmtBRL(settings.costs)}</strong>,
         o preço máximo de compra é <strong>${fmtBRL(margin.maxBuyPrice)}</strong>.
         ${margin.listed <= margin.maxBuyPrice
           ? `<br><span style="color:var(--green-text);font-weight:600">✓ Preço anunciado está abaixo do limite.</span>`
           : `<br><span style="color:var(--red-text);font-weight:600">✗ Preço anunciado está acima do limite por ${fmtBRL(margin.listed - margin.maxBuyPrice)}.</span>`}
       </div>` : '';

  const marginSection = hasFipe ? `
    <div class="analysis-section">
      <div class="section-title">Análise Financeira</div>
      <table class="margin-table">
        <tr><td class="col-label">Referência FIPE</td><td class="col-value">${fmtBRL(margin.fipe)}</td></tr>
        <tr><td class="col-label">(−) Preço anunciado</td><td class="col-value">${fmtBRL(margin.listed)}</td></tr>
        <tr class="row-total"><td class="col-label">= Margem bruta</td><td class="col-value">${fmtBRL(margin.grossMargin)}</td></tr>
        <tr><td class="col-label">(−) Custos estimados</td><td class="col-value">
          <input type="number" value="${settings.costs}" min="0" step="100" style="width:110px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;text-align:right" id="detail-costs" />
        </td></tr>
        <tr class="${rec.css === 'buy' ? 'row-highlight-green' : rec.css === 'avoid' ? 'row-highlight-red' : 'row-highlight-yellow'}">
          <td class="col-label">= Margem líquida</td>
          <td class="col-value" id="detail-net-margin">${fmtBRL(margin.netMargin)}</td>
        </tr>
        <tr><td class="col-label">Desconto sobre FIPE</td><td class="col-value">${margin.discountPct?.toFixed(1)}%</td></tr>
      </table>
      ${maxBuyNote}
    </div>` : `
    <div class="analysis-section">
      <div class="section-title">Análise Financeira</div>
      <div style="padding:12px;background:var(--yellow-bg);color:var(--yellow-text);border-radius:8px;font-size:13px">
        ⚠️ Preço FIPE não encontrado automaticamente. Atualize o valor manualmente.
      </div>
    </div>`;

  // Risk factors
  const riskSection = `
    <div class="analysis-section">
      <div class="section-title">
        Fatores de Risco — Nível: ${risk.levelLabel}
        <span class="badge badge-risk-${risk.level === 'minimal' || risk.level === 'low' ? 'low' : risk.level}">${risk.score} ponto(s)</span>
      </div>
      <div class="risk-factors">
        ${risk.factors.map(f => `
          <div class="risk-factor ${f.type}">
            <span class="risk-icon">${f.icon}</span>
            <span>${esc(f.text)}</span>
          </div>`).join('')}
      </div>
    </div>`;

  body.innerHTML = `
    ${recBox}
    <div class="detail-top">
      ${photoHtml}
      <div class="detail-info">
        <div class="detail-specs-grid">${specs}</div>
        <a class="btn-link" href="${esc(car.source_url || '#')}" target="_blank" rel="noopener" style="align-self:flex-start">
          Abrir no ${esc(car.source_label || car.source)}
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
        </a>
      </div>
    </div>
    ${marginSection}
    ${riskSection}`;

  // Live cost recalculation
  const costsInput = body.querySelector('#detail-costs');
  if (costsInput) {
    costsInput.addEventListener('input', () => {
      const newCosts     = Number(costsInput.value) || 0;
      const newNet       = (margin.grossMargin || 0) - newCosts;
      const netEl        = body.querySelector('#detail-net-margin');
      if (netEl) netEl.textContent = fmtBRL(newNet);
    });
  }

  openModal('modal-detail');
}

// ─── MANUAL ADD ───────────────────────────────────────────
async function handleAddManual() {
  const price = Number($('#add-price').value);
  const brand = $('#add-brand').value.trim();
  const model = $('#add-model').value.trim();
  if (!price || !brand || !model) {
    toast('Preencha ao menos Marca, Modelo e Preço.', 'error');
    return;
  }

  const cityRaw = $('#add-city').value.trim();
  const [city, state] = cityRaw.includes('/') ? cityRaw.split('/').map(s => s.trim()) : [cityRaw, ''];

  const listing = {
    brand, model,
    version:      $('#add-version').value.trim(),
    year:         Number($('#add-year').value) || 0,
    year_model:   Number($('#add-year-model').value) || 0,
    km:           Number($('#add-km').value) || 0,
    color:        $('#add-color').value.trim(),
    transmission: $('#add-transmission').value,
    fuel:         $('#add-fuel').value,
    price,
    fipe_price:   Number($('#add-fipe').value) || null,
    source:       $('#add-source').value,
    source_label: { webmotors: 'Webmotors', icarros: 'iCarros', facebook: 'Facebook', manual: 'Manual' }[$('#add-source').value] || 'Manual',
    source_url:   $('#add-url').value.trim() || '#',
    city, state,
    owners:       Number($('#add-owners').value) || 1,
    risk_flags: {
      auction: $('#add-flag-auction').checked,
      recall:  $('#add-flag-recall').checked,
    },
    liquidity: 'media',
  };

  const btn = $('#btn-save-add');
  btn.disabled = true;
  btn.textContent = 'Salvando…';

  try {
    const data = await apiFetch('/api/listing/add', { method: 'POST', body: listing });
    allListings.unshift(data.listing);
    applyFilters();
    renderCards();
    closeModal('modal-add');
    toast('Anúncio adicionado!', 'success');
    clearAddForm();
  } catch (err) {
    toast(`Erro: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Salvar anúncio';
  }
}

function clearAddForm() {
  ['add-brand','add-model','add-version','add-year','add-year-model','add-km',
   'add-color','add-price','add-fipe','add-owners','add-city','add-url'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = ['add-owners'].includes(id) ? '1' : '';
  });
  $('#add-flag-auction').checked = false;
  $('#add-flag-recall').checked  = false;
}

// ─── SETTINGS UI ──────────────────────────────────────────
function applySettingsToUI() {
  $('#cfg-costs').value  = settings.costs;
  $('#cfg-markup').value = settings.targetMarkup;
  updateDeductionDisplay();
}

function updateDeductionDisplay() {
  const costs  = Number($('#cfg-costs').value)  || 0;
  const markup = Number($('#cfg-markup').value) || 0;
  const total  = costs + markup;
  $('#cfg-total-deduction').textContent = fmtNum(total);
}

// ─── MODAL HELPERS ────────────────────────────────────────
function openModal(id) {
  document.getElementById(id)?.classList.remove('hidden');
}
function closeModal(id) {
  document.getElementById(id)?.classList.add('hidden');
}

// ─── API FETCH ────────────────────────────────────────────
async function apiFetch(url, opts = {}) {
  const res = await fetch(url, {
    method:  opts.method || 'GET',
    headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
    body:    opts.body  ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

// ─── FORMATTERS ───────────────────────────────────────────
function fmtBRL(v) {
  if (v == null) return '—';
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 }).format(v);
}
function fmtKm(v) {
  return new Intl.NumberFormat('pt-BR').format(v);
}
function fmtNum(v) {
  return new Intl.NumberFormat('pt-BR').format(v);
}

// ─── TOAST ────────────────────────────────────────────────
let toastTimer;
function toast(msg, type = 'info') {
  const el = $('#toast');
  el.textContent = msg;
  el.className = `toast ${type}`;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
}

// ─── UTILS ────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function carSVG(size = 48) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="#d1d5db" stroke-width="1.5"><path d="M5 17H3a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h11l4 4 1 4H5z"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/></svg>`;
}
