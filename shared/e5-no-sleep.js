/* e5-no-sleep.js — 统一的"运行期不锁屏"组件（我们自己的插件共用）
 *
 * 用法（放在 </body> 前，或用普通 <script src="nosleep.js"> 引入）：
 *   E5NoSleep.start({ minutes: 10 });   // 启动时申请 10 分钟不锁屏（可重复调用）
 *   E5NoSleep.setPlaying(true|false);   // 视频播放：true 时不受分钟数限制
 *   E5NoSleep.powerKey(e);              // 在插件的 keydown 里调用：电源键双击确认
 *   E5NoSleep.stop();                   // 退出时解除（页面销毁时租约也会自动过期）
 *
 * 规则：
 *  - 启动时申请 minutes 分钟的不锁屏窗口；窗口内每次触摸/按键都会把窗口续满；
 *  - 窗口用完后不再拦宿主，交回宿主自己的空闲规则（默认 60 秒）去锁屏；
 *  - 电源键始终有效，但需要 1.2 秒内按两次（第一次只提示），防误触；
 *  - 宿主收走 iframe（应用被关）后停止续期，不会把设备撑亮；
 *  - 所有拦截都带 2.5 秒租约、每 2 秒续期，页面一死自动失效。
 */
(function (global) {
  'use strict';
  var HOST = null, started = false, playing = false;
  var holdMs = 10 * 60000;
  var lastInputAt = Date.now(), lastPowerAt = 0;
  var timer = 0, installed = false, skipClose = false;

  function hostWin() {
    try {
      if (global.parent && global.parent !== global) return global.parent;
    } catch (e) {}
    return null;
  }
  function frameVisible(w) {
    try {
      var f = w.document.getElementById('app-frame');
      return !!(f && !f.hidden);
    } catch (e) { return true; }
  }
  function gate(w) {
    var g = w.__e5NoSleep;
    if (!g) g = w.__e5NoSleep = { until: 0, allowUntil: 0, activeUntil: 0 };
    return g;
  }
  function install() {
    if (installed) return;
    var w = hostWin();
    if (!w) { installed = true; return; }
    var g = gate(w);
    var blocked = function () {
      var n = Date.now();
      if (n < (g.allowUntil || 0)) return false;   /* 电源键双击放行 */
      return n < (g.until || 0);
    };
    try {
      var ob = w.setBlank;
      if (typeof ob === 'function' && !w.__e5NoSleepSetBlank) {
        w.setBlank = function (on) {
          try { if (on && blocked()) return; } catch (e) {}
          return ob.apply(this, arguments);
        };
        w.__e5NoSleepSetBlank = true;
      }
      var pow = w.T551M && w.T551M.power;
      if (typeof pow === 'function' && !w.__e5NoSleepPower) {
        w.T551M.power = function (on) {
          try { if (on && blocked()) return; } catch (e) {}
          return pow.apply(this, arguments);
        };
        w.__e5NoSleepPower = true;
      }
      var close = w.closeApp;
      if (!skipClose && typeof close === 'function' && !w.__e5NoSleepClose) {
        w.closeApp = function () {
          var st = '';
          try { st = String((new Error()).stack || ''); } catch (e) {}
          try {
            /* 锁屏导致的关闭：不真的关，只让游戏暂停（插件自己会挂起核心） */
            if (Date.now() < (g.activeUntil || 0) && /at lock\b/.test(st)) return;
          } catch (e) {}
          return close.apply(this, arguments);
        };
        w.__e5NoSleepClose = true;
      }
    } catch (e) {}
    installed = true;
  }
  function tick() {
    var w = hostWin();
    if (!w || !started) return;
    var g = gate(w);
    if (!frameVisible(w)) { g.until = 0; g.activeUntil = 0; return; }
    var now = Date.now();
    var keep = playing || holdMs <= 0 || (now - lastInputAt < holdMs);
    g.until = keep ? now + 2500 : 0;
    g.activeUntil = now + 8000;
    if (keep) {
      try { if (typeof global.e5 !== 'undefined' && global.e5.keepAwake) global.e5.keepAwake(true); } catch (e) {}
    }
  }
  function activity() { lastInputAt = Date.now(); }
  try {
    global.addEventListener('touchstart', activity, { passive: true, capture: true });
    global.addEventListener('mousedown', activity, { passive: true, capture: true });
    global.addEventListener('keydown', activity, true);
  } catch (e) {}

  global.E5NoSleep = {
    start: function (opts) {
      opts = opts || {};
      if (typeof opts.minutes === 'number') holdMs = opts.minutes <= 0 ? 0 : opts.minutes * 60000;
      skipClose = !!opts.skipClose;
      lastInputAt = Date.now();
      started = true;
      install();
      tick();
      if (!timer) timer = global.setInterval(tick, 2000);
    },
    setPlaying: function (on) {
      playing = !!on;
      if (playing && started) { lastInputAt = Date.now(); tick(); }
    },
    powerKey: function (e) {
      var k = e && (e.key || '');
      var code = e && e.keyCode;
      if (!(k === 'Power' || k === 'PowerOff' || k === 'Standby' || k === 'Sleep' || code === 116)) return false;
      var now = Date.now();
      var w = hostWin();
      if (now - lastPowerAt < 1200) {
        lastPowerAt = 0;
        if (w) { try { gate(w).allowUntil = now + 2500; } catch (x) {} }
        try { if (global.e5 && global.e5.toast) global.e5.toast('正在锁屏'); } catch (x) {}
      } else {
        lastPowerAt = now;
        try { if (global.e5 && global.e5.toast) global.e5.toast('再按一次电源键锁屏'); } catch (x) {}
      }
      return true;
    },
    stop: function () {
      started = false; playing = false;
      if (timer) { try { global.clearInterval(timer); } catch (e) {} timer = 0; }
      var w = hostWin();
      if (w) { try { gate(w).until = 0; gate(w).activeUntil = 0; } catch (e) {} }
    },
    _debug: function () { return { started: started, playing: playing, holdMs: holdMs }; }
  };
})(window);
