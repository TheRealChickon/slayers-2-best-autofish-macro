(() => {
  'use strict';
  const data = window.WIKI_DATA || {};
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const asset = file => file ? 'assets/' + String(file).split('/').map(encodeURIComponent).join('/') : '';
  const num = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-US',{maximumFractionDigits:1}) : '—';
  const first = name => (data.inventory || []).find(item => item.name === name);
  const pageNames = {satchel:'Inventory',archive:'Archive',field:'Build',bosses:'Bosses'};
  const damage = data.damage_build || {};
  const bosses = data.boss_analysis || {};
  const economy = bosses.economy || {};
  let page = pageNames[location.hash.slice(1)] ? location.hash.slice(1) : 'satchel';
  let query = '', filter = 'all', chosen = page === 'satchel' ? (data.inventory || [])[0] || null : null;
  let detailOpen = false;

  function showImage(file) {
    if (!file) return;
    $('large-image').src = asset(file);
    $('image-dialog').showModal();
  }

  function collectionItems() { return page === 'archive' ? data.archive_only || [] : data.inventory || []; }
  function shownItems() {
    return collectionItems().filter(item =>
      (filter !== 'equipped' || item.equipped) &&
      `${item.name} ${(item.stats || []).join(' ')} ${item.rarity || ''}`.toLowerCase().includes(query.toLowerCase()));
  }

  function itemButton(item,index) {
    const rarity = String(item.rarity || 'common').toLowerCase().replace(/[^a-z]/g,'');
    const label = `${item.name}${item.refinement ? ` +${item.refinement}` : ''}${item.quantity > 1 ? `, quantity ${item.quantity}` : ''}${item.equipped ? ', equipped' : ''}`;
    return `<button type="button" class="item-tile rarity-${rarity}${chosen === item ? ' active' : ''}" data-index="${index}" aria-label="${esc(label)}" title="${esc(label)}">
      <img loading="lazy" src="${asset(item.icon)}" alt="">${item.equipped ? '<span class="equipped-mark" aria-hidden="true">✓</span>' : ''}</button>`;
  }

  function detail(item) {
    if (!item) return '<div class="detail-empty">Select an item.</div>';
    const owned = item.source === 'inventory';
    const list = values => (values || []).map(value => `<div class="stat-row">${esc(value)}</div>`).join('') || '<div class="stat-empty">No stat line shown</div>';
    return `<button type="button" class="detail-close" aria-label="Close item details">×</button>
      <div class="detail-title"><img src="${asset(item.icon)}" alt=""><div><h2>${esc(item.name)}${item.refinement ? ` +${num(item.refinement)}` : ''}</h2><div class="rarity-label rarity-text-${String(item.rarity||'common').toLowerCase().replace(/[^a-z]/g,'')}">${esc(item.rarity || 'Unknown')}${item.equipped ? ' · Equipped' : ''}</div></div></div>
      <p class="item-description">${esc((item.description || []).join(' '))}</p>
      <div class="detail-section"><h3>${owned ? 'Your stats' : 'Archive base stats'}</h3>${list(item.stats)}</div>
      ${item.archive_stats?.length ? `<div class="detail-section base-stats"><h3>Unrefined archive stats</h3>${list(item.archive_stats)}</div>` : ''}
      ${item.source_info?.length ? `<div class="detail-section"><h3>Source</h3><p>${esc(item.source_info.join(' · '))}</p></div>` : ''}
      <div class="detail-actions"><button type="button" data-image="${esc(item.detail_image || '')}">View item capture ↗</button>${item.archive_detail_image ? `<button type="button" data-image="${esc(item.archive_detail_image)}">View base capture ↗</button>` : ''}</div>`;
  }

  function inventory() {
    const archive = page === 'archive';
    const items = collectionItems();
    const shown = shownItems();
    if (chosen && !shown.includes(chosen)) { chosen = null; detailOpen = false; }
    return `<div class="collection-tools">
      <div class="collection-filters">
        <button type="button" data-filter="all" class="${filter === 'all' ? 'selected' : ''}" aria-pressed="${filter === 'all'}">${archive ? 'Archive only' : 'All'} <span>${num(items.length)}</span></button>
        ${archive ? '' : `<button type="button" data-filter="equipped" class="${filter === 'equipped' ? 'selected' : ''}" aria-pressed="${filter === 'equipped'}">Equipped <span>${num(items.filter(x=>x.equipped).length)}</span></button>`}
      </div>
      <label class="search-bar"><span aria-hidden="true">⌕</span><input id="item-search" type="search" placeholder="Item name or stat" value="${esc(query)}" autocomplete="off" aria-label="Search items"></label>
    </div>
    <div class="collection-caption">${archive ? 'Unowned items · unrefined base values' : 'Your captured inventory · refined values shown separately'} <span>${num(shown.length)} shown</span></div>
    <div class="inventory-layout"><div class="item-grid" id="item-grid">${shown.map(itemButton).join('') || '<p class="no-results">No matching items.</p>'}</div><aside class="detail-panel${detailOpen ? ' open' : ''}" id="detail-panel">${detail(chosen)}</aside></div>
    ${detailOpen ? '<button type="button" class="detail-scrim" aria-label="Close item details"></button>' : ''}`;
  }

  function gearItem(name,index) {
    const item = first(name);
    return `<div class="gear-item">${item ? `<img src="${asset(item.icon)}" alt="">` : '<div class="gear-missing"></div>'}<div><span>${index === 0 ? 'Weapon' : `Stats ${index}`}</span><strong>${esc(name)}${item?.refinement ? ` +${num(item.refinement)}` : ''}</strong></div></div>`;
  }

  function build() {
    const profile = data.profile || {}, c = damage.calibration || {};
    const loadout = [damage.weapon,...(damage.stat_items || [])].filter(Boolean);
    const hud = profile.equipped_hud_image;
    return `<div class="build-layout"><section class="loadout"><div class="section-line"><h2>Measured loadout</h2><span>Gauntlet mastery ${esc(c.mastery || '—')}</span></div>
      <div class="gear-list">${loadout.map(gearItem).join('')}</div></section>
      <aside class="damage-readout"><div class="readout-label">M1 DAMAGE · SAME GEAR</div><div class="readout-number">${esc(c.m1 || '—')}</div><div class="readout-meta">${esc(c.damage_factor || '—')}× factor <span>·</span> +${esc(c.additional_damage || '—')} additional damage</div>
      <div class="comparison"><span>Horns II / measured</span><b>64.15</b><span>Flame Amigasa / measured</span><b>62.57</b></div></aside></div>
      <div class="build-followup"><div><h2>Still worth testing</h2><p>Serpent Haori and Flame Haori Style 1 each show a 1.07× factor. Neither was measured as a one-item swap against Stone Haori. A displayed factor alone cannot rank their real hit damage.</p></div>
      <div><h2>Mastery and skills</h2><p>At mastery 202, the recording shows a 64.78 M1 hit with the same gear. Shockwave ticks shown at mastery 206 were 37.57 and 38.23; total skill damage depends on how many ticks land.</p></div></div>
      ${hud ? `<details class="capture-details"><summary>Show captured HUD</summary><img class="profile-shot" data-image="${esc(hud)}" src="${asset(hud)}" alt="Captured equipped HUD"></details>` : ''}
      <button type="button" class="text-jump" data-go="bosses">Boss fight timings →</button>`;
  }

  function bossPage() {
    const rows = bosses.bosses || [];
    const summary = bosses.summary || {};
    return `<div class="boss-overview"><div><span>Typical clean fight</span><strong>${num(summary.overall_median_seconds)}s</strong></div><div><span>Solo-credit kills</span><strong>${num(summary.solo_fights)}</strong></div><div><span>Wen/hour · no 2×</span><strong>${economy.estimated_wen_per_hour_min ? `${num(economy.estimated_wen_per_hour_min)}–${num(economy.estimated_wen_per_hour_max)}` : '—'}</strong></div></div>
      <div class="boss-layout"><section class="boss-list"><div class="boss-list-head"><span>Boss</span><span>Clean kills</span><span>Median fight</span></div>${rows.map(row=>`<div class="boss-row"><strong>${esc(row.name)}</strong><span>${num(row.count)}</span><b>${num(row.median_seconds)}s</b></div>`).join('')}</section>
      <aside class="boss-notes"><h2>Wen calculation</h2><p>${num(economy.base_wen_per_boss)} Wen reward + ${num(economy.coin_pouches_per_boss_min)}–${num(economy.coin_pouches_per_boss_max)} pouches at ${num(economy.coin_pouch_wen_each)} Wen each = <b>${num(economy.wen_per_boss_without_2x_min)}–${num(economy.wen_per_boss_without_2x_max)} Wen per boss.</b></p>
      <p>${num(economy.clean_kills)} clean kills in ${num(economy.recording_seconds/60)} minutes. The hourly range assumes that pace and that every pouch is redeemed. The 2–5 pouch count is your report, not a measured average.</p>
      <details><summary>Timing method and damage notes</summary><p>All recorded bosses have 3,000 HP. Fight time runs from first engagement to despawn. Shared-damage and incomplete fights were excluded. Video sampling was every three seconds, so timings are approximate.</p><p>Gauntlet M1 was 64.78 at mastery 202. Shockwave examples were 37.57 and 38.23 per tick at mastery 206; other hit numbers could not be assigned confidently to named skills.</p></details>
      <details class="evidence-details"><summary>Video frames</summary><div class="evidence">${(bosses.evidence || []).map(frame=>`<button type="button" data-image="${esc(frame.file)}" title="Frame at ${esc(frame.time)}"><img src="${asset(frame.file)}" alt="Boss fight at ${esc(frame.time)}"><span>${esc(frame.time)}</span></button>`).join('')}</div></details></aside></div>`;
  }

  function closeDetails() {
    detailOpen=false;
    render();
    const index=shownItems().indexOf(chosen);
    if (index >= 0) $('item-grid')?.querySelector(`[data-index="${index}"]`)?.focus({preventScroll:true});
  }

  function render() {
    $('page-title').textContent = pageNames[page];
    document.title = `${pageNames[page]} · Grofheyse3729`;
    document.querySelectorAll('.nav-link').forEach(button => {
      const active = button.dataset.page === page;
      button.classList.toggle('active',active);
      button.setAttribute('aria-current',active ? 'page' : 'false');
    });
    $('view').innerHTML = page === 'satchel' || page === 'archive' ? inventory() : page === 'field' ? build() : bossPage();
    $('view').querySelectorAll('[data-image]').forEach(button => button.addEventListener('click',() => showImage(button.dataset.image)));
    $('view').querySelectorAll('[data-go]').forEach(button => button.addEventListener('click',() => navigate(button.dataset.go)));
    if (page === 'satchel' || page === 'archive') {
      const search = $('item-search');
      search.addEventListener('input',() => {
        query = search.value; detailOpen = false;
        const cursor = search.selectionStart;
        render(); $('item-search').focus();
        if (cursor !== null) $('item-search').setSelectionRange(cursor,cursor);
      });
      $('view').querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click',() => {filter=button.dataset.filter;detailOpen=false;render();}));
      const shown = shownItems();
      $('item-grid').querySelectorAll('[data-index]').forEach(button => button.addEventListener('click',() => {chosen=shown[Number(button.dataset.index)];detailOpen=true;render();}));
      $('view').querySelector('.detail-close')?.addEventListener('click',closeDetails);
      $('view').querySelector('.detail-scrim')?.addEventListener('click',closeDetails);
      if (detailOpen && window.matchMedia('(max-width:760px)').matches) {
        const panel=$('detail-panel');
        panel.setAttribute('role','dialog');
        panel.setAttribute('aria-modal','true');
        panel.setAttribute('aria-label',`${chosen?.name || 'Item'} details`);
        panel.querySelector('.detail-close')?.focus({preventScroll:true});
      }
    }
  }

  function navigate(target) {
    if (!pageNames[target]) return;
    page=target;query='';filter='all';detailOpen=false;
    chosen=target === 'satchel' ? (data.inventory || [])[0] || null : null;
    location.hash=target;render();window.scrollTo(0,0);
  }

  document.querySelectorAll('.nav-link').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.page)));
  window.addEventListener('hashchange',()=>{const target=location.hash.slice(1);if(pageNames[target] && target !== page) navigate(target);});
  document.addEventListener('keydown',event=>{if(event.key === 'Escape' && detailOpen) closeDetails();});
  $('close-image').addEventListener('click',()=>$('image-dialog').close());
  $('image-dialog').addEventListener('click',event=>{if(event.target===$('image-dialog'))$('image-dialog').close();});
  $('capture-stamp').textContent='NOTES UPDATED '+String(data.captured_at||'').slice(0,16);
  render();
})();
