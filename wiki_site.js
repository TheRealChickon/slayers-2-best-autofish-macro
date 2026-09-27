(() => {
  'use strict';
  const data = window.WIKI_DATA || {};
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const asset = file => file ? 'assets/' + String(file).split('/').map(encodeURIComponent).join('/') : '';
  const first = (name) => (data.inventory || []).find(x => x.name === name);
  const pageNames = {field:'Build',satchel:'Inventory',archive:'Archive',bosses:'Bosses'};
  let page = pageNames[location.hash.slice(1)] ? location.hash.slice(1) : 'field', query = '', chosen = null;
  const damage = data.damage_build || {};
  const bosses = data.boss_analysis || {};
  const economy = bosses.economy || {};
  const num = n => Number.isFinite(Number(n)) ? Number(n).toLocaleString('en-US', {maximumFractionDigits:1}) : '—';

  function showImage(file) {
    if (!file) return;
    $('large-image').src = asset(file);
    $('image-dialog').showModal();
  }

  function itemButton(x, index) {
    const rarity = esc(x.rarity || 'Unknown');
    return `<button class="item-tile ${chosen === x ? 'active' : ''}" data-index="${index}" title="${esc(x.name)} · ${rarity}">
      <img loading="lazy" src="${asset(x.icon)}" alt=""><span class="name">${esc(x.name)}</span>
      ${x.quantity > 1 ? `<span class="qty">×${num(x.quantity)}</span>` : ''}
      ${x.refinement ? `<span class="ref">+${num(x.refinement)}</span>` : ''}</button>`;
  }

  function detail(x) {
    if (!x) return '<div class="detail-empty">Select an item to see its stats.</div>';
    const owned = x.source === 'inventory';
    const list = (values, className='') => (values || []).map(y => `<div class="stat-row ${className}"><span>${esc(y)}</span></div>`).join('') || '<p>None shown</p>';
    return `<div class="detail-head"><img src="${asset(x.icon)}" alt=""><div><div class="detail-kicker">${owned ? `In satchel${x.equipped ? ' / equipped' : ''}` : 'Archive reference'} · ${esc(x.rarity || 'unknown')}</div><h3>${esc(x.name)}${x.refinement ? ` +${num(x.refinement)}` : ''}</h3></div></div>
      <p>${esc((x.description || []).join(' '))}</p>
      <h4>${owned ? 'Your displayed stats' : 'Archive base stats'}</h4>${list(x.stats)}
      ${x.archive_stats?.length ? `<h4>Unrefined archive reference</h4>${list(x.archive_stats, 'base')}` : ''}
      ${x.source_info?.length ? `<h4>Source</h4><p>${esc(x.source_info.join(' · '))}</p>` : ''}
      <div class="detail-actions"><button data-image="${esc(x.detail_image || '')}">DETAIL CAPTURE ↗</button>${x.archive_detail_image ? `<button data-image="${esc(x.archive_detail_image)}">BASE CAPTURE ↗</button>` : ''}</div>`;
  }

  function inventory(archive=false) {
    const items = archive ? data.archive_only || [] : data.inventory || [];
    const result = items.filter(x => `${x.name} ${(x.stats||[]).join(' ')} ${x.rarity||''}`.toLowerCase().includes(query.toLowerCase()));
    if (chosen && !result.includes(chosen)) chosen = null;
    return `<div class="intro"><div><span class="eyebrow">${archive ? 'UNOWNED · BASE STATS' : 'OWNED · YOUR STATS'}</span><h2>${archive ? 'Items you have not found' : 'Your items'}</h2></div><p>${archive ? 'Archive entries shown only when the item was absent from your inventory capture.' : 'Select an item for its captured stats, refinement, and original screenshot.'}</p></div>
      <div class="summary-strip"><div class="summary-stat"><b>${num(items.length)}</b><span>${archive ? 'Archive entries' : 'Item variants'}</span></div>${archive ? '' : `<div class="summary-stat"><b>${num((data.inventory||[]).filter(x=>x.equipped).length)}</b><span>Equipped</span></div>`}</div>
      <div class="inventory-layout"><section><label class="search-bar"><span aria-hidden="true">⌕</span><input id="item-search" type="search" placeholder="Search names, stats, rarity" value="${esc(query)}" autocomplete="off"></label><div class="inventory-meta"><span>${num(result.length)} SHOWN</span><span>${archive ? 'BASE REFERENCE' : 'LIVE INVENTORY'}</span></div><div class="item-grid" id="item-grid">${result.map(itemButton).join('')}</div></section><aside class="detail-panel" id="detail-panel">${detail(chosen)}</aside></div>`;
  }

  function slot(name) {
    const x = first(name);
    return `<div class="slot"><div class="slot-icon">${x ? `<img src="${asset(x.icon)}" alt="">` : ''}</div><div class="slot-name">${esc(name)}</div></div>`;
  }

  function field() {
    const c = damage.calibration || {}, p = data.profile || {};
    const statItems = damage.stat_items || [];
    const weapon = first(damage.weapon);
    const summary = bosses.summary || {};
    const top = (bosses.bosses || []).slice(0,5);
    return `<div class="intro"><div><span class="eyebrow">${esc(p.clan||'CHARACTER')} · DAMAGE</span><h2>Current best damage setup</h2></div><p>Measured from your recording and the gear you own.</p></div>
      <div class="field-grid"><section class="featured"><div class="featured-top"><span class="eyebrow">M1 HIT · RECORDED</span><span class="micro">GAUNTLET MASTERY ${esc(c.mastery||'—')}</span></div><h3>${esc(damage.weapon || 'Gauntlet')} ${weapon?.refinement ? '+'+num(weapon.refinement) : ''}</h3><p>Best measured M1 set among your owned items.</p><div class="hit">${esc(c.m1||'—')}<small> damage</small></div><div class="micro">${esc(c.damage_factor||'—')}× factor · +${esc(c.additional_damage||'—')} additional damage</div><div class="slot-list">${statItems.map(slot).join('')}</div></section>
      <section><span class="eyebrow">BOSS FIGHTS · 32 MIN RECORDING</span><h2 style="font-size:24px;margin:5px 0 12px">Time to kill</h2><table class="ledger-table"><thead><tr><th>Boss</th><th>Median</th></tr></thead><tbody>${top.map(x=>`<tr><td>${esc(x.name)}</td><td>${num(x.median_seconds)}s</td></tr>`).join('')}</tbody></table><div class="field-note"><strong>${summary.overall_median_seconds ? `${num(summary.overall_median_seconds)}s typical fight` : 'Timed boss fights'}</strong><p>${num(summary.solo_fights)} clean solo-credit kills. Fight times exclude travel and waiting.</p>${economy.estimated_wen_per_hour ? `<p><b>≈${num(economy.estimated_wen_per_hour)} Wen/hour</b> at the full recorded pace, with redeemed pouches and without 2× Wen.</p>` : ''}</div></section></div>
      <div class="rule"></div><div class="intro"><div><span class="eyebrow">OWNED GEAR</span><h2>Equip this set</h2></div></div>
      <div class="field-grid"><section>${[damage.weapon,...statItems].filter(Boolean).map((name,i)=>{const x=first(name);return `<div class="loadout-row">${x?`<img src="${asset(x.icon)}" alt="">`:''}<div><small>${i===0?'WEAPON':'STATS SLOT '+i}</small><strong>${esc(name)}${x?.refinement?' +'+num(x.refinement):''}</strong></div></div>`}).join('')}</section><aside class="field-note"><strong>Why this set</strong><p>${esc((damage.tests||[])[0]||'Measured M1 comparisons favor this owned set.')}</p><details class="build-details"><summary>Mastery and Shockwave notes</summary><p>At mastery 202 the recording shows a 64.78 M1 hit with the same displayed +35.888 damage and 1.461× factor. Earlier 183–186 tests showed roughly +0.0365 displayed M1 per mastery level. Keep the same gear when using that projection.</p><p>Shockwave shows 37.57 and 38.23 per-hit examples at Shockwave mastery 206. Total damage depends on how many hits connect.</p></details></aside></div>
      ${p.equipped_hud_image ? `<details class="capture-details"><summary>View captured HUD</summary><img class="profile-shot" data-image="${esc(p.equipped_hud_image)}" src="${asset(p.equipped_hud_image)}" alt="Captured equipped HUD"></details>` : ''}`;
  }

  function bossPage() {
    const rows = bosses.bosses || [];
    const summary = bosses.summary || {};
    const maximum = Math.max(50, ...rows.map(x=>x.median_seconds||0));
    return `<div class="intro"><div><span class="eyebrow">RECORDED FIGHTS</span><h2>Boss times and Wen</h2></div><p>3,000 HP per boss. Times run from engagement to despawn; shared-damage fights were excluded.</p></div>
      <div class="summary-strip"><div class="summary-stat"><b>${num(summary.overall_median_seconds)}s</b><span>Typical clean kill</span></div><div class="summary-stat"><b>${num(summary.solo_fights)}</b><span>Solo-credit kills</span></div><div class="summary-stat"><b>${economy.estimated_wen_per_hour ? Math.round(economy.estimated_wen_per_hour/1000)+'k' : '—'}</b><span>Wen/hour · no 2×</span></div></div>
      <div class="boss-layout"><section><div class="eyebrow">MEDIAN ENGAGED TIME / SHORTER IS FASTER</div>${rows.map(x=>`<div class="boss-row"><div><div class="boss-name">${esc(x.name)}</div><div class="boss-range">${num(x.count)} clean ${x.count===1?'kill':'kills'}</div></div><div class="boss-track"><div class="boss-fill" style="width:${Math.max(2,100*(x.median_seconds||0)/maximum)}%"></div></div><div class="boss-time">${num(x.median_seconds)}s</div></div>`).join('')}${economy.estimated_wen_per_hour ? `<div class="field-note"><strong>${num(economy.estimated_wen_per_hour)} Wen/hour without 2×</strong><p>${num(economy.base_wen_per_boss)} base Wen + ${num(economy.coin_pouch_wen_per_boss)} from one coin pouch = ${num(economy.wen_per_boss_without_2x)} Wen per kill. ${num(economy.clean_kills)} clean kills over ${num(economy.recording_seconds/60)} minutes gives ${num(economy.clean_kills_per_hour)} kills/hour. This is gross pouch value, assuming you redeem them; the full video includes travel, menus, and waits.</p></div>` : ''}<div class="field-note"><strong>What the numbers mean</strong><p>These are your observed kills, not a promise for every attempt. Knockback, skill misses, terrain, mastery, and another player can change the result. Video timing is sampled every three seconds, so each time is approximate.</p></div></section>
      <aside class="boss-side"><div class="eyebrow">DAMAGE READOUT</div><h3>Per-hit anchors</h3><p><b>Gauntlet M1</b> 64.78 at mastery 202 in the recording.</p><p><b>Shockwave</b> examples of 37.57 and 38.23 per tick at Shockwave mastery 206. Total depends on landed ticks.</p><p><b>Other visible hits</b> vary from about 60 to 78; the video does not reliably identify a named skill for each.</p><p>Kill pace combines these attacks, movement and recovery. Dividing 3,000 HP by M1 alone would overstate the time.</p><div class="evidence">${(bosses.evidence||[]).map(x=>`<button data-image="${esc(x.file)}" title="Open capture at ${esc(x.time)}"><img src="${asset(x.file)}" alt="Boss fight at ${esc(x.time)}"><span>${esc(x.time)}</span></button>`).join('')}</div><div class="micro">Click a frame for the original capture.</div></aside></div>`;
  }

  function bindImages(root=$('view')) {
    root.querySelectorAll('[data-image]').forEach(node => node.addEventListener('click', () => showImage(node.dataset.image)));
  }

  function render() {
    $('page-title').textContent = pageNames[page];
    document.querySelectorAll('.nav-link').forEach(button => {button.classList.toggle('active',button.dataset.page===page);button.setAttribute('aria-current',button.dataset.page===page?'page':'false')});
    $('view').innerHTML = page==='satchel'?inventory(false):page==='archive'?inventory(true):page==='bosses'?bossPage():field();
    bindImages();
    if(page==='satchel'||page==='archive') {
      const input=$('item-search');
      input.addEventListener('input', () => {query=input.value;chosen=null;const start=input.selectionStart;render();$('item-search').focus();$('item-search').setSelectionRange(start,start)});
      $('item-grid').querySelectorAll('.item-tile').forEach(button=>button.addEventListener('click',()=>{const source=page==='archive'?data.archive_only:data.inventory;const found=source.filter(x=>`${x.name} ${(x.stats||[]).join(' ')} ${x.rarity||''}`.toLowerCase().includes(query.toLowerCase()));chosen=found[Number(button.dataset.index)];render()}));
    }
  }
  document.querySelectorAll('.nav-link').forEach(button=>button.addEventListener('click',()=>{page=button.dataset.page;location.hash=page;query='';chosen=null;render();window.scrollTo({top:0,behavior:'smooth'})}));
  window.addEventListener('hashchange',()=>{const target=location.hash.slice(1);if(pageNames[target]&&target!==page){page=target;query='';chosen=null;render()}});
  $('close-image').addEventListener('click',()=>$('image-dialog').close());
  $('image-dialog').addEventListener('click',event=>{if(event.target===$('image-dialog'))$('image-dialog').close()});
  $('capture-stamp').textContent='CAPTURED '+String(data.captured_at||'').slice(0,16);
  render();
})();
