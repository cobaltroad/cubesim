'use strict';

// ─────────────────────────────────────────────────────────────
// Router
// ─────────────────────────────────────────────────────────────

function route() {
  const hash = location.hash || '#/';
  const app  = document.getElementById('app');

  const poolMatch  = hash.match(/^#\/draft\/([^/]+)\/pool$/);
  const draftMatch = hash.match(/^#\/draft\/([^/]+)$/);

  if (poolMatch)        renderPool(app, poolMatch[1]);
  else if (draftMatch)  renderDraft(app, draftMatch[1]);
  else                  renderLanding(app);
}

window.addEventListener('hashchange', route);
window.addEventListener('load', route);


// ─────────────────────────────────────────────────────────────
// API helpers
// ─────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res  = await fetch(path, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}


// ─────────────────────────────────────────────────────────────
// Tooltip
// ─────────────────────────────────────────────────────────────

const tooltip = document.getElementById('tooltip');

function showTooltip(card, x, y) {
  const pt = (card.power != null && card.toughness != null)
    ? `${card.power}/${card.toughness}` : '';
  tooltip.innerHTML = `
    <div class="tooltip-name">${esc(card.name)}</div>
    ${ card.mana_cost ? `<div class="tooltip-mana">${esc(card.mana_cost)}</div>` : '' }
    ${ card.type_line ? `<div class="tooltip-type">${esc(card.type_line)}</div>` : '' }
    ${ card.oracle_text ? `<div class="tooltip-oracle">${esc(card.oracle_text)}</div>` : '' }
    ${ pt ? `<div class="tooltip-pt">${esc(pt)}</div>` : '' }
  `;
  tooltip.style.display = 'block';
  positionTooltip(x, y);
}

function positionTooltip(x, y) {
  const tw = tooltip.offsetWidth;
  const th = tooltip.offsetHeight;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  tooltip.style.left = Math.min(x + 12, vw - tw - 8) + 'px';
  tooltip.style.top  = Math.min(y + 12, vh - th - 8) + 'px';
}

function hideTooltip() {
  tooltip.style.display = 'none';
}

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}


// ─────────────────────────────────────────────────────────────
// Card image
// ─────────────────────────────────────────────────────────────

function cardImg(card, cls = '') {
  const img = document.createElement('img');
  img.alt   = card.name;
  img.src   = `/api/images/${card.id}`;
  img.setAttribute('data-fallback', card.image_uri_normal || '');
  img.addEventListener('error', () => {
    if (!img.getAttribute('data-fallback-used')) {
      img.setAttribute('data-fallback-used', '1');
      const fb = img.getAttribute('data-fallback');
      if (fb) img.src = fb;
    }
  });
  if (cls) img.className = cls;
  return img;
}


// ─────────────────────────────────────────────────────────────
// Landing view
// ─────────────────────────────────────────────────────────────

function renderLanding(app) {
  const div = document.createElement('div');
  div.className = 'landing';

  div.innerHTML = `
    <div class="landing-hero">
      <h1>Commander Cube Draft</h1>
      <p class="tagline">Draft a 75-card pool from a curated Commander cube against three AI opponents.</p>
    </div>

    <div class="how-it-works">
      <h2>How it works</h2>
      <ol class="steps">
        <li>
          <strong>Commander Pack</strong>
          15 cards drawn from the Commander pool. Pick 1 card per pass as packs rotate left. Choose your Commander here.
        </li>
        <li>
          <strong>Packs 2–4</strong>
          20 cards drawn from the main deck pool. Pick 2 cards per pass. Direction alternates each pack.
        </li>
        <li>
          <strong>Your Pool</strong>
          75 cards total. Download your pool at the end and import it into Moxfield to build your deck.
        </li>
      </ol>
      <div class="draft-details">
        <span>4 players (you + 3 AI)</span>
        <span>·</span>
        <span>4 packs</span>
        <span>·</span>
        <span>75 cards</span>
      </div>
    </div>

    <div class="landing-cta">
      <button class="btn-start" id="start-draft-btn">Start Draft</button>
      <p class="cta-note">Building a new pool takes a few seconds.</p>
    </div>
  `;

  app.innerHTML = '';
  app.appendChild(div);

  div.querySelector('#start-draft-btn').addEventListener('click', async () => {
    const btn = div.querySelector('#start-draft-btn');
    btn.disabled    = true;
    btn.textContent = 'Building pool…';
    try {
      const draft = await api('POST', '/api/drafts');
      location.hash = `#/draft/${draft.name}`;
    } catch (e) {
      alert(`Failed to create draft: ${e.message}`);
      btn.disabled    = false;
      btn.textContent = 'Start Draft';
    }
  });
}


// ─────────────────────────────────────────────────────────────
// Draft view
// ─────────────────────────────────────────────────────────────

// Per-draft UI state
const draftUI = {
  selected: new Set(),
  submitting: false,
};

async function renderDraft(app, draftName) {
  app.innerHTML = '<div class="loading">Loading draft…</div>';
  let state;
  try {
    state = await api('GET', `/api/drafts/${draftName}`);
  } catch (e) {
    app.innerHTML = `<div class="error-msg">Error: ${esc(e.message)}</div>`;
    return;
  }

  if (state.status === 'complete') {
    location.replace(`#/draft/${draftName}/pool`);
    return;
  }

  if (state.status === 'not_started') {
    renderStartScreen(app, draftName, state);
    return;
  }

  renderDraftInProgress(app, draftName, state);
}

function renderStartScreen(app, draftName, state) {
  app.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'start-screen';
  div.innerHTML = `
    <h2>Draft Ready</h2>
    <p>${esc(draftName)}</p>
    <p>4 players · 4 packs · You are Player 1</p>
    <button class="btn-success" id="start-btn">Start Draft</button>
    <a href="#/">← Back</a>
  `;
  app.appendChild(div);

  div.querySelector('#start-btn').addEventListener('click', async () => {
    div.querySelector('#start-btn').disabled = true;
    try {
      const s = await api('POST', `/api/drafts/${draftName}/start`);
      renderDraftInProgress(app, draftName, s);
    } catch (e) {
      alert(`Error: ${e.message}`);
      div.querySelector('#start-btn').disabled = false;
    }
  });
}

function renderDraftInProgress(app, draftName, state) {
  draftUI.selected.clear();
  draftUI.submitting = false;

  app.innerHTML = '';

  const layout = document.createElement('div');
  layout.className = 'draft-layout';

  // Header
  const n = state.picks_per_pass;
  const header = document.createElement('div');
  header.className = 'draft-header';
  header.innerHTML = `
    <h2>${state.current_pack === 1 ? 'Commander Pack' : `Pack ${state.current_pack}`}</h2>
    <span class="meta">Pass ${state.current_pass}</span>
    <span class="meta">${state.current_pack_cards.length} cards in pack</span>
    <span class="meta">Pick ${n - state.human_picks_remaining + 1} of ${n}</span>
    <span class="spacer"></span>
    <button class="btn-drafted" id="toggle-drafted-btn">Drafted (${state.drafted_human.length})</button>
    <a href="#/" style="color:#aaa;font-size:0.85rem">← Drafts</a>
  `;

  // Pack area
  const packArea = document.createElement('div');
  packArea.className = 'pack-area';

  const pickLabel = document.createElement('div');
  pickLabel.style.cssText = 'padding: 0 4px 12px; font-size: 0.85rem; color: #aaa;';
  if (n === 1) {
    pickLabel.textContent = 'Click a card to pick it.';
  } else {
    pickLabel.textContent = `Select ${state.human_picks_remaining} card${state.human_picks_remaining > 1 ? 's' : ''}, then confirm.`;
  }

  const grid = document.createElement('div');
  grid.className = 'card-grid';

  state.current_pack_cards.forEach(card => {
    const item = document.createElement('div');
    item.className   = 'card-item';
    item.dataset.id  = card.id;
    item.appendChild(cardImg(card));

    item.addEventListener('mouseenter', e => showTooltip(card, e.clientX, e.clientY));
    item.addEventListener('mousemove',  e => positionTooltip(e.clientX, e.clientY));
    item.addEventListener('mouseleave', hideTooltip);

    item.addEventListener('click', () => handleCardClick(item, card, draftName, state, app));
    grid.appendChild(item);
  });

  packArea.appendChild(pickLabel);
  packArea.appendChild(grid);

  // Confirm button for multi-pick passes
  if (n > 1) {
    const confirmBtn = document.createElement('button');
    confirmBtn.className   = 'btn-primary';
    confirmBtn.id          = 'confirm-pick-btn';
    confirmBtn.disabled    = true;
    confirmBtn.style.cssText = 'margin-top: 16px; width: 100%;';
    confirmBtn.textContent = `Confirm Pick (0 / ${state.human_picks_remaining} selected)`;
    packArea.appendChild(confirmBtn);

    confirmBtn.addEventListener('click', () => {
      if (draftUI.selected.size === 0 || draftUI.submitting) return;
      submitPicks(draftName, app);
    });
  }

  // Drafted overlay
  const overlay = document.createElement('div');
  overlay.className = 'drafted-overlay';
  overlay.innerHTML = `
    <div class="drafted-backdrop"></div>
    <div class="drafted-panel">
      <div class="drafted-panel-header">
        <span>Drafted (${state.drafted_human.length})</span>
        <button class="drafted-close" aria-label="Close">✕</button>
      </div>
      <div class="drafted-cards">
        ${state.drafted_human.map(c =>
          `<div class="drafted-card" title="${esc(c.name)}">${esc(c.name)}</div>`
        ).join('')}
      </div>
    </div>
  `;

  const openOverlay  = () => overlay.classList.add('open');
  const closeOverlay = () => overlay.classList.remove('open');
  overlay.querySelector('.drafted-backdrop').addEventListener('click', closeOverlay);
  overlay.querySelector('.drafted-close').addEventListener('click', closeOverlay);

  layout.appendChild(header);
  layout.appendChild(packArea);
  app.appendChild(layout);
  app.appendChild(overlay);

  header.querySelector('#toggle-drafted-btn').addEventListener('click', openOverlay);
}

function handleCardClick(item, card, draftName, state, app) {
  if (draftUI.submitting) return;
  const n = state.picks_per_pass;

  if (n === 1) {
    // Immediate pick
    draftUI.submitting = true;
    item.style.opacity = '0.5';
    submitSinglePick(card.id, draftName, app);
  } else {
    // Toggle selection
    if (draftUI.selected.has(card.id)) {
      draftUI.selected.delete(card.id);
      item.classList.remove('selected');
    } else if (draftUI.selected.size < state.human_picks_remaining) {
      draftUI.selected.add(card.id);
      item.classList.add('selected');
    }
    updateConfirmButton(state.human_picks_remaining);
  }
}

function updateConfirmButton(needed) {
  const btn = document.getElementById('confirm-pick-btn');
  if (!btn) return;
  const n = draftUI.selected.size;
  btn.disabled    = n < needed;
  btn.textContent = `Confirm Pick (${n} / ${needed} selected)`;
}

async function submitSinglePick(cardId, draftName, app) {
  try {
    const state = await api('POST', `/api/drafts/${draftName}/pick`, { card_id: cardId });
    if (state.status === 'complete') {
      location.hash = `#/draft/${draftName}/pool`;
    } else {
      renderDraftInProgress(app, draftName, state);
    }
  } catch (e) {
    draftUI.submitting = false;
    alert(`Pick failed: ${e.message}`);
    renderDraft(app, draftName);
  }
}

async function submitPicks(draftName, app) {
  draftUI.submitting = true;
  const ids = [...draftUI.selected];
  let state;
  try {
    for (const id of ids) {
      state = await api('POST', `/api/drafts/${draftName}/pick`, { card_id: id });
    }
  } catch (e) {
    draftUI.submitting = false;
    alert(`Pick failed: ${e.message}`);
    renderDraft(app, draftName);
    return;
  }
  if (state.status === 'complete') {
    location.hash = `#/draft/${draftName}/pool`;
  } else {
    renderDraftInProgress(app, draftName, state);
  }
}


// ─────────────────────────────────────────────────────────────
// Pool view
// ─────────────────────────────────────────────────────────────

async function renderPool(app, draftName) {
  app.innerHTML = '<div class="loading">Loading pool…</div>';
  let pool;
  try {
    pool = await api('GET', `/api/drafts/${draftName}/pool`);
  } catch (e) {
    app.innerHTML = `<div class="error-msg">Error: ${esc(e.message)}</div>`;
    return;
  }

  const div = document.createElement('div');
  div.className = 'pool-view';

  const moxfieldText = pool.cards.map(c => `1 ${c.name}`).join('\n');
  const moxfieldUrl  = URL.createObjectURL(new Blob([moxfieldText], { type: 'text/plain' }));

  const header = document.createElement('div');
  header.className = 'pool-header';
  header.innerHTML = `
    <h1>Your Drafted Pool</h1>
    <span style="color:#aaa">${pool.total_drafted} cards</span>
    <a href="${moxfieldUrl}" download="drafted-pool.txt" class="btn-primary" style="padding:6px 14px;border-radius:4px;font-size:0.85rem">Download for Moxfield</a>
    <a href="#/" class="btn-secondary" style="padding:6px 14px;border-radius:4px;font-size:0.85rem">← Drafts</a>
  `;

  const grid = document.createElement('div');
  grid.className = 'card-grid';

  pool.cards.forEach(card => {
    const item = document.createElement('div');
    item.className = 'card-item';
    item.appendChild(cardImg(card));

    item.addEventListener('mouseenter', e => showTooltip(card, e.clientX, e.clientY));
    item.addEventListener('mousemove',  e => positionTooltip(e.clientX, e.clientY));
    item.addEventListener('mouseleave', hideTooltip);

    grid.appendChild(item);
  });

  div.appendChild(header);
  div.appendChild(grid);
  app.innerHTML = '';
  app.appendChild(div);
}
