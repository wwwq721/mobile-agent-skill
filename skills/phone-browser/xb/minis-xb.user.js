// ==UserScript==
// @name         Minis Bridge XB
// @namespace    minis.local
// @version      3.9.1
// @description  让 Minis 直接操控这个浏览器页面（DOM/JS），保留登录态
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// @match        *
// @include      *
// @updateURL    http://127.0.0.1:8765/xb.user.js
// @downloadURL  http://127.0.0.1:8765/xb.user.js
// ==/UserScript==

(function () {
  'use strict';
  var BASE = 'http://127.0.0.1:8765';
  var SV = '3.9.1';          // 脚本真实版本，桥用它判断浏览器里装的是不是最新
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
          if (res.status && (res.status < 200 || res.status >= 300)) {
            reject(new Error('bridge HTTP ' + res.status));
            return;
          }
          try {
            var data = JSON.parse(res.responseText);
            if (path === '/poll' && (!data || data.ok === false)) throw new Error('poll rejected');
            resolve(data);
          } catch (e) { reject(e); }
        },
        onerror: function () { if (onReq) onReq(null); reject(new Error('bridge unreachable')); },
        ontimeout: function () { if (onReq) onReq(null); reject(new Error('bridge timeout')); },
        onabort: function () { reject(new Error('aborted')); }
      });
      if (onReq) onReq(r);
    });
  }

  function target(selector) {
    if (typeof selector !== 'string' || !selector) throw Error('missing selector');
    if (selector.indexOf('minis-ref:') === 0) {
      var book=document[Symbol.for('minis.snapshot.v1')], item=book && book.nodes.get(selector);
      if (!item || book.url!==location.href || !item.node.isConnected ||
          item.node.ownerDocument!==document || book.signature(item.node)!==item.sig)
        throw Error('stale_ref: take a new snapshot');
      return item.node;
    }
    var found=document.querySelectorAll(selector);
    if (found.length!==1) throw Error(found.length ? 'ambiguous selector: '+found.length : 'no element: '+selector);
    return found[0];
  }
  function interactive(el){
    if (!el || !el.isConnected) return false;
    if (el.closest('[aria-hidden="true"]') && !el.closest('[aria-hidden="true"]').contains(el.offsetParent)) return false;
    var st=getComputedStyle(el);
    if (st.display==='none' || st.visibility==='hidden' || parseFloat(st.opacity)===0) return false;
    var r=el.getBoundingClientRect();
    if (r.width<1 || r.height<1) return false;
    if (el.closest('[inert]')) return false;
    return !!el.offsetParent || el.getClientRects().length>0;
  }

  function beforeClick(el) {
    return {url:location.href,tag:el.localName,label:(el.getAttribute('aria-label') ||
      el.innerText || el.getAttribute('title') || '').trim().slice(0,60),
      expected_url:el.localName==='a' ? el.href : null};
  }
  function run(job) {
    if(document.visibilityState!=='visible') throw Error('tab_hidden: action not run');
    if (job.type === 'click') {
      var el=target(job.selector), before=beforeClick(el);
      if(!interactive(el)) throw Error('not_interactive: 元素不可见或尺寸为 0，拒绝点击');
      if(el.matches(':disabled,[aria-disabled="true"]')) throw Error('disabled element');
      el.scrollIntoView({ block: 'center' });
      el.click();
      return {state:'click_dispatched',before:before,after:{url:location.href,title:document.title}};
    }
    if (job.type === 'fill') {
      var f=target(job.selector);
      if (f.matches(':disabled,[aria-disabled="true"]') || f.readOnly) throw Error('field is not writable');
      if (!f.matches('input,select,textarea')) throw Error('not a form field');
      if (!interactive(f)) throw Error('not_interactive: 表单元素不可见或尺寸为 0');
      var want = job.code || '';
      f.focus();
      f.value = want;
      f.dispatchEvent(new Event('input', { bubbles: true }));
      f.dispatchEvent(new Event('change', { bubbles: true }));
      if (f.value !== want) {
        throw Error('fill_rejected: 控件拒绝该值，实际为 ' + JSON.stringify(String(f.value).slice(0,40)));
      }
      return 'filled';
    }
    var v = new Function('return (' + (job.code || 'null') + ')')();
    return v;
  }

  var rafTicks = 0, rafRate = 0;
  (function tick(){ rafTicks++; requestAnimationFrame(tick); })();
  setInterval(function(){ rafRate = rafTicks; rafTicks = 0; }, 500);   // 每秒帧数 ≈ rafRate*2

  var loopGen = 0, loopTick = Date.now();
  function startLoop() { var g = ++loopGen; loopTick = Date.now(); loop(g); }

  async function loop(g) {
    var backoff = 1500;
    for (;;) {
      if (g !== loopGen) return;          // 被新一代循环替代，静默退出
      loopTick = Date.now();
      if (stopped) { await new Promise(function (r) { setTimeout(r, 1000); }); continue; }
      var job;
      try {
        job = await req('/poll', {
          tab: tab,
          url: location.href,
          title: document.title,
          visible: document.visibilityState === 'visible',
          focus: document.hasFocus(),
          v: 13,
          sv: SV,
          raf: rafRate
        }, 26000, function (r) { if (r) waiting = r; else waiting = null; });
        lastOk = Date.now();
        backoff = 1500;
      } catch (e) {
        await new Promise(function (r) { setTimeout(r, backoff); });
        backoff = Math.min(backoff * 2, 8000);
        continue;
      }
      // 空结果说明长轮询自然到期，立刻重连；只有出错才退避
      if (!job || !job.id) { continue; }
      // 先回执：让服务端知道「已经开始执行」，即使结果丢失也不会被当成没执行
      var receipt={id:job.id, tab:tab, url:location.href, title:document.title};
      if (job.type==='click') { try { receipt.before=beforeClick(target(job.selector)); } catch(_){} }
      // 页面侧最后一道闸：桥可能在投递后才过期，这里再核对一次绝对截止时间
      if (job.deadline && Date.now() > job.deadline) {
        var expired = { id: job.id, ok: false, error: 'deadline_exceeded: 执行前已超时，动作未执行',
                        url: location.href, title: document.title, v: 13, sv: SV, tab: tab };
        try { await req('/result', expired, 5000); } catch (e) {}
        continue;
      }
      // eval 幂等且不会跳转，回执没意义，省一次往返；click/fill 保留（可能触发卸载）
      if (job.type !== 'eval') { try { await req('/ack', receipt, 8000); } catch (e) {} }
      // 回执本身可能很慢（弱网/主线程忙）。执行前再核一次截止时间，
      // 否则「回执晚到」会把一个调用方早已放弃的点击补上——这是最危险的假象。
      if (job.deadline && Date.now() > job.deadline) {
        var late = { id: job.id, ok: false, error: 'deadline_exceeded: 回执延迟导致执行前已超时，动作未执行',
                     url: location.href, title: document.title, v: 13, sv: SV, tab: tab };
        try { await req('/result', late, 5000); } catch (e) {}
        continue;
      }
      var out;
      try {
        var v = run(job);
        if (v && typeof v.then === 'function') v = await v;
        var val = (v !== null && typeof v === 'object') ? JSON.stringify(v) : String(v);
        out = { id: job.id, ok: true, value: val, url: location.href, title: document.title, v: 13 };
      } catch (e) {
        out = { id: job.id, ok: false, error: String((e && e.stack) || e), v: 13 };
      }
      out.tab=tab;
      try { await req('/result', out, 10000); } catch (e) {}
    }
  }

  // Do not abort a poll on focus: an in-transit response may already contain a job.
  function presence(hidden) {
    req('/presence',{tab:tab,url:location.href,title:document.title,
      visible:!hidden && document.visibilityState==='visible',focus:document.hasFocus()},2500).catch(function(){});
  }
  document.addEventListener('visibilitychange',function(){ presence(false); },true);
  window.addEventListener('focus',function(){ presence(false); },true);
  window.addEventListener('blur',function(){ presence(false); },true);
  window.addEventListener('pageshow',function(){ presence(false); },true);
  window.addEventListener('pagehide',function(){ presence(true); },true);

  // 看门狗：40s 没成功轮询 → 掐掉挂起的请求；60s 循环本身停摆 → 换一代重开
  setInterval(function () {
    if (Date.now() - lastOk > 40000) {
      lastOk = Date.now();
      try { if (waiting && waiting.abort) waiting.abort(); } catch (e) {}
    }
    if (Date.now() - loopTick > 60000) {
      try { startLoop(); } catch (e) {}
    }
  }, 10000);

  startLoop();
})();
