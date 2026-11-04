// ==UserScript==
// @name         Minis Bridge
// @namespace    minis.local
// @version      1.2
// @description  让 Minis 直接操控这个浏览器页面（DOM/JS），保留登录态
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// @updateURL    http://127.0.0.1:8765/minis.user.js
// @downloadURL  http://127.0.0.1:8765/minis.user.js
// ==/UserScript==

(function () {
  'use strict';
  var BASE = 'http://127.0.0.1:8765';
  var tab = Math.random().toString(36).slice(2, 9);
  var lastOk = Date.now();
  var waiting = null;          // 当前挂起的 poll 对象
  var stopped = false;

  function req(path, body, timeout, onReq) {
    return new Promise(function (resolve, reject) {
      var r = GM_xmlhttpRequest({
        method: 'POST',
        url: BASE + path,
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify(body || {}),
        timeout: timeout,
        onload: function (res) {
          if (onReq) onReq(null);
          try { resolve(JSON.parse(res.responseText)); }
          catch (e) { resolve({ ok: false, error: 'bad json' }); }
        },
        onerror: function () { if (onReq) onReq(null); reject(new Error('bridge unreachable')); },
        ontimeout: function () { if (onReq) onReq(null); reject(new Error('bridge timeout')); },
        onabort: function () { reject(new Error('aborted')); }
      });
      if (onReq) onReq(r);
    });
  }

  function run(job) {
    if (job.type === 'click') {
      var el = document.querySelector(job.selector);
      if (!el) throw new Error('no element: ' + job.selector);
      el.scrollIntoView({ block: 'center' });
      el.click();
      return 'clicked';
    }
    if (job.type === 'fill') {
      var f = document.querySelector(job.selector);
      if (!f) throw new Error('no element: ' + job.selector);
      f.focus();
      f.value = job.code || '';
      f.dispatchEvent(new Event('input', { bubbles: true }));
      f.dispatchEvent(new Event('change', { bubbles: true }));
      return 'filled';
    }
    var v = new Function('return (' + (job.code || 'null') + ')')();
    return v;
  }

  async function loop() {
    var backoff = 300;
    for (;;) {
      if (stopped) { await new Promise(function (r) { setTimeout(r, 1000); }); continue; }
      var job;
      try {
        job = await req('/poll', {
          tab: tab,
          url: location.href,
          title: document.title,
          visible: document.visibilityState === 'visible',
          focus: document.hasFocus(),
          v: 11
        }, 26000, function (r) { if (r) waiting = r; else waiting = null; });
        lastOk = Date.now();
        backoff = 300;
      } catch (e) {
        await new Promise(function (r) { setTimeout(r, 1500); });
        backoff = Math.min(backoff * 2, 8000);
        continue;
      }
      if (!job || !job.id) { await new Promise(function (r) { setTimeout(r, backoff); }); continue; }
      // 先回执：让服务端知道「已经开始执行」，即使结果丢失也不会被当成没执行
      try { await req('/ack', { id: job.id, url: location.href, title: document.title }, 8000); } catch (e) {}
      var out;
      try {
        var v = run(job);
        if (v && typeof v.then === 'function') v = await v;
        var val = (v !== null && typeof v === 'object') ? JSON.stringify(v) : String(v);
        out = { id: job.id, ok: true, value: val, url: location.href, title: document.title, v: 11 };
      } catch (e) {
        out = { id: job.id, ok: false, error: String((e && e.stack) || e), v: 11 };
      }
      try { await req('/result', out, 10000); } catch (e) {}
    }
  }

  // 页面重新可见 / 获得焦点时，立刻补一次心跳（被挂起后的唤醒）
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      try { if (waiting && waiting.abort) waiting.abort(); } catch (e) {}
    }
  }, true);

  // 看门狗：超过 40s 没有成功轮询，就掐掉挂起的请求重来
  setInterval(function () {
    if (Date.now() - lastOk > 40000) {
      lastOk = Date.now();
      try { if (waiting && waiting.abort) waiting.abort(); } catch (e) {}
    }
  }, 10000);

  loop();
})();
