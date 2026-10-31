// Observatory: browse the incident journal (OBS-12 to OBS-16). Plain JS, no
// build step. The URL query string is the single source of filter state.
(() => {
  const $ = (id) => document.getElementById(id);
  const REFRESH_MS = 5000;
  const PAGE = 100;
  const RANGES = { '1h': 3600e3, '24h': 86400e3, '7d': 7 * 86400e3, '30d': 30 * 86400e3 };
  const KIND_LABEL = { fault: 'fault', rejection: 'rejection', cap_trip: 'cap trip', client_failure: 'client failure' };
  const FILTER_KEYS = ['range', 'kind', 'code', 'client', 'device', 'session', 'q', 'since', 'until'];

  // ---- Presets (OBS-13) ---------------------------------------------------
  // "This device" and "This session" need a chosen value; it is filled in
  // when the preset is clicked and can then be edited in the filter fields.
  const PRESETS = [
    { id: 'hour', label: 'Last hour: faults + client failures',
      filter: { range: '1h', kind: ['fault', 'client_failure'] } },
    { id: 'device', label: 'This device', needs: 'device',
      filter: { range: '24h' } },
    { id: 'session', label: 'This session', needs: 'session',
      filter: {} },
    { id: 'why', label: "Why won't it start?",
      filter: { range: '24h', code: 'addressing.*,session.already_active,safety.cooldown,route.*,device.tunnel_down,device.not_reachable' } },
    // A client failure always carries a client.* code, so "client failures
    // and device.* codes" is the code list below; ANDing kind=client_failure
    // with device.* could never match anything.
    { id: 'connectivity', label: 'Connectivity',
      filter: { range: '24h', code: 'client.*,device.*' } },
    { id: 'all', label: 'Everything', filter: { range: '7d' } },
  ];

  const emptyState = () => ({
    range: '', kind: [], code: '', client: '', device: '', session: '', q: '',
    since: '', until: '', view: 'list', incident: '',
  });
  let state = emptyState();
  let items = [];          // loaded incident list items
  let nextBefore = null;
  let summaryRows = [];
  let knownDevices = new Set();
  let lastListJson = '';
  let lastDetailJson = '';
  let refreshing = false;
  let codeCatalogue = [];

  // ---- URL <-> state ------------------------------------------------------
  function readURL() {
    const p = new URLSearchParams(location.search);
    const s = emptyState();
    s.range = p.get('range') || '';
    s.kind = (p.get('kind') || '').split(',').filter(Boolean);
    for (const k of ['code', 'client', 'device', 'session', 'q', 'since', 'until', 'incident']) {
      s[k] = p.get(k) || '';
    }
    s.view = p.get('view') === 'grouped' ? 'grouped' : 'list';
    const hasFilter = FILTER_KEYS.some((k) => p.has(k));
    return { s, hasFilter };
  }

  function writeURL() {
    const p = new URLSearchParams();
    if (state.range) p.set('range', state.range);
    if (state.kind.length) p.set('kind', state.kind.join(','));
    for (const k of ['code', 'client', 'device', 'session', 'q', 'since', 'until']) {
      if (state[k]) p.set(k, state[k]);
    }
    if (state.view === 'grouped') p.set('view', 'grouped');
    if (state.incident) p.set('incident', state.incident);
    // An empty-but-intentional "all time, everything" view still needs a
    // filter key so the address does not fall back to the first preset.
    if (!FILTER_KEYS.some((k) => p.has(k))) p.set('range', 'all');
    const qs = p.toString();
    history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
  }

  function rangeKey() { return state.range === 'all' ? '' : state.range; }

  // ---- API ----------------------------------------------------------------
  function filterParams(extra = {}) {
    const p = new URLSearchParams();
    if (state.kind.length) p.set('kind', state.kind.join(','));
    for (const k of ['code', 'client', 'device', 'session', 'q']) {
      if (state[k]) p.set(k, state[k]);
    }
    const dur = RANGES[rangeKey()];
    if (state.since) p.set('since', state.since);
    else if (dur) p.set('since', new Date(Date.now() - dur).toISOString());
    if (state.until) p.set('until', state.until);
    for (const [k, v] of Object.entries(extra)) p.set(k, v);
    return p;
  }

  async function getJSON(path) {
    const r = await fetch(path, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  // ---- Small DOM helpers (text only; never innerHTML with data) -----------
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }

  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const today = new Date();
    const sameDay = d.toDateString() === today.toDateString();
    const opts = { hour: '2-digit', minute: '2-digit', second: '2-digit' };
    if (!sameDay) Object.assign(opts, { month: 'short', day: 'numeric' });
    return d.toLocaleString([], opts);
  }
  const timeEl = (iso) => h('span', { title: iso, text: fmtTime(iso) });
  const badge = (kind) => h('span', { class: `badge ${kind}`, text: KIND_LABEL[kind] || kind });

  // ---- Presets and filter controls ----------------------------------------
  function presetMatches(p) {
    const f = p.filter;
    if ((f.range || '') !== (rangeKey() || '')) return false;
    if ((f.code || '') !== state.code) return false;
    if ((f.kind || []).join(',') !== state.kind.join(',')) return false;
    if (p.needs === 'device') return !!state.device && !state.session && !state.client && !state.q;
    if (p.needs === 'session') return !!state.session && !state.device && !state.client && !state.q;
    return !state.device && !state.session && !state.client && !state.q;
  }

  function renderPresets() {
    $('presets').replaceChildren(...PRESETS.map((p) => h('button', {
      type: 'button', class: presetMatches(p) ? 'on' : '', text: p.label,
      'aria-pressed': presetMatches(p) ? 'true' : 'false',
      onclick: () => applyPreset(p),
    })));
  }

  async function applyPreset(p) {
    const keep = { view: state.view };
    state = Object.assign(emptyState(), keep, {
      range: p.filter.range || 'all',
      kind: [...(p.filter.kind || [])],
      code: p.filter.code || '',
    });
    if (p.needs === 'device') {
      state.device = chooseDevice();
      if (!state.device) setStatus('No device known yet: type one in the Device field.');
    } else if (p.needs === 'session') {
      state.session = await chooseSession();
      if (!state.session) setStatus('No incident with a session yet: type a session ID.');
    }
    syncControls();
    writeURL();
    refresh(true);
  }

  function chooseDevice() {
    // The web UI keeps the chosen device name in localStorage on this origin.
    let stored = '';
    try { stored = localStorage.getItem('trailsim.device') || ''; } catch (_) {}
    if (stored) return stored;
    return [...knownDevices][0] || '';
  }

  async function chooseSession() {
    const withSession = items.find((i) => i.session_id != null);
    if (withSession) return String(withSession.session_id);
    try {
      const data = await getJSON('/api/incidents?limit=200');
      const hit = data.incidents.find((i) => i.session_id != null);
      return hit ? String(hit.session_id) : '';
    } catch (_) { return ''; }
  }

  function syncControls() {
    $('f-range').value = state.range === 'all' ? '' : state.range;
    document.querySelectorAll('input[name="kind"]').forEach((c) => { c.checked = state.kind.includes(c.value); });
    $('f-code').value = state.code;
    $('f-client').value = state.client;
    $('f-device').value = state.device;
    $('f-session').value = state.session;
    $('f-q').value = state.q;
    $('view-list').setAttribute('aria-selected', String(state.view === 'list'));
    $('view-grouped').setAttribute('aria-selected', String(state.view === 'grouped'));
    renderPresets();
  }

  function readControls() {
    state.range = $('f-range').value || 'all';
    state.kind = [...document.querySelectorAll('input[name="kind"]:checked')].map((c) => c.value);
    state.code = $('f-code').value.trim();
    state.client = $('f-client').value.trim();
    state.device = $('f-device').value.trim();
    state.session = $('f-session').value.trim();
    state.q = $('f-q').value.trim();
    state.since = ''; state.until = '';
  }

  let debounce = null;
  function onControlsChanged(immediate) {
    readControls();
    renderPresets();
    writeURL();
    clearTimeout(debounce);
    debounce = setTimeout(() => refresh(true), immediate ? 0 : 250);
  }

  function setStatus(text) { $('status').textContent = text; }

  // ---- Rendering: list ----------------------------------------------------
  function renderList() {
    const box = $('list');
    if (state.view === 'grouped') return renderGrouped(box);
    if (!items.length) {
      box.replaceChildren(h('div', { class: 'empty', text: 'No incidents match this filter.' }));
      return;
    }
    box.replaceChildren(...items.map((i) => h('button', {
      type: 'button',
      class: `item${String(i.id) === state.incident ? ' selected' : ''}`,
      'data-id': i.id,
      onclick: () => openIncident(i.id),
    },
      h('span', { class: 'kind' }, badge(i.kind)),
      h('span', { class: 'code', text: i.code }),
      h('span', { class: 'time' }, timeEl(i.last_seen)),
      h('span', { class: 'msg', text: i.message, title: i.message }),
      h('span', { class: 'meta' },
        i.count > 1 ? h('span', { class: 'count', text: `×${i.count}` }) : null,
        i.device_name ? h('span', { text: `device ${i.device_name}` }) : null,
        i.client_id ? h('span', { text: `client ${i.client_id}` }) : null,
        i.session_id != null ? h('span', { text: `session ${i.session_id}` }) : null,
      ),
    )));
  }

  function renderGrouped(box) {
    if (!summaryRows.length) {
      box.replaceChildren(h('div', { class: 'empty', text: 'No incidents match this filter.' }));
      return;
    }
    box.replaceChildren(h('table', { class: 'grouped' },
      h('thead', null, h('tr', null,
        h('th', { text: 'Code' }), h('th', { text: 'Incidents' }),
        h('th', { text: 'Occurrences' }), h('th', { text: 'Last seen' }),
        h('th', { text: 'Remedy' }))),
      h('tbody', null, summaryRows.map((r) => h('tr', null,
        h('td', { class: 'code' }, h('button', {
          type: 'button', title: 'Show these incidents',
          text: r.code, onclick: () => { state.code = r.code; state.view = 'list'; syncControls(); writeURL(); refresh(true); },
        })),
        h('td', { class: 'num', text: r.incidents }),
        h('td', { class: 'num', text: r.occurrences }),
        h('td', null, timeEl(r.last_seen)),
        h('td', { class: 'remedy', text: r.remedy || '(none: read the traceback)' }),
      )))));
  }

  // ---- Rendering: detail --------------------------------------------------
  function row(label, value) {
    if (value == null || value === '') return null;
    return [h('dt', { text: label }), h('dd', null, value)];
  }

  const EXPLAIN = {
    up: 'Host up throughout the outage: the backend was running, which points at the network between the phone and the host.',
    down: 'Host down or asleep for the whole outage: the backend was not running, so the phone had nothing to reach.',
    partly: 'Host up for only part of the outage: it slept, froze or restarted while the phone was failing.',
  };

  function renderDetail(d) {
    const box = $('detail');
    const keepScroll = box.scrollTop;
    const req = d.request;
    const sess = d.session;
    const cf = d.client_failure;
    box.replaceChildren(h('div', { class: 'detail-body' },
      h('div', { class: 'actions' },
        h('button', { type: 'button', text: 'Close', onclick: closeIncident }),
        d.session_id != null ? h('button', {
          type: 'button', text: `Session ${d.session_id}'s incidents`,
          onclick: () => showSession(d.session_id),
        }) : null,
        h('button', { type: 'button', text: 'Copy link', onclick: (e) => copyLink(e.target, d.id) }),
      ),
      h('div', null, badge(d.kind), ' ', h('span', { class: 'time' }, `#${d.id}`)),
      h('h2', { text: d.code }),
      d.remedy
        ? h('div', { class: 'remedy' }, h('strong', { text: 'Remedy: ' }), d.remedy)
        : h('div', { class: 'remedy none', text: 'No remedy for this code: read the traceback below.' }),
      cf ? h('div', { class: 'explain' }, EXPLAIN[d.host_during_outage] || '') : null,
      h('h3', { text: 'Message' }),
      h('div', { class: 'message', text: d.message }),
      h('h3', { text: 'Record' }),
      h('dl', null,
        row('Source', d.source),
        row('First seen', timeEl(d.first_seen)),
        row('Last seen', timeEl(d.last_seen)),
        row('Occurrences', String(d.count)),
        row('Client', d.client_id),
        row('Device', d.device_name ? `${d.device_name}${d.device_udid ? ` (${d.device_udid})` : ''}` : d.device_udid),
        row('Session', d.session_id != null ? `${d.session_id}${d.session_state ? ` · ${d.session_state}` : ''}` : null),
        row('Backend version', d.backend_version),
      ),
      req ? [h('h3', { text: 'Request' }), h('dl', null,
        row('Request', `${req.method} ${req.path}${req.query ? `?${req.query}` : ''}`),
        row('Status', String(req.status)),
        row('Response', req.detail ? h('pre', { text: req.detail }) : null),
      )] : null,
      sess ? [h('h3', { text: 'Session at the time' }), h('dl', null,
        row('Origin', sess.origin ? sess.origin.join(', ') : null),
        row('Destinations', (sess.destinations || []).map((p) => p.join(', ')).join('  →  ')),
        row('Speed', sess.speed_kmh != null ? `${sess.speed_kmh} km/h` : null),
        row('Loop', sess.loop == null ? null : String(sess.loop)),
        row('Last fix', sess.last_fix ? sess.last_fix.slice(0, 2).join(', ') : null),
      )] : null,
      cf ? [h('h3', { text: 'Client failure' }), h('dl', null,
        row('Outage start', timeEl(cf.started_at)),
        row('Outage end', timeEl(cf.ended_at)),
        row('Failed attempts', String(cf.attempts)),
        row('App build', cf.app_build),
        row('OS version', cf.os_version),
        row("Phone's own times", `${cf.client_started_at} to ${cf.client_ended_at}`),
        row('Clock offset', cf.clock_offset_s != null ? `${cf.clock_offset_s} s (host minus phone)` : null),
      )] : null,
      d.exception_type || d.traceback ? [
        h('h3', { text: d.exception_type ? `Exception: ${d.exception_type}` : 'Exception' }),
        d.traceback ? h('pre', { text: d.traceback }) : null,
      ] : null,
      d.log ? [h('h3', { text: `Lead-up log (${d.log.length} lines)` }), h('pre', { text: d.log.join('\n') })] : null,
    ));
    box.scrollTop = keepScroll;
  }

  async function copyLink(btn, id) {
    const url = `${location.origin}${location.pathname}?incident=${id}`;
    try { await navigator.clipboard.writeText(url); btn.textContent = 'Copied'; }
    catch (_) { btn.textContent = url; }
    setTimeout(() => { btn.textContent = 'Copy link'; }, 2000);
  }

  function layoutDetail(open) {
    $('detail').hidden = !open;
    document.querySelector('.layout').classList.toggle('has-detail', open);
  }

  async function openIncident(id) {
    state.incident = String(id);
    lastDetailJson = '';
    writeURL();
    layoutDetail(true);
    highlightSelected();
    await refreshDetail(true);
  }

  function closeIncident() {
    state.incident = '';
    lastDetailJson = '';
    layoutDetail(false);
    writeURL();
    highlightSelected();
  }

  function showSession(id) {
    state = Object.assign(emptyState(), { session: String(id), range: 'all', view: 'list' });
    layoutDetail(false);
    syncControls();
    writeURL();
    refresh(true);
  }

  function highlightSelected() {
    document.querySelectorAll('.item').forEach((e) => {
      e.classList.toggle('selected', e.dataset.id === state.incident);
    });
  }

  async function refreshDetail(force) {
    if (!state.incident) return;
    try {
      const d = await getJSON(`/api/incidents/${encodeURIComponent(state.incident)}`);
      const json = JSON.stringify(d);
      if (force || json !== lastDetailJson) {
        lastDetailJson = json;
        renderDetail(d);
      }
    } catch (e) {
      $('detail').replaceChildren(
        h('div', { class: 'actions' }, h('button', { type: 'button', text: 'Close', onclick: closeIncident })),
        h('div', { class: 'empty', text: `Incident ${state.incident} could not be loaded (it may have been pruned).` }));
    }
  }

  // ---- Refresh ------------------------------------------------------------
  async function refresh(reset) {
    if (refreshing && !reset) return;
    refreshing = true;
    try {
      if (state.view === 'grouped') {
        const data = await getJSON(`/api/incidents/summary?${filterParams()}`);
        summaryRows = data.codes;
        const json = JSON.stringify(summaryRows);
        if (reset || json !== lastListJson) { lastListJson = json; renderList(); }
        $('more').hidden = true;
        setStatus(`${summaryRows.length} code${summaryRows.length === 1 ? '' : 's'} · updated ${new Date().toLocaleTimeString()}`);
      } else {
        // Re-fetch as many rows as are loaded so "Load more" pages persist.
        const want = reset ? PAGE : Math.min(500, Math.max(PAGE, items.length));
        const data = await getJSON(`/api/incidents?${filterParams({ limit: want })}`);
        items = data.incidents;
        nextBefore = data.next_before;
        for (const i of items) if (i.device_name) knownDevices.add(i.device_name);
        const json = JSON.stringify(items);
        if (reset || json !== lastListJson) { lastListJson = json; renderList(); }
        $('more').hidden = !nextBefore;
        setStatus(`${items.length}${nextBefore ? '+' : ''} incident${items.length === 1 ? '' : 's'} · updated ${new Date().toLocaleTimeString()}`);
        fillDeviceList();
      }
      await refreshDetail(false);
    } catch (e) {
      setStatus(`Could not load: ${e.message}`);
    } finally {
      refreshing = false;
    }
  }

  async function loadMore() {
    if (!nextBefore) return;
    const data = await getJSON(`/api/incidents?${filterParams({ limit: PAGE, before: nextBefore })}`);
    items = items.concat(data.incidents);
    nextBefore = data.next_before;
    lastListJson = JSON.stringify(items);
    renderList();
    $('more').hidden = !nextBefore;
  }

  function fillDeviceList() {
    $('device-list').replaceChildren(...[...knownDevices].map((d) => h('option', { value: d })));
  }

  async function loadReferenceData() {
    try {
      codeCatalogue = (await getJSON('/api/incident-codes')).codes;
      $('code-list').replaceChildren(...codeCatalogue.map((c) => h('option', { value: c.code })));
    } catch (_) {}
    try {
      for (const d of (await getJSON('/api/devices')).devices) knownDevices.add(d.name);
      fillDeviceList();
    } catch (_) {}
  }

  // ---- Boot ---------------------------------------------------------------
  function bind() {
    $('f-range').addEventListener('change', () => onControlsChanged(true));
    document.querySelectorAll('input[name="kind"]').forEach((c) => c.addEventListener('change', () => onControlsChanged(true)));
    for (const id of ['f-code', 'f-client', 'f-device', 'f-session', 'f-q']) {
      $(id).addEventListener('input', () => onControlsChanged(false));
    }
    $('clear').addEventListener('click', () => {
      state = Object.assign(emptyState(), { range: 'all', view: state.view, incident: state.incident });
      syncControls(); writeURL(); refresh(true);
    });
    $('view-list').addEventListener('click', () => setView('list'));
    $('view-grouped').addEventListener('click', () => setView('grouped'));
    $('more').addEventListener('click', loadMore);
    window.addEventListener('popstate', () => { boot(false); });
    document.addEventListener('visibilitychange', () => {
      $('live').classList.toggle('paused', document.hidden);
      $('live').textContent = document.hidden ? 'paused' : 'live';
      if (!document.hidden) refresh(false);
    });
    setInterval(() => { if (!document.hidden) refresh(false); }, REFRESH_MS);
  }

  function setView(v) {
    state.view = v;
    lastListJson = '';
    syncControls();
    writeURL();
    refresh(true);
  }

  function boot(first) {
    const { s, hasFilter } = readURL();
    state = s;
    if (!hasFilter) {
      // No filter in the address: open on the first preset (OBS-13).
      const p = PRESETS[0];
      state.range = p.filter.range;
      state.kind = [...p.filter.kind];
    }
    syncControls();
    writeURL();
    layoutDetail(!!state.incident);
    if (state.incident) refreshDetail(true);
    refresh(true);
  }

  // A phone has no room for the filter form above the list: start it closed.
  if (window.innerWidth < 700) $('filters').open = false;
  bind();
  loadReferenceData();
  boot(true);
})();
