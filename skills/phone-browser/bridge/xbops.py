"""页面内 JS 片段（唯一下发来源）。"""

TEXT_JS = r"""(function(){
  function shadowText(root){
    // DocumentFragment 没有 innerText，只能拼 textContent（这正是之前读不到影子树的原因）
    var out = '';
    var els = root.querySelectorAll('*');
    for (var i = 0; i < els.length; i++) {
      if (els[i].shadowRoot) out += '\n' + shadowText(els[i].shadowRoot) + '\n';
    }
    out += (root.textContent || '');
    return out;
  }
  function bodyText(doc){
    var t = '';
    try { t = doc.body ? doc.body.innerText : ''; } catch (e) {}
    t += shadowText(doc);
    var fs = doc.querySelectorAll('iframe');
    for (var i = 0; i < fs.length; i++) {
      try { if (fs[i].contentDocument) t += '\n' + bodyText(fs[i].contentDocument); } catch (e) {}
    }
    return t;
  }
  return bodyText(document).replace(/\n{3,}/g, '\n\n');
})()"""

SEL_FN = r"""
  function sel(el){
    function unique(q){ try { var a=document.querySelectorAll(q); return a.length===1 && a[0]===el; } catch(_){ return false; } }
    var tag=el.localName, esc=CSS.escape;
    if(el.id && unique('#'+esc(el.id))) return '#'+esc(el.id);
    for (var key of ['data-testid','data-test','name','aria-label','href','title']) {
      var v=el.getAttribute(key), q=v && tag+'['+key+'='+esc(v)+']';
      if(q && unique(q)) return q;
    }
    var parts=[], cur=el;
    while(cur && cur.nodeType===1 && parts.length<8){
      var i=1, p=cur; while((p=p.previousElementSibling)) if(p.localName===cur.localName) i++;
      parts.unshift(cur.localName+':nth-of-type('+i+')');
      var path=parts.join(' > '); if(unique(path)) return path;
      cur=cur.parentElement;
    }
    return null;
  }
  function label(el){
    return (el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') ||
      el.placeholder || (/^(button|submit|reset)$/.test(el.type) ? el.value : '') || '').trim().slice(0,80);
  }
  function sig(el){
    return JSON.stringify([el.localName,el.getAttribute('role'),el.getAttribute('type'),el.getAttribute('name'),
      el.getAttribute('href'),el.getAttribute('formaction'),el.getAttribute('aria-label'),label(el)]);
  }
  function vis(el){ var r = el.getBoundingClientRect(); return r.width > 4 && r.height > 4; }
"""

ROOTS_FN = r"""
  function roots(){
    var out=[], seen=new Set();
    function scan(root){
      var els;
      try { els = root.querySelectorAll('*'); } catch(e) { return; }
      for (var i=0;i<els.length;i++){
        var w=els[i];
        if (w.shadowRoot && !seen.has(w.shadowRoot)){ seen.add(w.shadowRoot); out.push(w.shadowRoot); scan(w.shadowRoot); }
        if (w.localName==='iframe'){ try{ var d=w.contentDocument; if(d && !seen.has(d)){ seen.add(d); out.push(d); scan(d); } }catch(e){} }
      }
    }
    out.push(document); scan(document);
    return out;
  }
"""

CHECKABLE_HIT_JS = r"""
  function __transparentCheckable(el) {
    if (!el.matches('input[type="checkbox"],input[type="radio"]') || Number(getComputedStyle(el).opacity)!==0) return false;
    var r=el.getBoundingClientRect(), root=el.getRootNode();
    if (r.width<1 || r.height<1) return false;
    if (typeof root.elementFromPoint!=='function') root=el.ownerDocument;
    return root.elementFromPoint(r.left+r.width/2,r.top+r.height/2)===el;
  }
"""

SNAPSHOT_JS = r"""(function(){ var OFFSET=__OFFSET__, PAGE_SIZE=__PAGE__;
""" + SEL_FN + ROOTS_FN + CHECKABLE_HIT_JS + r"""
  var serial=Array.from(crypto.getRandomValues(new Uint32Array(3)),function(x){return x.toString(36);}).join('-');
  var book={url:location.href,nodes:new Map(),signature:sig};
  document[Symbol.for('minis.snapshot.v1')]=book;
  var rs = roots();
  // 第一步：廉价可见性预筛（不看布局），并记录一次 rect 供排序
  var cands=[];
  function cheapVisible(el){
    if (el.getAttribute('aria-hidden')==='true' || el.hasAttribute('inert')) return false;
    if (typeof el.checkVisibility==='function'){
      try { if (!el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) && !__transparentCheckable(el)) return false; } catch(e){}
    }
    return true;
  }
  for (var k=0; k<rs.length; k++){
    var nodes = rs[k].querySelectorAll('a,button,input,select,textarea,[role=button],[role=tab],[onclick]');
    var scope = rs[k]===document ? '' : (rs[k].host ? '[shadow]' : '[iframe]');
    for (var i=0;i<nodes.length;i++){
      var el=nodes[i];
      if (!cheapVisible(el)) continue;
      var r0=el.getBoundingClientRect();
      if (r0.width<=4 || r0.height<=4) continue;   // 不再按视口裁剪：屏幕下方的按钮也要能找到
      var tagW = (el.localName==='button'||el.getAttribute('role')==='button'||/^(submit|button)$/.test(el.type||'')) ? 2 : 1;
      cands.push({el:el,scope:scope,top:r0.top,area:r0.width*r0.height,w:tagW});
    }
  }
  // 第二步：按视口上下顺序 + 语义权重排序，再按 offset 取一页（默认 70）
  cands.sort(function(a,b){ return (a.top-b.top) || (a.w!==b.w ? b.w-a.w : b.area-a.area); });
  var page = cands.slice(OFFSET, OFFSET+PAGE_SIZE);
  var inter=[];
  for (var q=0;q<page.length;q++){
    var c=page[q], ref='minis-ref:'+serial+':'+q;
    book.nodes.set(ref,{node:c.el,sig:sig(c.el)});
    inter.push({tag:c.el.localName,label:label(c.el).slice(0,40),index:q,ref:ref,sel:sel(c.el),scope:c.scope});
  }
  var ov = [];
  var cand = document.querySelectorAll('[role=dialog],dialog,[class*=modal],[class*=popup],[class*=drawer],[class*=dialog]');
  for (var j = 0; j < cand.length && ov.length < 6; j++) {
    var e = cand[j];
    if (getComputedStyle(e).display === 'none' || getComputedStyle(e).visibility === 'hidden' || !vis(e)) continue;
    var r = e.getBoundingClientRect();
    if (r.width < 30 || r.height < 80) continue;
    ov.push({sel: sel(e), text: (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160)});
  }
  var txt = '';
  try { txt = document.body ? document.body.innerText.replace(/\n{3,}/g, '\n\n').slice(0, 4000) : ''; } catch (e) {}
  return JSON.stringify({url: location.href, title: document.title, snapshot_id:serial, overlays: ov, interactive: inter, total: cands.length, offset: OFFSET, text: txt, roots: rs.length});
})()"""





GUARD_JS = CHECKABLE_HIT_JS + r"""
  function __interactive(el){
    if(!el||!el.isConnected) return false;
    var st=getComputedStyle(el);
    if(st.display==='none'||st.visibility==='hidden'||st.visibility==='collapse') return false;
    if(Number(st.opacity)===0 && !__transparentCheckable(el)) return false;
    var r=el.getBoundingClientRect();
    if(r.width<1||r.height<1) return false;
    if(el.closest('[inert]')) return false;
    if(el.closest('[aria-hidden="true"]') && !__transparentCheckable(el)) return false;
    return el.getClientRects().length>0;
  }
  function __target(sel){
    if(sel.indexOf('minis-ref:')===0){
      var book=document[Symbol.for('minis.snapshot.v1')];
      var item=book&&book.nodes.get(sel);
      if(!item||book.url!==location.href||!item.node.isConnected) throw Error('stale_ref: take a new snapshot');
      return item.node;
    }
    var f=document.querySelectorAll(sel);
    if(f.length!==1) throw Error(f.length?('ambiguous selector: '+f.length):('no element: '+sel));
    return f[0];
  }
"""

CLICK_JS = r"""(function(){""" + GUARD_JS + r"""
  var el=__target(%s);
  if(el.matches(':disabled,[aria-disabled="true"]')) return JSON.stringify({ok:false,error:'disabled element'});
  if(!__interactive(el)) return JSON.stringify({ok:false,error:'not_interactive: 元素不可见或尺寸为 0，拒绝点击'});
  var before={url:location.href,tag:el.localName,label:(el.getAttribute('aria-label')||el.innerText||'').trim().slice(0,60),
              expected_url:el.localName==='a'?el.href:null};
  el.scrollIntoView({block:'center'});
  try{
    var r0=el.getBoundingClientRect();
    var opts={bubbles:true,cancelable:true,view:window,clientX:r0.left+r0.width/2,clientY:r0.top+r0.height/2,button:0};
    if(window.PointerEvent) el.dispatchEvent(new PointerEvent('pointerdown',opts));
    el.dispatchEvent(new MouseEvent('mousedown',opts));
    if(window.PointerEvent) el.dispatchEvent(new PointerEvent('pointerup',opts));
    el.dispatchEvent(new MouseEvent('mouseup',opts));
  }catch(e){}
  el.click();
  return JSON.stringify({ok:true,state:'click_dispatched',before:before,after:{url:location.href,title:document.title}});
})()"""

FILL_JS = r"""(async function(){""" + GUARD_JS + r"""
  var f=__target(%s);
  if(!f.matches('input,select,textarea,[contenteditable="true"],[contenteditable=""],[contenteditable="plaintext-only"]'))
    return JSON.stringify({ok:false,error:'not a form field'});
  if(!f.matches('input,select,textarea')&&!f.isContentEditable)
    return JSON.stringify({ok:false,error:'field is not writable in this browser'});
  if(f.matches(':disabled,[aria-disabled="true"],[aria-readonly="true"]')||f.readOnly||f.closest('[inert]')) return JSON.stringify({ok:false,error:'field is not writable'});
  if(!__interactive(f)) return JSON.stringify({ok:false,error:'not_interactive: 表单元素不可见或尺寸为 0'});
  var want=%s;
  if(typeof want!=='string') return JSON.stringify({ok:false,error:'value must be a string'});
  var wantStr = want;
  if(f.type==='checkbox'||f.type==='radio'){
    var on = !(want===''||want==='false'||want==='0'||want==='off');
    if(f.type==='radio' && !on) return JSON.stringify({ok:false,error:'radio 只能被选中，不能取消'});
    if(f.checked!==on) f.click();
    if(f.checked!==on) return JSON.stringify({ok:false,error:'fill_rejected: 勾选框状态未变为 '+on});
    return JSON.stringify({ok:true,value:'filled',checked:on});
  }
  if(f.tagName==='SELECT' && f.multiple){
    var list;
    try{ list = JSON.parse(want); }catch(e){ list = String(want).split(/\s*,\s*/).filter(Boolean); }
    if(!Array.isArray(list)) list=[String(want)];
    for(var i=0;i<f.options.length;i++){
      var v=f.options[i].value, t=f.options[i].textContent.trim();
      f.options[i].selected = list.indexOf(v)>=0 || list.indexOf(t)>=0;
    }
    f.dispatchEvent(new Event('input',{bubbles:true}));
    f.dispatchEvent(new Event('change',{bubbles:true}));
    var picked=[].filter.call(f.options,function(o){return o.selected}).map(function(o){return o.value});
    return JSON.stringify({ok:true,value:'filled',selected:picked});
  }
  if(f.isContentEditable){
    // 富文本编辑器（Lexical/Slate/ProseMirror）有自己的模型：外部写 DOM 会被回滚，
    // 合成编辑事件也不一定被采纳。这里只做一次最普通的尝试，读回不一致就如实拒绝，
    // 不再尝试第二条通道（多试一次就会在编辑器里叠加重复内容）。
    var readCE = function(){ var t=''; try{ t=f.innerText; }catch(e){ try{ t=f.textContent; }catch(e2){ t=''; } } return t==null?'':String(t); };
    var beforeCE = readCE();
    if(wantStr === '' && beforeCE.trim() === '')
      return JSON.stringify({ok:true, value:'already empty', method:'noop', before:'', observed:''});
    f.focus();
    try{
      var rg = document.createRange(); rg.selectNodeContents(f);
      var sl = window.getSelection(); sl.removeAllRanges(); sl.addRange(rg);
    }catch(e){}
    try{ document.execCommand('insertText', false, wantStr); }catch(e){}
    // 必须等两帧再读：编辑器在下一帧回滚 DOM，同步读会读到假象。
    await new Promise(function(res){ var n=0; (function step(){ if(++n>=3) return void setTimeout(res, 40); requestAnimationFrame(step); })(); });
    var gotCE = readCE();
    if(gotCE === wantStr)
      return JSON.stringify({ok:true, value:'filled', method:'execCommand', before:beforeCE.slice(0,40), observed:gotCE.slice(0,40)});
    return JSON.stringify({ok:false, method:'execCommand', mutated: gotCE !== beforeCE,
      error:'fill_rejected: 富文本编辑器未接受该文本。本工具只保证普通表单；需要时点进去用真键盘输入',
      before: beforeCE.slice(0,40), observed: gotCE.slice(0,40)});
  }
  if(f.localName==='input'){
    var probe=f.cloneNode(false);
    try { probe.value=want; } catch(e) { return JSON.stringify({ok:false,error:'fill_rejected: invalid input value'}); }
    if(probe.value!==want) return JSON.stringify({ok:false,error:'fill_rejected: invalid input value'});
  } else if(f.localName==='select' && want!=='' && !Array.prototype.some.call(f.options,function(o){return o.value===want;})){
    return JSON.stringify({ok:false,error:'fill_rejected: no matching option'});
  }
  f.focus();
  try{
    var proto = f.tagName==='TEXTAREA' ? window.HTMLTextAreaElement.prototype
              : (f.tagName==='SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype);
    var setter = Object.getOwnPropertyDescriptor(proto,'value') && Object.getOwnPropertyDescriptor(proto,'value').set;
    if(setter) setter.call(f, want); else f.value = want;
  }catch(e){ f.value = want; }
  // React 的受控组件靠 _valueTracker 判断“值有没有被外部改过”，不清掉它就会把输入回滚
  try{ if(f._valueTracker) f._valueTracker.setValue(''); }catch(e){}
  try{ f.dispatchEvent(new InputEvent('input',{bubbles:true,data:want,inputType:'insertText'})); }
  catch(e){ f.dispatchEvent(new Event('input',{bubbles:true})); }
  f.dispatchEvent(new Event('change',{bubbles:true}));
  if(f.value!==want) return JSON.stringify({ok:false,error:'fill_rejected: 控件拒绝该值，实际为 '+JSON.stringify(String(f.value).slice(0,40))});
  return JSON.stringify({ok:true,value:'filled',react:!!f._valueTracker});
})()"""


