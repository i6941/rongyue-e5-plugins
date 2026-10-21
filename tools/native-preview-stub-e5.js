/* 预览用的 e5 SDK 占位：真实设备上有宿主提供的 /sdk/e5.js。
   预览时给一份最小实现，让页面的 e5.api 调用走本地内存，不报错。 */
(function () {
  var calls = [];
  window.e5 = {
    api: function (path, opts) {
      calls.push(path);
      window.__e5api = calls;
      return Promise.resolve({ ok: true, preview: true });
    },
    onKey: function () {},
    onBack: function () {},
    keepAwake: function () {},
    toast: function () {},
  };
})();
