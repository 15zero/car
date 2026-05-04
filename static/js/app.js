/* ═══════════════════════════════════════════════
   CarAnalyser — app.js
   ═══════════════════════════════════════════════ */
'use strict';

// ─── Settings ────────────────────────────────────
const DEFAULTS = { costs: 2000, targetMarkup: 10000 };
let settings = (() => {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem('ca_settings') || '{}') }; }
  catch { return { ...DEFAULTS }; }
})();
const saveSettings = () => localStorage.setItem('ca_settings', JSON.stringify(settings));

// ─── State ───────────────────────────────────────
let allListings  = [];
let filtered     = [];
let activeFilter = 'all';
let sortMode     = 'margin_desc';
let searchText   = '';

// ─── Boot ────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  syncSettingsUI();
  bindEvents();
  showSkeletons(6);
  await loadListings();
});

// ─── Events ──────────────────────────────────────
function bindEvents() {
  // Search
  q('#btn-search').addEventListener('click', handleSearch);
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.closest('.search-card')) handleSearch();
  });

  // Source toggles
  qq('.src-btn').forEach(btn =>
    btn.addEventListener('click', () => btn.classList.toggle('active'))
  );

  // Clear all
  q('#btn-clear-all').addEventListener('click', async () => {
    if (!confirm('Remover todos os anúncios da lista?')) return;
    await api('/api/listings', { method: 'DELETE' });
    allListings = [];
    render();
    toast('Lista limpa.', 'info');
  });

  // Stat pills as filters
  qq('.stat-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      activeFilter = pill.dataset.filter;
      qq('.stat-pill').forEach(p => p.classList.remove('active-filter'));
      pill.classList.add('active-filter');
      applyFilters();
      renderCards();
    });
  });

  // Text filter
  q('#filter-search').addEventListener('input', e => {
    searchText = e.target.value.toLowerCase();
    applyFilters();
    renderCards();
  });

  // Sort
  q('#sort-select').addEventListener('change', e => {
    sortMode = e.target.value;
    applyFilters();
    renderCards();
  });

  // Settings modal
  q('#btn-settings').addEventListener('click', () => openModal('modal-settings'));
  q('#btn-save-settings').addEventListener('click', () => {
    settings.costs        = +q('#cfg-costs').value  || 0;
    settings.targetMarkup = +q('#cfg-markup').value || 0;
    saveSettings();
    updateFormulaDisplay();
    closeModal('modal-settings');
    applyFilters(); renderCards();
    toast('Configurações salvas!', 'success');
  });
  ['#cfg-costs','#cfg-markup'].forEach(id =>
    q(id).addEventListener('input', updateFormulaDisplay)
  );

  // Manual add modal
  q('#btn-add-manual').addEventListener('click', () => openModal('modal-add'));
  q('#btn-save-add').addEventListener('click', handleAdd);

  // Modal: close on overlay click or × button
  qq('.overlay').forEach(o => o.addEventListener('click', e => {
    if (e.target === o) closeModal(o.id);
  }));
  qq('[data-close]').forEach(b => b.addEventListener('click', () => closeModal(b.dataset.close)));
}

// ─── Search ──────────────────────────────────────
async function handleSearch() {
  const sources = [...qq('.src-btn.active')].map(b => b.dataset.src);
  if (!sources.length) { toast('Selecione pelo menos uma fonte.', 'error'); return; }

  const filters = {
    sources,
    brand:     q('#f-brand').value.trim()     || undefined,
    model:     q('#f-model').value.trim()     || undefined,
    price_min: +q('#f-price-min').value       || undefined,
    price_max: +q('#f-price-max').value       || undefined,
    year_min:  +q('#f-year-min').value        || undefined,
    year_max:  +q('#f-year-max').value        || undefined,
    km_max:    +q('#f-km-max').value          || undefined,
    max_pages: 15,
  };

  setBtnLoading(true);
  showSkeletons(8);

  try {
    // Get SSE token
    const { token } = await api('/api/search/prepare', { method: 'POST', body: filters });

    await new Promise((resolve, reject) => {
      const es = new EventSource(`/api/search/stream?token=${token}`);
      const counts = {};

      es.addEventListener('status', e => {
        const d = JSON.parse(e.data);
        setStatus(d.msg, 'loading');
      });

      es.addEventListener('progress', e => {
        const d = JSON.parse(e.data);
        counts[d.source] = d.total;
        const total = Object.values(counts).reduce((a, b) => a + b, 0);
        setStatus(`Buscando… ${total} anúncios coletados (página ${d.page} — ${d.source})`, 'loading');
      });

      es.addEventListener('fipe_progress', e => {
        const d = JSON.parse(e.data);
        setStatus(`Consultando FIPE… ${d.done}/${d.total}`, 'loading');
      });

      es.addEventListener('done', async e => {
        es.close();
        const d = JSON.parse(e.data);
        let msg = `${d.total} resultado(s). ${d.added} novo(s) adicionado(s).`;
        if (d.errors?.length) msg += ' ⚠️ ' + d.errors.join('; ');
        setStatus(msg, d.errors?.length ? 'error' : 'success');
        await loadListings();
        resolve();
      });

      es.addEventListener('error', e => {
        es.close();
        setStatus('Erro na busca. Verifique o terminal do servidor.', 'error');
        renderCards();
        reject(new Error('SSE error'));
      });
    });
  } catch(err) {
    if (!q('#search-status').classList.contains('error')) {
      setStatus(`Erro: ${err.message}`, 'error');
      renderCards();
    }
  } finally {
    setBtnLoading(false);
  }
}

function setBtnLoading(on) {
  const b = q('#btn-search');
  b.disabled = on;
  b.innerHTML = on
    ? `<span class="spinner"></span> Buscando…`
    : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Buscar Carros`;
}

function setStatus(msg, type) {
  const el = q('#search-status');
  el.className = `search-status ${type}`;
  el.innerHTML = type === 'loading'
    ? `<span class="spinner" style="border-color:rgba(37,99,235,.3);border-top-color:var(--primary)"></span>${x(msg)}`
    : x(msg);
  el.classList.remove('hidden');
  if (type !== 'loading') setTimeout(() => el.classList.add('hidden'), 6000);
}

// ─── Load listings ────────────────────────────────
async function loadListings() {
  const { listings } = await api('/api/listings');
  allListings = listings || [];
  render();
}

function render() {
  applyFilters();
  updateStats();
  renderCards();
}

// ─── Filter + sort ────────────────────────────────
function applyFilters() {
  let list = allListings.map(car => {
    const margin = calcMargin(car);
    const risk   = calcRisk(car);
    const rec    = getRec(margin, risk);
    return { car, margin, risk, rec };
  });

  if (activeFilter !== 'all') list = list.filter(i => i.rec.status === activeFilter);

  if (searchText) {
    list = list.filter(({ car }) =>
      `${car.brand} ${car.model} ${car.version} ${car.city} ${car.state}`.toLowerCase().includes(searchText)
    );
  }

  list.sort((a, b) => {
    switch (sortMode) {
      case 'price_asc':     return a.car.price - b.car.price;
      case 'km_asc':        return a.car.km - b.car.km;
      case 'year_desc':     return b.car.year - a.car.year;
      case 'discount_desc': return (b.margin.discPct||0) - (a.margin.discPct||0);
      default:              return (b.margin.net ?? -Infinity) - (a.margin.net ?? -Infinity);
    }
  });

  filtered = list;
}

function updateStats() {
  const statuses = allListings.map(car => getRec(calcMargin(car), calcRisk(car)).status);
  q('#stat-total').textContent = allListings.length;
  q('#stat-buy').textContent   = statuses.filter(s => s === 'buy').length;
  q('#stat-check').textContent = statuses.filter(s => s === 'check').length;
  q('#stat-avoid').textContent = statuses.filter(s => s === 'avoid').length;
}

// ─── Margin & risk ────────────────────────────────
function calcMargin(car) {
  const fipe = car.fipe_price || 0;
  const ask  = car.price || 0;
  if (!fipe || !ask) return { fipe, ask, gross: null, net: null, maxBuy: null, discPct: null };
  const gross  = fipe - ask;
  const net    = gross - settings.costs;
  const maxBuy = fipe - (settings.targetMarkup + settings.costs);
  const discPct = ((fipe - ask) / fipe) * 100;
  return { fipe, ask, gross, net, maxBuy, discPct };
}

function calcRisk(car) {
  let score = 0;
  const factors = [];
  const age = new Date().getFullYear() - (car.year || new Date().getFullYear());

  // KM
  if (car.km > 100000)     { score+=2; factors.push({t:'danger',  i:'⚠️', txt:`KM alto: ${km(car.km)} km`}); }
  else if (car.km > 60000) { score+=1; factors.push({t:'warning', i:'⚡', txt:`KM moderado: ${km(car.km)} km`}); }
  else if (car.km > 0)     {           factors.push({t:'success', i:'✓', txt:`KM baixo: ${km(car.km)} km`}); }

  // Age
  if (age > 7)      { score+=2; factors.push({t:'danger',  i:'⚠️', txt:`Ano antigo: ${car.year}`}); }
  else if (age > 4) { score+=1; factors.push({t:'warning', i:'⚡', txt:`Ano moderado: ${car.year}`}); }
  else if (car.year){           factors.push({t:'success', i:'✓', txt:`Ano recente: ${car.year}`}); }

  if (car.risk_flags?.auction) { score+=3; factors.push({t:'critical', i:'🚨', txt:'Histórico de leilão — atenção!'}); }
  if (car.risk_flags?.recall)  { score+=1; factors.push({t:'warning',  i:'⚡', txt:'Recall pendente'}); }

  const owners = car.owners || 1;
  if (owners >= 3)      { score+=1; factors.push({t:'warning', i:'⚡', txt:`Múltiplos donos: ${owners}`}); }
  else if (owners === 1){           factors.push({t:'success', i:'✓', txt:'Único proprietário'}); }

  const pop = ['branco','prata','cinza','preto','white','silver','gray','black','grey'];
  const col = (car.color||'').toLowerCase();
  if (car.color) {
    if (pop.some(c=>col.includes(c))) { factors.push({t:'success',i:'✓',txt:`Cor popular (${car.color}) — boa liquidez`}); }
    else { score+=1; factors.push({t:'warning',i:'⚡',txt:`Cor menos popular (${car.color}) — liquidez menor`}); }
  }

  const level = score===0?'minimal':score<=2?'low':score<=4?'medium':'high';
  const levelLabel = {minimal:'Mínimo',low:'Baixo',medium:'Moderado',high:'Alto'}[level];
  return { score, level, levelLabel, factors };
}

function getRec(margin, risk) {
  if (margin.net === null) return { status:'unknown', label:'Sem FIPE', icon:'❓', css:'unknown' };
  const { net } = margin;
  const t = settings.targetMarkup;
  if (net >= t && (risk.level==='minimal'||risk.level==='low'))  return {status:'buy',   label:'Boa Compra',   icon:'✅', css:'buy'};
  if (net >= t && risk.level==='medium')                          return {status:'check', label:'Verificar',    icon:'⚠️', css:'check'};
  if (net >= t && risk.level==='high')                            return {status:'check', label:'Alto Risco',   icon:'🔴', css:'check'};
  if (net > 0)                                                    return {status:'check', label:'Margem Baixa', icon:'⚡', css:'check'};
  return                                                                 {status:'avoid', label:'Evitar',       icon:'🚫', css:'avoid'};
}

// ─── Skeleton loaders ─────────────────────────────
function showSkeletons(n) {
  const grid = q('#cards-grid');
  grid.innerHTML = Array.from({length:n}, () => `
    <div class="skeleton">
      <div class="skel-photo"></div>
      <div class="skel-body">
        <div class="skel-line" style="height:14px;width:70%"></div>
        <div class="skel-line" style="height:11px;width:45%"></div>
        <div class="skel-line" style="height:28px;width:55%;margin-top:4px"></div>
        <div class="skel-line" style="height:48px;width:100%;border-radius:8px"></div>
      </div>
    </div>`).join('');
}

// ─── Render cards ─────────────────────────────────
function renderCards() {
  const grid = q('#cards-grid');

  if (!filtered.length) {
    grid.innerHTML = `
      <div class="empty-state" id="empty-state">
        <div class="empty-art">
          <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="1"><path d="M5 17H3a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h11l4 4 1 4H5z"/><circle cx="7.5" cy="17.5" r="1.5"/><circle cx="17.5" cy="17.5" r="1.5"/></svg>
        </div>
        <h3>${allListings.length ? 'Nenhum resultado' : 'Nenhum anúncio ainda'}</h3>
        <p>${allListings.length
          ? 'Nenhum anúncio corresponde aos filtros aplicados.'
          : 'Use o formulário acima para buscar carros no Webmotors e iCarros,<br>ou adicione um anúncio manualmente.'}</p>
        ${!allListings.length ? `
        <div class="empty-steps">
          <div class="estep"><span class="estep-num">1</span> Informe marca, modelo e filtros</div>
          <div class="estep"><span class="estep-num">2</span> Clique em <strong>Buscar Carros</strong></div>
          <div class="estep"><span class="estep-num">3</span> Veja a análise de margem e risco</div>
        </div>` : ''}
      </div>`;
    return;
  }

  grid.innerHTML = filtered.map(({car, margin, risk, rec}, idx) =>
    buildCard(car, margin, risk, rec, idx)
  ).join('');

  // Card click → detail
  grid.querySelectorAll('.car-card').forEach(card => {
    card.addEventListener('click', e => {
      if (e.target.closest('.btn-visit') || e.target.closest('.btn-remove')) return;
      const item = filtered.find(i => i.car.id === card.dataset.id);
      if (item) openDetail(item);
    });
  });

  // Delete
  grid.querySelectorAll('.btn-remove').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await api(`/api/listing/${btn.dataset.id}`, { method: 'DELETE' });
      allListings = allListings.filter(c => c.id !== btn.dataset.id);
      render();
      toast('Anúncio removido.', 'info');
    });
  });
}

// ─── Build card HTML ──────────────────────────────
function buildCard(car, margin, risk, rec, idx) {
  const name = [car.brand, car.model].filter(Boolean).join(' ') || 'Sem título';
  const sub  = [car.version, car.year && car.year_model && car.year !== car.year_model
    ? `${car.year}/${car.year_model}`
    : car.year].filter(Boolean).join(' · ');

  const chips = [
    car.km         && `<span class="spec-chip">${km(car.km)} km</span>`,
    car.transmission && `<span class="spec-chip">${x(car.transmission)}</span>`,
    car.fuel       && `<span class="spec-chip">${x(car.fuel)}</span>`,
    car.color      && `<span class="spec-chip">${x(car.color)}</span>`,
  ].filter(Boolean).join('');

  const loc = [car.city, car.state].filter(Boolean).join(' / ');

  // Price + FIPE
  const fipeHTML = margin.fipe
    ? `FIPE <span class="price-fipe-val">${brl(margin.fipe)}</span>
       <span class="${margin.discPct >= 0 ? 'disc-pos' : 'disc-neg'}">
         ${margin.discPct >= 0 ? '▼' : '▲'} ${Math.abs(margin.discPct).toFixed(1)}%
       </span>`
    : `<span class="no-fipe">FIPE não encontrada</span>`;

  // Margin block
  const pct = margin.net !== null
    ? Math.min(100, Math.max(0, (margin.net / (settings.targetMarkup * 2)) * 100))
    : 0;
  const mClass = margin.net === null ? 'unknown'
    : rec.status === 'buy' ? 'positive'
    : rec.status === 'avoid' ? 'negative' : 'warn';
  const mVal   = margin.net !== null ? brl(margin.net) : '—';

  return `
<article class="car-card s-${rec.css}" data-id="${x(car.id)}" style="animation-delay:${idx * 40}ms">
  <div class="card-photo">
    ${car.photo
      ? `<img src="${x(car.photo)}" alt="${x(name)}" loading="lazy" onerror="this.parentNode.innerHTML='<div class=card-photo-placeholder>${carIcon(48)}</div>'" />`
      : `<div class="card-photo-placeholder">${carIcon(48)}</div>`}
    <div class="card-photo-badges">
      <span class="src-badge ${x(car.source)}">${x(car.source_label||car.source)}</span>
      <span class="status-chip ${rec.css}">${rec.icon} ${rec.label}</span>
    </div>
  </div>

  <div class="card-body">
    <div>
      <div class="car-name">${x(name)}</div>
      ${sub ? `<div class="car-sub">${x(sub)}</div>` : ''}
    </div>

    ${chips ? `<div class="specs-row">${chips}</div>` : ''}

    ${loc ? `<div class="card-location">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
      ${x(loc)}</div>` : ''}

    <div class="pricing-block">
      <div class="price-ask">${brl(car.price)}</div>
      <div class="price-fipe-line">${fipeHTML}</div>
    </div>

    <div class="margin-block ${mClass}">
      <div class="margin-top">
        <span class="margin-label-txt">Margem estimada</span>
        <span class="margin-val">${mVal}</span>
      </div>
      <div class="margin-bar"><div class="margin-fill" style="width:${pct}%"></div></div>
      <div class="risk-tag risk-${risk.level === 'minimal' ? 'low' : risk.level}">Risco ${risk.levelLabel}</div>
    </div>
  </div>

  <div class="card-footer">
    <div class="card-footer-left">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      ${car.seller_type === 'PJ' ? 'Loja' : 'Particular'}
    </div>
    <div style="display:flex;gap:6px">
      <a class="btn-visit" href="${x(car.source_url||'#')}" target="_blank" rel="noopener" onclick="event.stopPropagation()">
        Ver anúncio
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </a>
      <button class="btn-remove" data-id="${x(car.id)}" title="Remover">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
  </div>
</article>`;
}

// ─── Detail modal ─────────────────────────────────
function openDetail({ car, margin, risk, rec }) {
  const name = [car.brand, car.model, car.version].filter(Boolean).join(' ');
  const src  = car.source_label || car.source;
  q('#detail-title').textContent = name || 'Detalhes do Veículo';
  q('#detail-sub').textContent   = [car.year && car.year_model ? `${car.year}/${car.year_model}` : car.year, src].filter(Boolean).join(' · ');

  const specsData = [
    ['Marca',         car.brand],
    ['Modelo',        car.model],
    ['Versão',        car.version],
    ['Ano fab./mod.', car.year && car.year_model ? `${car.year}/${car.year_model}` : car.year],
    ['Quilometragem', car.km ? `${km(car.km)} km` : null],
    ['Cor',           car.color],
    ['Câmbio',        car.transmission],
    ['Combustível',   car.fuel],
    ['Localização',   [car.city,car.state].filter(Boolean).join(' / ')],
    ['Nº de donos',   car.owners],
    ['Tipo anunc.',   car.seller_type === 'PJ' ? 'Loja/Dealer' : 'Particular'],
  ].filter(([,v]) => v);

  const specs = specsData.map(([l,v]) => `
    <div class="dspec">
      <span class="dspec-label">${l}</span>
      <span class="dspec-value">${x(String(v))}</span>
    </div>`).join('');

  // Finance table
  const hasFipe = margin.fipe && margin.ask;
  const resClass = rec.status === 'buy' ? 'fin-result-buy' : rec.status === 'avoid' ? 'fin-result-avoid' : 'fin-result-check';

  const finSection = hasFipe ? `
    <div class="dsection-title">Análise Financeira</div>
    <table class="fin-table">
      <tr><td class="ftd-label">Referência FIPE</td>    <td class="ftd-value">${brl(margin.fipe)}</td></tr>
      <tr><td class="ftd-label">(−) Preço anunciado</td><td class="ftd-value">${brl(margin.ask)}</td></tr>
      <tr class="fin-total"><td class="ftd-label">= Margem bruta</td><td class="ftd-value">${brl(margin.gross)}</td></tr>
      <tr>
        <td class="ftd-label">(−) Custos estimados <span style="color:var(--text-3);font-size:11px">(editável)</span></td>
        <td class="ftd-edit"><input type="number" id="d-costs" value="${settings.costs}" min="0" step="100" /></td>
      </tr>
      <tr class="${resClass}">
        <td class="ftd-label">= Margem líquida</td>
        <td class="ftd-value" id="d-net">${brl(margin.net)}</td>
      </tr>
      <tr><td class="ftd-label">Desconto sobre FIPE</td><td class="ftd-value">${margin.discPct?.toFixed(1)}%</td></tr>
    </table>
    <div class="maxbuy-note">
      💡 Para garantir <strong>${brl(settings.targetMarkup)}</strong> de lucro com custos de <strong>${brl(settings.costs)}</strong>,
      o preço máximo de compra é <strong>${brl(margin.maxBuy)}</strong>.
      ${margin.ask <= margin.maxBuy
        ? `<br><strong style="color:var(--buy-d)">✓ Preço anunciado está dentro do limite.</strong>`
        : `<br><strong style="color:var(--avoid-d)">✗ Anúncio supera o limite em ${brl(margin.ask - margin.maxBuy)}.</strong>`}
    </div>` : `
    <div class="dsection-title">Análise Financeira</div>
    <div style="padding:12px;background:var(--check-bg);color:var(--check-text);border-radius:var(--radius);font-size:13px;border:1px solid var(--check-ring)">
      ⚠️ Preço FIPE não encontrado automaticamente. Adicione o valor manualmente no anúncio.
    </div>`;

  // Risk factors
  const riskSection = `
    <div class="dsection-title" style="margin-top:20px">Fatores de Risco — ${risk.levelLabel} (${risk.score} pt)</div>
    <div class="risk-factors">
      ${risk.factors.map(f => `
        <div class="rfactor ${f.t}">
          <span class="rfactor-icon">${f.i}</span>
          <span>${x(f.txt)}</span>
        </div>`).join('')}
    </div>`;

  q('#detail-body').innerHTML = `
    <div class="rec-banner ${rec.css}">
      <span class="rec-icon">${rec.icon}</span>
      <div class="rec-body">
        <span class="rec-label">Recomendação</span>
        <span>${rec.label}</span>
      </div>
      <a class="btn-visit" href="${x(car.source_url||'#')}" target="_blank" rel="noopener" style="margin-left:auto">
        Abrir no ${x(src)}
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </a>
    </div>

    <div class="detail-layout">
      <div>
        <div class="detail-photo">
          ${car.photo
            ? `<img src="${x(car.photo)}" alt="${x(name)}" onerror="this.parentNode.innerHTML='<div class=detail-photo-ph>${carIcon(48)}</div>'" />`
            : `<div class="detail-photo-ph">${carIcon(48)}</div>`}
        </div>
      </div>
      <div class="detail-meta">
        <div class="dsection-title">Especificações</div>
        <div class="detail-specs">${specs}</div>
      </div>
    </div>

    ${finSection}
    ${riskSection}`;

  // Live cost recalc
  const costsInput = q('#d-costs');
  if (costsInput) {
    costsInput.addEventListener('input', () => {
      const c  = +costsInput.value || 0;
      const n  = (margin.gross || 0) - c;
      const el = q('#d-net');
      if (el) el.textContent = brl(n);
    });
  }

  openModal('modal-detail');
}

// ─── Manual add ───────────────────────────────────
async function handleAdd() {
  const price = +q('#add-price').value;
  const brand = q('#add-brand').value.trim();
  const model = q('#add-model').value.trim();
  if (!price || !brand || !model) { toast('Preencha Marca, Modelo e Preço.', 'error'); return; }

  const srcKey = q('#add-source').value;
  const srcLabels = { webmotors:'Webmotors', icarros:'iCarros', facebook:'Facebook', manual:'Manual' };
  const cityRaw = q('#add-city').value.trim();
  const [city, state] = cityRaw.includes('/') ? cityRaw.split('/').map(s=>s.trim()) : [cityRaw,''];

  const listing = {
    brand, model,
    version:      q('#add-version').value.trim(),
    year:         +q('#add-year').value || 0,
    year_model:   +q('#add-year-model').value || 0,
    km:           +q('#add-km').value || 0,
    color:        q('#add-color').value.trim(),
    transmission: q('#add-transmission').value,
    fuel:         q('#add-fuel').value,
    price,
    fipe_price:   +q('#add-fipe').value || null,
    source:       srcKey,
    source_label: srcLabels[srcKey] || 'Manual',
    source_url:   q('#add-url').value.trim() || '#',
    city, state,
    owners:       +q('#add-owners').value || 1,
    risk_flags:   { auction: q('#add-flag-auction').checked, recall: q('#add-flag-recall').checked },
    liquidity: 'media',
  };

  const btn = q('#btn-save-add');
  btn.disabled = true; btn.textContent = 'Salvando…';

  try {
    const { listing: saved } = await api('/api/listing/add', { method:'POST', body: listing });
    allListings.unshift(saved);
    render();
    closeModal('modal-add');
    toast('Anúncio adicionado!', 'success');
    clearAddForm();
  } catch(err) { toast(`Erro: ${err.message}`, 'error');
  } finally { btn.disabled = false; btn.textContent = 'Salvar anúncio'; }
}

function clearAddForm() {
  ['add-brand','add-model','add-version','add-year','add-year-model','add-km',
   'add-color','add-price','add-fipe','add-city','add-url'].forEach(id => {
    const el = document.getElementById(id); if(el) el.value = '';
  });
  q('#add-owners').value = '1';
  q('#add-flag-auction').checked = q('#add-flag-recall').checked = false;
}

// ─── Settings UI ──────────────────────────────────
function syncSettingsUI() {
  q('#cfg-costs').value  = settings.costs;
  q('#cfg-markup').value = settings.targetMarkup;
  updateFormulaDisplay();
}
function updateFormulaDisplay() {
  const total = (+q('#cfg-costs').value||0) + (+q('#cfg-markup').value||0);
  q('#cfg-total-deduction').textContent = num(total);
}

// ─── Modal helpers ────────────────────────────────
function openModal(id)  { document.getElementById(id)?.classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id)?.classList.add('hidden');    }

// ─── API ──────────────────────────────────────────
async function api(url, opts={}) {
  const res = await fetch(url, {
    method: opts.method || 'GET',
    headers: opts.body ? {'Content-Type':'application/json'} : undefined,
    body:    opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) { const t = await res.text().catch(()=>''); throw new Error(`HTTP ${res.status}: ${t}`); }
  return res.json();
}

// ─── Toast ────────────────────────────────────────
let _tt;
function toast(msg, type='info') {
  const el = q('#toast');
  el.textContent = msg; el.className = `toast ${type}`;
  el.classList.remove('hidden');
  clearTimeout(_tt);
  _tt = setTimeout(() => el.classList.add('hidden'), 3500);
}

// ─── Formatters ───────────────────────────────────
const brl = v => v == null ? '—' : new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL',maximumFractionDigits:0}).format(v);
const km  = v => new Intl.NumberFormat('pt-BR').format(v);
const num = v => new Intl.NumberFormat('pt-BR').format(v);

// ─── Utils ────────────────────────────────────────
const q  = s => document.querySelector(s);
const qq = s => document.querySelectorAll(s);
const x  = s => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const carIcon = (s=48) =>
  `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M5 17H3a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h11l4 4 1 4H5z"/><circle cx="7.5" cy="17.5" r="1.5"/><circle cx="17.5" cy="17.5" r="1.5"/></svg>`;
