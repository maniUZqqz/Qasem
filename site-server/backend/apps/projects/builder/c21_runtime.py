# -*- coding: utf-8 -*-
"""رانتایمِ کوچکِ «تعامل» برای قطعه‌های 21st (دورِ ۵، ۱۱/۱۸).

قطعه‌های تبدیل‌شده HTMLِ ساکن‌اند (بی‌اسکریپت)؛ آکاردئون، تب، کلید (switch) و بنرِ بسته‌شو در سایتِ منتشرشده کاری نمی‌کردند و پنلِ بسته‌ها اصلاً در HTML نبود.
حالا مبدّل همهٔ پنل‌ها را در HTML می‌گذارد (بسته‌ها ``hidden``) و این اسکریپتِ ~۳ کیلوبایتیِ بی‌وابستگی روی همان نشانه‌ها (``aria-expanded``، ``role=tab``، ``role=switch``،
``data-nbc-*``، ``data-state`` / ``data-open`` / ``data-closed`` ِ Radix و Base UI) باز و بسته می‌کند. هیچ‌چیزی از بیرون نمی‌آید و چیزی ارسال نمی‌شود.

فقط داخلِ قطعه‌های 21st (``.nbc21-host``) کار می‌کند: دکمه‌های خودِ سایت (منوی همبرگری، …) هرگز دست‌خورده نمی‌شوند.
الگوها: ``accordion`` (دکمهٔ ``aria-expanded`` + پنلِ هم‌نشین؛ ``type=single`` ⇒ فقط یکی باز)، ``tabs`` (``role=tablist/tab/tabpanel``، پیکان‌ها)،
``toggle`` (``role=switch|checkbox``)، ``dismiss`` (دکمهٔ «Close/Dismiss/بستن» در ``role=alert|status|dialog|banner`` یا ``data-slot`` ِ banner/alert/toast/cookie).
سنجشِ مرورگر (``deploy/c21/rtl_check.py``) همین اسکریپت را روی هر قطعه تزریق و کلیک می‌کند تا «کار می‌کند» تجربی ثابت شود، نه حدس.
"""
from __future__ import annotations

import re

VERSION = 1

#: بدونِ «{{»، «{%» و «{#» (قالبِ جنگو) و بدونِ پایانِ script؛ آزمون این را می‌سنجد.
RUNTIME_JS = r"""(function(){
if(window.__nbc21)return;
var api=window.__nbc21={version:1};
function A(l){return Array.prototype.slice.call(l)}
function qa(r,s){return A(r.querySelectorAll(s))}
function has(e,n){return e.hasAttribute(n)}
function set(e,n,on){if(on)e.setAttribute(n,'');else e.removeAttribute(n)}
function mark(e,on,kind){
  if(!e||e.nodeType!==1)return;
  if(has(e,'data-state'))e.setAttribute('data-state',kind==='tab'?(on?'active':'inactive'):kind==='chk'?(on?'checked':'unchecked'):(on?'open':'closed'));
  if(has(e,'data-open')||has(e,'data-closed')){set(e,'data-open',on);set(e,'data-closed',!on)}
  if(has(e,'data-active')||has(e,'data-inactive')){set(e,'data-active',on);set(e,'data-inactive',!on)}
  if(has(e,'data-checked')||has(e,'data-unchecked')){set(e,'data-checked',on);set(e,'data-unchecked',!on)}
  if(has(e,'data-panel-open'))set(e,'data-panel-open',on);
  if(has(e,'data-hidden')&&on)e.removeAttribute('data-hidden')
}
function head(t){var h=t.parentNode;return h&&h.nodeType===1&&(/^H[1-6]$/.test(h.tagName)||has(h,'data-nbc-head'))?h:t}
function isPanel(p){return !!p&&p.nodeType===1&&(has(p,'hidden')||has(p,'data-nbc-panel')||p.getAttribute('role')==='region'||has(p,'data-open')||has(p,'data-closed')||has(p,'data-state'))}
function panelOf(t){
  var h=head(t),p=h.nextElementSibling;
  if(isPanel(p))return p;
  var r=t.closest('[data-nbc-item],[data-nbc-root]');
  if(r){var c=qa(r,'[data-nbc-panel]');for(var i=0;i<c.length;i++){if(c[i].closest('[data-nbc-item],[data-nbc-root]')===r)return c[i]}}
  r=t.parentNode&&t.parentNode.closest?t.parentNode.closest('[data-open],[data-closed],[data-state]'):null;
  if(r){var d=qa(r,'[hidden],[role=region],[data-nbc-panel]');for(var j=0;j<d.length;j++){if(!t.contains(d[j])&&isPanel(d[j])&&(has(d[j],'data-open')||has(d[j],'data-closed')||has(d[j],'data-state')||has(d[j],'data-nbc-panel')||d[j].getAttribute('role')==='region'))return d[j]}}
  return null
}
function setOpen(t,on){
  var p=panelOf(t);if(!p)return false;
  var h=head(t),it=t.closest('[data-nbc-item],[data-nbc-root]')||(h!==t?h.parentNode:null);
  t.setAttribute('aria-expanded',on?'true':'false');p.hidden=!on;
  if(has(p,'data-open')||has(p,'data-closed'))set(t,'data-panel-open',on);
  [t,h,p,it,p.parentNode].forEach(function(e){mark(e,on,'open')});
  return true
}
function acc(t){
  var on=t.getAttribute('aria-expanded')!=='true';
  if(on){var root=t.closest('[data-nbc-acc="single"],[type="single"]');
    if(root)qa(root,'[aria-expanded="true"]').forEach(function(o){if(o!==t)setOpen(o,false)})}
  return setOpen(t,on)
}
function tab(t){
  var list=t.closest('[role=tablist]');if(!list)return false;
  var root=list.parentNode,tabs=qa(list,'[role=tab]'),panels=[];
  for(var k=0;k<4&&root&&!panels.length;k++){panels=qa(root,'[role=tabpanel]').filter(function(p){return !list.contains(p)});if(!panels.length)root=root.parentNode}
  var i=tabs.indexOf(t);if(i<0||!panels[i])return false;
  tabs.forEach(function(x,j){var on=j===i;x.setAttribute('aria-selected',on?'true':'false');x.tabIndex=on?0:-1;mark(x,on,'tab')});
  panels.forEach(function(p,j){p.hidden=j!==i;mark(p,j===i,'tab')});
  return true
}
function sw(t){
  var on=t.getAttribute('aria-checked')!=='true';
  t.setAttribute('aria-checked',on?'true':'false');mark(t,on,'chk');
  A(t.children).forEach(function(c){mark(c,on,'chk')});
  return true
}
function dismiss(t){
  var l=(t.getAttribute('aria-label')||'').toLowerCase();
  if(!has(t,'data-nbc-dismiss')&&l.indexOf('close')!==0&&l.indexOf('dismiss')!==0&&l.indexOf('بستن')!==0)return false;
  var c=t.closest('[role=alert],[role=status],[role=dialog],[role=banner],[data-slot*=banner],[data-slot*=alert],[data-slot*=toast],[data-slot*=notification],[data-slot*=cookie],[data-nbc-dismissible]');
  if(!c)return false;c.hidden=true;return true
}
var SEL='button,[role=tab],[role=switch],[role=checkbox],[aria-expanded]';
function act(t){
  var r=t.getAttribute('role');
  if(r==='tab')return tab(t);
  if(has(t,'aria-expanded'))return acc(t);
  if(r==='switch'||r==='checkbox'||has(t,'aria-checked'))return sw(t);
  return dismiss(t)
}
function mine(t){return !!(t.closest&&t.closest('.nbc21-host'))}
document.addEventListener('click',function(e){
  var t=e.target&&e.target.closest?e.target.closest(SEL):null;
  while(t){if(mine(t)&&act(t)){e.preventDefault();return}t=t.parentNode&&t.parentNode.closest?t.parentNode.closest(SEL):null}
},false);
document.addEventListener('keydown',function(e){
  var t=e.target;if(!t||!t.getAttribute||t.getAttribute('role')!=='tab'||!mine(t))return;
  var k=e.key;if(k!=='ArrowLeft'&&k!=='ArrowRight'&&k!=='Home'&&k!=='End')return;
  var list=t.closest('[role=tablist]');if(!list)return;
  var tabs=qa(list,'[role=tab]'),i=tabs.indexOf(t),rtl=getComputedStyle(list).direction==='rtl',n=tabs.length;
  var j=k==='Home'?0:k==='End'?n-1:(i+((k==='ArrowRight')!==rtl?1:-1)+n)%n;
  if(tabs[j]){tabs[j].focus();tabs[j].click();e.preventDefault()}
},false);
api.panelOf=panelOf;
})();"""


def script_tag() -> str:
    """‹script› ِ درون‌خطی؛ سایتِ منتشرشده با یک نسخه از آن (یک بار در هر صفحه)."""
    return '<script data-nbc21-rt="%d">%s</script>' % (VERSION, RUNTIME_JS)


def runtime_ok(js: str = RUNTIME_JS) -> bool:
    """بی‌خطرِ قالبِ جنگو و HTML: بدونِ {{ ، {% ، {# و «</script»."""
    return not re.search(r"\{[{%#]|</script", js, re.I)


def needs_runtime(rec: dict) -> bool:
    """آیا این قطعه با رانتایم «زنده» می‌شود (سنجشِ مرورگر نشان داد دست‌کم یک الگو کار می‌کند)؟"""
    return (rec.get("interact") or {}).get("state") == "works"
