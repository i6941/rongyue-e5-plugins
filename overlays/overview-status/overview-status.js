/* Local E5 overview extension. Read-only; credentials stay in plugin backends. */
(() => {
  'use strict';
  const overview = document.querySelector('.page[data-title="overview"]');
  if (!overview || document.getElementById('e5-link-summary')) return;
  const card = document.createElement('div');
  card.id = 'e5-link-summary';
  card.className = 'card';
  const rows = {};
  for (const [id, label] of [['wifi', '上游 Wi-Fi'], ['nikki', 'Nikki']]) {
    const row = document.createElement('div');
    row.className = 'e5-summary-row';
    const name = document.createElement('span');
    name.className = 'label'; name.textContent = label;
    const value = document.createElement('span');
    value.className = 'e5-summary-value'; value.textContent = '读取中…';
    row.append(name, value); card.append(row); rows[id] = value;
  }
  overview.querySelector('.rates').after(card);
  const clean = value => String(value || '').replace(/^[^\p{L}\p{N}\[]+/u, '');
  function display(id, text, tone = '') {
    rows[id].textContent = text;
    rows[id].title = text;
    rows[id].className = 'e5-summary-value ' + tone;
  }
  async function read(id) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 7000);
    try {
      const response = await (window.T551MTransport
        ? window.T551MTransport.fetch('/api/plugins/' + id + '/status', {cache:'no-store', signal:controller.signal})
        : fetch('/api/plugins/' + id + '/status', {cache:'no-store', signal:controller.signal}));
      const result = await response.json();
      if (!response.ok || result?.ok !== true) throw new Error('Status unavailable');
      return result;
    } finally { clearTimeout(timeout); }
  }
  let busy = false, timer;
  async function refresh() {
    if (busy || document.hidden || !overview.classList.contains('is-current') ||
        !document.getElementById('app-frame')?.hidden) return;
    busy = true;
    try {
      const results = await Promise.allSettled([read('wifi-control'), read('nikki-control')]);
      const [wifi, nikki] = results;
      if (wifi.status === 'rejected') display('wifi', '状态暂不可读', 'warn');
      else {
        const w = wifi.value;
        display('wifi', w.connected ? w.ssid + (w.signal != null ? ' · ' + w.signal + ' dBm' : '')
          : w.mode === 'hotspot' ? '未连接 · 热点模式' : '未连接', w.connected ? 'ok' : 'warn');
      }
      if (nikki.status === 'rejected') display('nikki', '状态暂不可读', 'warn');
      else {
        const n = nikki.value;
        display('nikki', !n.running ? '已停止' : !n.apiReady ? '运行中 · 核心未就绪'
          : '运行中' + (n.proxy?.node ? ' · ' + clean(n.proxy.node) : ''), n.running && n.apiReady ? 'ok' : 'warn');
      }
    } finally { busy = false; }
  }
  const observer = new MutationObserver(refresh);
  observer.observe(overview, {attributes:true, attributeFilter:['class']});
  observer.observe(document.getElementById('app-frame'), {attributes:true, attributeFilter:['hidden']});
  document.addEventListener('visibilitychange', refresh);
  window.addEventListener('pagehide', () => {clearInterval(timer); observer.disconnect();});
  refresh(); timer = setInterval(refresh, 10000);
})();
