/* 应用内置 9 键拼音输入法
 *
 * 为什么不用宿主那套：宿主的输入法是个独立 iframe，盖在页面外面，不是悬浮的，
 * 而且它带的词库只有 676 条，打什么都要翻页选字。这里把输入法做进插件自己，
 * 面板跟着搜索框走，词库由 tools/build-ime-dict.py 从 jieba 词频表编译。
 *
 * 按键（设备是实体键盘，2-9 同时是拼音键）：
 *   2-9      输入拼音数字
 *   1        标点（连按换下一个标点）
 *   0        空格
 *   *#       上屏当前候选（快速选第一个）
 *   OK       有拼音时上屏候选；没拼音时收起面板并搜索
 *   ← →      移动候选；↑ ↓ 翻页
 *   返回      有拼音先清拼音，再退格，最后收起面板
 */
(function () {
  'use strict';

  var DICT = null, MAXSIG = 0;
  var PAGE = 8;

  var PUNCT = ['，', '。', '？', '！', '、', '：', '；', '《', '》', '…'];
  var EN_KEYS = {
    '2': 'abc', '3': 'def', '4': 'ghi', '5': 'jkl', '6': 'mno',
    '7': 'pqrs', '8': 'tuv', '9': 'wxyz'
  };

  var st = {
    open: false,
    mode: 'zh',
    text: '',
    buf: '',
    cands: [],
    sel: 0,
    punctAt: 0,
    punctIdx: 0,
    enKey: null,
    enIdx: 0,
    enAt: 0,
    enTimer: 0
  };
  var hook = { search: null, change: null, close: null };
  var dom = {};

  /* ---------------- 词典 ---------------- */

  function parseDict() {
    if (DICT) return DICT;
    DICT = {};
    var raw = window.IME_DICT || '';
    var rows = raw.split(';');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var bar = row.indexOf('|');
      if (bar < 1) continue;
      var sig = row.slice(0, bar);
      var items = row.slice(bar + 1).split(',');
      var list = [];
      for (var k = 0; k < items.length; k++) {
        var it = items[k];
        var til = it.lastIndexOf('~');
        if (til < 1) continue;
        list.push([it.slice(0, til), +it.slice(til + 1)]);
      }
      if (list.length) {
        DICT[sig] = list;
        if (sig.length > MAXSIG) MAXSIG = sig.length;
      }
    }
    return DICT;
  }

  /* 把整串数字分成若干词：每一步都保留最省的 3 条路，避免指数爆炸 */
  function segment(buf) {
    var n = buf.length, best = new Array(n + 1);
    best[0] = [{ cost: 0, t: '', parts: 0 }];
    for (var i = 1; i <= n; i++) {
      var cand = [];
      var maxL = Math.min(14, i);
      for (var L = 1; L <= maxL; L++) {
        var sig = buf.substr(i - L, L);
        var g = DICT[sig];
        if (!g) continue;
        var prev = best[i - L];
        if (!prev || !prev.length) continue;
        var take = Math.min(g.length, 3);
        for (var p = 0; p < prev.length; p++) {
          for (var k = 0; k < take; k++) {
            var w = g[k];
            /* 词频档越高越优先；每多一个词加一点代价，倾向少分词 */
            var cost = prev[p].cost + (10 - w[1]) + 0.6;
            cand.push({ cost: cost, t: prev[p].t + w[0], parts: prev[p].parts + 1 });
          }
        }
      }
      cand.sort(function (a, b) { return a.cost - b.cost || a.parts - b.parts; });
      best[i] = cand.slice(0, 3);
    }
    return best[n] || [];
  }

  function rebuild() {
    var out = [], seen = {};
    function push(t) {
      if (!t || seen[t]) return;
      seen[t] = 1;
      out.push(t);
    }
    if (st.mode === 'zh' && st.buf) {
      var exact = DICT[st.buf];
      if (exact) for (var i = 0; i < exact.length; i++) push(exact[i][0]);
      var segs = segment(st.buf);
      for (var s = 0; s < segs.length; s++) push(segs[s].t);
      /* 整串还没打完（比如 644 想打 nihao）：补几个以此为前缀的词，方便一次上屏 */
      if (out.length < PAGE) {
        var keys = Object.keys(DICT), added = 0;
        for (var k = 0; k < keys.length && added < PAGE; k++) {
          var sig = keys[k];
          if (sig.length > st.buf.length && sig.length <= st.buf.length + 6 &&
              sig.indexOf(st.buf) === 0) {
            var g = DICT[sig];
            for (var q = 0; q < g.length && added < PAGE; q++) {
              if (!seen[g[q][0]]) { push(g[q][0]); added++; }
            }
          }
        }
      }
    }
    st.cands = out;
    if (st.sel >= out.length) st.sel = 0;
  }

  /* ---------------- 文本 ---------------- */

  function setText(t, silent) {
    st.text = t;
    if (dom.text) {
      dom.text.textContent = t;
      dom.text.classList.toggle('empty', !t);
    }
    if (!silent && hook.change) hook.change(t);
    render();
  }

  function commit(v) {
    if (!v) return;
    setText(st.text + v);
  }

  function backspace() {
    if (st.buf) { st.buf = st.buf.slice(0, -1); st.sel = 0; rebuild(); render(); return true; }
    if (st.enKey) { st.enKey = null; render(); return true; }
    if (st.text) { setText(Array.from(st.text).slice(0, -1).join('')); return true; }
    return false;
  }

  /* ---------------- 渲染 ---------------- */

  function render() {
    if (!dom.root) return;
    var comp = '';
    if (st.mode === 'zh' && st.buf) comp = st.buf;
    else if (st.mode === 'en' && st.enKey) comp = EN_KEYS[st.enKey][st.enIdx] || '';
    if (dom.comp) dom.comp.textContent = comp;
    if (dom.mode) dom.mode.textContent = st.mode === 'zh' ? '中' : '英';
    if (dom.cands) {
      var box = dom.cands;
      box.textContent = '';
      var start = Math.floor(st.sel / PAGE) * PAGE;
      var slice = st.cands.slice(start, start + PAGE);
      for (var i = 0; i < slice.length; i++) {
        var b = document.createElement('span');
        b.className = 'ime-c' + (start + i === st.sel ? ' sel' : '');
        b.textContent = slice[i];
        (function (idx) {
          b.addEventListener('click', function () {
            st.sel = idx; commitCurrent();
          });
        })(start + i);
        box.appendChild(b);
      }
      if (!slice.length) {
        var hint = document.createElement('span');
        hint.className = 'ime-tip';
        hint.textContent = st.buf ? '没有候选，按 OK 上屏数字' : '2-9 拼音 · 1 标点 · 0 空格';
        box.appendChild(hint);
      }
      box.classList.toggle('multi', st.cands.length > PAGE);
    }
    if (dom.page) {
      var pages = Math.max(1, Math.ceil(st.cands.length / PAGE));
      dom.page.textContent = pages > 1 ? (Math.floor(st.sel / PAGE) + 1) + '/' + pages : '';
    }
  }

  /* ---------------- 操作 ---------------- */

  function commitCurrent() {
    if (!st.buf) return false;
    var pick = st.cands[st.sel];
    if (!pick) pick = st.buf;
    commit(pick);
    st.buf = '';
    st.sel = 0;
    rebuild();
    render();
    return true;
  }

  function insertPunct() {
    var now = Date.now();
    if (now - st.punctAt < 900 && st.punctAt) {
      st.punctIdx = (st.punctIdx + 1) % PUNCT.length;
      setText(Array.from(st.text).slice(0, -1).join('') + PUNCT[st.punctIdx]);
    } else {
      st.punctIdx = 0;
      commit(PUNCT[0]);
    }
    st.punctAt = now;
  }

  function commitEnglish() {
    if (!st.enKey) return false;
    var letters = EN_KEYS[st.enKey] || '';
    commit(letters.charAt(st.enIdx));
    st.enKey = null;
    return true;
  }

  function moveSel(d) {
    if (!st.cands.length) return false;
    st.sel = (st.sel + d + st.cands.length) % st.cands.length;
    render();
    return true;
  }

  function flipPage(d) {
    if (st.cands.length <= PAGE) return false;
    var start = Math.floor(st.sel / PAGE) * PAGE;
    start += d * PAGE;
    if (start >= st.cands.length) start = 0;
    if (start < 0) start = Math.floor((st.cands.length - 1) / PAGE) * PAGE;
    st.sel = start;
    render();
    return true;
  }

  function zhKey(key) {
    if (key === '1') { commitCurrent(); insertPunct(); return true; }
    if (key === '0') { commitCurrent(); commit(' '); return true; }
    if (key === '2' || key === '3' || key === '4' || key === '5' ||
        key === '6' || key === '7' || key === '8' || key === '9') {
      st.buf += key;
      st.sel = 0;
      rebuild();
      render();
      return true;
    }
    return false;
  }

  function enKey(key) {
    if (key === '1') { insertPunct(); return true; }
    if (key === '0') { commitEnglish(); commit(' '); return true; }
    var letters = EN_KEYS[key];
    if (!letters) return false;
    var now = Date.now();
    if (st.enKey === key && now - st.enAt < 900) {
      st.enIdx = (st.enIdx + 1) % letters.length;
    } else {
      commitEnglish();
      st.enKey = key;
      st.enIdx = 0;
    }
    st.enAt = now;
    render();
    clearTimeout(st.enTimer);
    st.enTimer = setTimeout(function () {
      if (st.enKey) { commitEnglish(); render(); }
    }, 900);
    return true;
  }

  /* 返回 true 表示这个键被输入法吃掉了 */
  function key(kind, k) {
    if (!st.open) return false;
    if (kind === 'back') {
      if (backspace()) return true;
      close();
      return true;
    }
    if (kind === 'ok') {
      if (st.mode === 'zh' && st.buf) { commitCurrent(); return true; }
      if (st.mode === 'en' && st.enKey) { commitEnglish(); render(); return true; }
      close();
      if (hook.search) hook.search(st.text);
      return true;
    }
    /* 没有候选也要吃掉：否则方向键会漏到列表去挪选中项 */
    if (kind === 'left') { moveSel(-1); return true; }
    if (kind === 'right') { moveSel(1); return true; }
    if (kind === 'up') { flipPage(-1); return true; }
    if (kind === 'down') { flipPage(1); return true; }
    if (kind === 'digit') {
      if (k === '*') {
        st.mode = st.mode === 'zh' ? 'en' : 'zh';
        st.enKey = null;
        render();
        return true;
      }
      if (k === '#') { if (st.buf) commitCurrent(); return true; }
      return st.mode === 'zh' ? zhKey(k) : enKey(k);
    }
    /* 英文模式下打字母：页面那边可能把字母当普通键送来 */
    if (st.mode === 'en' && k && k.length === 1) {
      commit(k.toLowerCase());
      return true;
    }
    return false;
  }

  /* ---------------- 开关 ---------------- */

  function open(text) {
    parseDict();
    st.open = true;
    st.buf = '';
    st.sel = 0;
    st.cands = [];
    if (typeof text === 'string') setText(text, true);
    if (dom.root) {
      dom.root.classList.add('on');
      dom.root.setAttribute('aria-hidden', 'false');
    }
    render();
  }

  function close() {
    if (!st.open) return;
    st.open = false;
    st.buf = '';
    st.cands = [];
    st.enKey = null;
    if (dom.root) {
      dom.root.classList.remove('on');
      dom.root.setAttribute('aria-hidden', 'true');
    }
    if (hook.close) hook.close(st.text);
  }

  function mount() {
    dom.root = document.getElementById('ime');
    if (!dom.root) return false;
    dom.text = document.getElementById('q');
    dom.comp = document.getElementById('ime-comp');
    dom.mode = document.getElementById('ime-mode');
    dom.cands = document.getElementById('ime-cands');
    dom.page = document.getElementById('ime-page');
    return true;
  }

  window.E5IME = {
    init: function (h) {
      if (!mount()) return false;
      hook.search = h && h.search;
      hook.change = h && h.change;
      hook.close = h && h.close;
      return true;
    },
    open: open,
    close: close,
    isOpen: function () { return st.open; },
    key: key,
    text: function () { return st.text; },
    setText: function (t) { setText(t || ''); },
    isBusy: function () { return !!(st.buf || st.enKey); },
    /* 调试/自检用：页面控制台和 tools 里的测试脚本靠这几个看内部状态 */
    cands: function () { return st.cands.slice(); },
    selected: function () { return st.cands[st.sel] || ''; },
    buffer: function () { return st.buf; },
    /* 真机自检：不开浏览器也能在设备上跑一遍「按键 -> 候选 -> 上屏」，
       结果由页面写到 /tmp/bili-probe.log，避免只靠语法检查就说做好了 */
    selfTest: function () {
      var t0 = Date.now();
      var r = {};
      try {
        open('');
        r.parseMs = Date.now() - t0;
        r.groups = Object.keys(DICT).length;
        /* 面板节点必须在脚本运行前就存在，否则点击搜索框根本弹不出来 */
        r.dom = !!dom.root;
        r.panelOn = !!(dom.root && dom.root.classList.contains('on'));

        var seq = function (keys) {
          for (var i = 0; i < keys.length; i++) key('digit', keys.charAt(i));
        };
        seq('744746');
        r.shipin = st.cands.slice(0, 3);
        key('ok', null);
        r.afterShipin = st.text;

        seq('64426744543');
        r.lianDa = st.cands.slice(0, 2);
        key('ok', null);
        r.afterLianDa = st.text;

        key('back', null);
        r.afterBack = st.text;
        close();
        r.ok = r.afterShipin === '视频' && r.afterLianDa === '视频你好世界';
      } catch (e) {
        r.ok = false;
        r.error = '' + (e && e.message ? e.message : e);
      }
      r.ms = Date.now() - t0;
      setText('', true);
      return r;
    }
  };
})();
