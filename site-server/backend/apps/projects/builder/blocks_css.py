# -*- coding: utf-8 -*-
"""CSSِ پایهٔ بلوک‌ها؛ در پروژهٔ تولیدشده می‌شود static/css/blocks.css و بی‌جاوااسکریپت کار می‌کند.

راست‌به‌چپ با ویژگی‌های منطقی (margin-inline و padding-block) نوشته شده. متغیرهای --brand و … همان‌هایی
هستند که CSSِ پایهٔ پروژه و AI هم استفاده می‌کنند.
"""

BLOCK_CSS = r"""
body{font-family:var(--nb-font-body,Vazirmatn,"Segoe UI",Tahoma,sans-serif)}
h1,h2,h3,h4{font-family:var(--nb-font-head,inherit)}
.btn{border-radius:var(--nb-btn-radius,999px)}
.nb-wrap{max-width:var(--nb-width,1140px);margin-inline:auto;padding-inline:20px;width:100%}
.nb-section{position:relative;padding-block:clamp(44px,7vw,84px)}
.nb-section.is-full>.nb-wrap{max-width:none}
.nb-wrap>*+*{margin-top:22px}
.nb-col>*+*{margin-top:14px}
.nb-svg{display:inline-block;vertical-align:middle;flex:none}
.nb-cols{display:grid;gap:24px}
.nb-col{min-width:0}
.nb-h{line-height:1.3;font-weight:800;margin:0;letter-spacing:-.01em}
.nb-h1{font-size:clamp(2rem,5vw,3.1rem)}
.nb-h2{font-size:clamp(1.55rem,3.4vw,2.2rem)}
.nb-h3{font-size:clamp(1.2rem,2.4vw,1.45rem)}
.nb-h4{font-size:1.08rem}
.nb-text{font-size:1.02rem;line-height:2;color:inherit}
.nb-text p{margin:0 0 .75em}.nb-text p:last-child{margin-bottom:0}
.nb-text ul,.nb-text ol{margin:0 0 .75em;padding-inline-start:1.4em}
.nb-text a{text-decoration:underline}
.nb-image{margin:0}
.nb-image img{width:100%;height:auto;display:block;border-radius:inherit}
.nb-image figcaption{font-size:.86rem;opacity:.72;margin-top:8px;text-align:center}
.nb-button{display:block}
.nb-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;font:inherit;font-weight:700;line-height:1.5;cursor:pointer;
  border:1.5px solid transparent;border-radius:var(--nb-btn-radius,999px);text-decoration:none;transition:filter .15s,transform .15s,background .15s;white-space:nowrap}
.nb-btn:hover{transform:translateY(-1px);filter:brightness(1.06)}
.nb-btn:focus-visible,.nb-nav a:focus-visible,.nb-form input:focus-visible,.nb-form textarea:focus-visible{outline:3px solid color-mix(in srgb,var(--brand) 45%,transparent);outline-offset:2px}
.nb-btn[disabled]{opacity:.5;pointer-events:none}
.nb-btn.is-sm{padding:6px 16px;font-size:.88rem}
.nb-btn.is-md{padding:10px 24px}
.nb-btn.is-lg{padding:13px 32px;font-size:1.05rem}
.nb-btn.is-filled{background:var(--brand);color:var(--brand-ink,#fff);box-shadow:0 10px 22px -12px var(--brand)}
.nb-btn.is-outline{background:transparent;color:var(--brand);border-color:var(--brand)}
.nb-btn.is-soft{background:color-mix(in srgb,var(--brand) 14%,transparent);color:var(--brand)}
.nb-btn.is-ghost{background:transparent;color:inherit;border-color:color-mix(in srgb,currentColor 35%,transparent)}
.nb-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:26px}
.nb-video{max-width:100%}
.nb-video video{width:100%;display:block;border-radius:inherit;background:#000}
.nb-video iframe{width:100%;aspect-ratio:16/9;border:0;display:block;border-radius:inherit}
.nb-video-ph{display:grid;place-items:center;aspect-ratio:16/9;background:color-mix(in srgb,var(--ink) 8%,transparent);border-radius:12px;color:var(--ink-3);padding:12px;text-align:center}
.nb-divider{border:0;border-top:1px solid var(--line);margin-block:8px}
.nb-icon{line-height:0}
.nb-gallery-in{display:grid;gap:12px}
.nb-gallery-cell{overflow:hidden;border-radius:inherit}
.nb-gallery img{width:100%;height:auto;object-fit:cover;display:block;border-radius:inherit}
.nb-custom{display:contents}
.nb-head{max-width:720px;margin-inline:auto;margin-bottom:36px;text-align:center}
.nb-title{font-size:clamp(1.55rem,3.4vw,2.2rem);font-weight:800;line-height:1.3;margin:0 0 10px}
.nb-sub{font-size:1.06rem;line-height:1.95;margin:0;opacity:.8}
.nb-grid{display:grid;gap:22px}
.nb-hero{background:linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 55%,#0f172a));color:var(--brand-ink,#fff);padding-block:clamp(64px,10vw,128px)}
.nb-hero-copy.is-center{max-width:760px;margin-inline:auto;text-align:center}
.nb-hero-copy.is-center .nb-actions{justify-content:center}
.nb-hero-title{font-size:clamp(2.1rem,5.6vw,3.6rem);font-weight:900;line-height:1.22;margin:0 0 16px;letter-spacing:-.015em}
.nb-eyebrow{display:inline-block;font-size:.85rem;font-weight:700;padding:4px 14px;border-radius:999px;background:color-mix(in srgb,currentColor 15%,transparent);margin-bottom:16px}
.nb-hero .nb-btn.is-filled{background:var(--brand-ink,#fff);color:var(--brand);box-shadow:0 14px 30px -14px rgba(0,0,0,.5)}
.nb-hero-split{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:clamp(24px,5vw,64px);align-items:center}
.nb-hero-media img{width:100%;height:auto;display:block;border-radius:var(--r,16px);box-shadow:0 30px 70px -28px rgba(0,0,0,.55)}
.nb-hero-copy.is-center+.nb-hero-media{max-width:880px;margin:44px auto 0}
.nb-feature{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:var(--r,16px);padding:26px 24px;box-shadow:0 1px 2px rgba(0,0,0,.03),0 12px 28px -22px rgba(0,0,0,.25);transition:transform .15s,box-shadow .15s}
.nb-feature:hover{transform:translateY(-3px);box-shadow:0 18px 40px -22px rgba(0,0,0,.35)}
.nb-feature-icon{display:inline-grid;place-items:center;width:52px;height:52px;border-radius:14px;background:color-mix(in srgb,var(--brand) 13%,transparent);color:var(--brand);margin-bottom:14px}
.nb-feature-icon .nb-svg{width:26px;height:26px}
.nb-feature-title{font-size:1.14rem;font-weight:800;margin:0 0 6px}
.nb-feature-text{margin:0;color:var(--ink-2);line-height:1.9;font-size:.97rem}
.nb-plan{display:flex;flex-direction:column;gap:6px;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:var(--r,16px);padding:28px 24px;position:relative}
.nb-plan.is-featured{border:2px solid var(--brand);box-shadow:0 24px 50px -28px color-mix(in srgb,var(--brand) 70%,transparent);transform:translateY(-6px)}
.nb-plan-name{font-size:1.1rem;font-weight:800;margin:0}
.nb-plan-price{font-size:1.65rem;font-weight:900;color:var(--brand);line-height:1.4}
.nb-plan-period{font-size:.85rem;color:var(--ink-3)}
.nb-plan-list{list-style:none;margin:14px 0 20px;padding:0;display:grid;gap:9px;flex:1;align-content:start}
.nb-plan-list li{display:flex;gap:8px;align-items:flex-start;font-size:.96rem;color:var(--ink-2)}
.nb-plan-list .nb-svg{width:18px;height:18px;color:var(--brand);margin-top:4px}
.nb-plan .nb-btn{width:100%}
.nb-testimonials .nb-grid{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.nb-quote{margin:0;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:var(--r,16px);padding:24px;display:flex;flex-direction:column;gap:16px}
.nb-quote blockquote{margin:0;line-height:1.95;flex:1}
.nb-quote figcaption{display:flex;align-items:center;gap:12px}
.nb-quote figcaption span{display:grid}
.nb-quote small{color:var(--ink-3)}
.nb-avatar{width:46px;height:46px;border-radius:50%;object-fit:cover;flex:none}
.nb-avatar-ph{display:grid;place-items:center;background:color-mix(in srgb,var(--brand) 16%,transparent);color:var(--brand);font-weight:800}
.nb-faq-list{max-width:780px;margin-inline:auto;display:grid;gap:10px}
.nb-faq-item{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:calc(var(--r,16px) - 4px);padding:4px 18px}
.nb-faq-item summary{cursor:pointer;font-weight:700;padding:12px 0;list-style:none;display:flex;justify-content:space-between;gap:12px;align-items:center}
.nb-faq-item summary::-webkit-details-marker{display:none}
.nb-faq-item summary::after{content:"+";font-size:1.3rem;line-height:1;color:var(--brand);transition:transform .15s}
.nb-faq-item[open] summary::after{transform:rotate(45deg)}
.nb-faq-item p{margin:0 0 14px;color:var(--ink-2);line-height:1.95}
.nb-cta-box{background:linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 60%,#0f172a));color:var(--brand-ink,#fff);border-radius:calc(var(--r,16px) + 8px);padding:clamp(32px,6vw,60px);text-align:center}
.nb-cta-box .nb-actions{justify-content:center;margin-top:20px}
.nb-contact .nb-head{margin-bottom:24px}
.nb-form{max-width:620px;margin-inline:auto;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:var(--r,16px);padding:clamp(18px,4vw,30px);display:grid;gap:14px;box-shadow:0 18px 40px -30px rgba(0,0,0,.35)}
.nb-form-row{display:grid;gap:6px}
.nb-form label{font-size:.92rem;font-weight:600;color:var(--ink-2)}
.nb-form input:not([type=hidden]),.nb-form textarea{width:100%;font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:calc(var(--r,16px) - 6px);padding:10px 14px}
.nb-form input[type=tel],.nb-form input[type=email],.nb-form input[type=number]{direction:ltr;text-align:right}
.nb-form .nb-btn{justify-self:start;margin-top:4px}
.nb-hp{position:absolute!important;inset-inline-start:-9999px;height:1px;overflow:hidden}
.nb-map-box{position:relative;overflow:hidden;width:100%;border:1px solid var(--line);border-radius:var(--r,16px);background:color-mix(in srgb,var(--brand) 6%,var(--card,#fff))}
.nb-map-tile{position:absolute;display:block;width:256px;height:256px;max-width:none;border-radius:0;z-index:1;color:transparent}
.nb-map-tile::after{content:"";position:absolute;inset:0;background:color-mix(in srgb,var(--brand) 6%,var(--card,#fff))}
.nb-map-empty{flex:1 1 100%;margin:2px 0 0;font-size:.85rem;color:var(--ink-3,#666)}
.nb-map-pin{position:absolute;top:50%;left:50%;width:22px;height:22px;margin:-22px 0 0 -11px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:var(--brand);border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.35);z-index:2}
.nb-map-credit{position:absolute;bottom:0;right:0;padding:1px 6px;font-size:.68rem;line-height:1.5;background:rgba(255,255,255,.8);color:#333;text-decoration:none;z-index:2;direction:ltr}
.nb-map-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.nb-cards{display:grid;gap:20px}
.nb-card{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:var(--r,16px);overflow:hidden;display:flex;flex-direction:column;transition:transform .15s,box-shadow .15s}
.nb-card:hover{transform:translateY(-3px);box-shadow:0 18px 40px -22px rgba(0,0,0,.35)}
.nb-card-img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:var(--line)}
.nb-card-body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:6px;flex:1}
.nb-card-title{font-size:1.05rem;font-weight:800;margin:0;line-height:1.5}
.nb-card-title a,.nb-card>a{color:inherit;text-decoration:none}
.nb-card-text{margin:0;color:var(--ink-2);font-size:.93rem;line-height:1.85}
.nb-card-meta{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 10px;font-size:.92rem;align-items:baseline}
.nb-card-meta span{color:var(--ink-3);font-size:.82rem}
.nb-card-meta b{color:var(--brand);font-weight:800}
.nb-card-cart{margin-top:auto;padding-top:8px}
.nb-card-cart .nb-btn{width:100%}
.nb-empty{color:var(--ink-3);text-align:center;padding:24px;grid-column:1/-1;margin:0}
.nb-detail{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:32px;align-items:start}
.nb-detail:not(:has(.nb-detail-media)){grid-template-columns:minmax(0,1fr)}
.nb-detail-media img{width:100%;height:auto;display:block;border-radius:var(--r,16px)}
.nb-detail-body{display:grid;gap:12px}
.nb-detail-title{font-size:clamp(1.6rem,3.6vw,2.3rem);font-weight:900;margin:0;line-height:1.3}
.nb-detail-text{line-height:2;color:var(--ink-2)}
.nb-header{background:var(--card);color:var(--ink);border-bottom:1px solid var(--line);z-index:40;position:relative}
.nb-header.is-sticky{position:sticky;top:0}
.nb-wrap.nb-header-in>*+*{margin-top:0}
.nb-header-in{display:flex;align-items:center;gap:18px;min-height:66px;padding-block:8px;flex-wrap:wrap}
.nb-brand{display:inline-flex;align-items:center;gap:10px;font-weight:900;font-size:1.2rem;color:var(--brand);text-decoration:none;line-height:1.3}
.nb-logo{width:auto;display:block}
.nb-nav{display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.nb-nav a{color:inherit;text-decoration:none;padding:7px 13px;border-radius:999px;font-size:.96rem;font-weight:500;transition:background .15s,color .15s}
.nb-nav a:hover,.nb-nav a.on{background:color-mix(in srgb,var(--brand) 12%,transparent);color:var(--brand)}
.nb-header-extra{display:flex;align-items:center;gap:10px;margin-inline-start:auto}
.nb-cart{position:relative;display:inline-grid;place-items:center;width:40px;height:40px;border-radius:50%;border:1px solid var(--line);color:inherit}
.nb-badge{position:absolute;top:-4px;inset-inline-end:-4px;min-width:18px;height:18px;padding:0 4px;border-radius:999px;background:var(--brand);color:var(--brand-ink,#fff);font-size:.7rem;line-height:18px;text-align:center}
.nb-sub{position:relative;display:inline-flex}
.nb-sub>a{display:inline-flex;align-items:center;gap:6px}
.nb-caret{display:inline-block;width:0;height:0;border-inline:4px solid transparent;border-top:5px solid currentColor;opacity:.55}
.nb-sub-menu{display:none;position:absolute;top:100%;inset-inline-start:0;min-width:190px;padding:6px;flex-direction:column;align-items:stretch;gap:2px;background:var(--card,#fff);color:var(--text,#111);border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 30px rgba(0,0,0,.14);z-index:60}
.nb-sub-menu a{display:block;border-radius:8px;white-space:nowrap}
.nb-sub:hover .nb-sub-menu,.nb-sub:focus-within .nb-sub-menu{display:flex}
.nb-nav-toggle{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}
.nb-burger{display:none;width:42px;height:42px;border-radius:10px;border:1px solid var(--line);cursor:pointer;flex-direction:column;align-items:center;justify-content:center;gap:4px;order:3}
.nb-burger i{display:block;width:18px;height:2px;border-radius:2px;background:currentColor}
.nb-nav-toggle:focus-visible+.nb-burger{outline:3px solid color-mix(in srgb,var(--brand) 45%,transparent)}
.nb-footer{margin-top:0}
.nb-footer a{color:inherit;text-decoration:none}
.nb-footer a:hover{color:var(--brand)}
.nb-menu-links{display:grid;gap:6px}
.nb-copy{margin:0;font-size:.88rem;opacity:.75}
.nb-blank{min-height:1em;min-width:40px}
@media (max-width:1024px){
  .nb-detail{gap:22px}
}
@media (max-width:760px){
  .nb-burger{display:inline-flex}
  .nb-nav{display:none;order:4;width:100%;flex-direction:column;align-items:stretch;padding-block:8px;border-top:1px solid var(--line)}
  .nb-nav-toggle:checked~.nb-nav{display:flex}
  .nb-sub{display:block}
  .nb-sub>a{display:flex;justify-content:space-between}
  .nb-sub .nb-sub-menu,.nb-sub:hover .nb-sub-menu{display:flex;position:static;min-width:0;padding:0 16px 4px;background:none;border:0;box-shadow:none;color:inherit}
  .nb-sub-menu a{white-space:normal;font-size:.92rem}
  .nb-caret{display:none}
  .nb-header-extra{order:2}
  .nb-burger{margin-inline-start:0}
}
@media (max-width:640px){
  .nb-hero-split,.nb-detail{grid-template-columns:minmax(0,1fr)}
  .nb-plan.is-featured{transform:none}
  .nb-actions .nb-btn{flex:1 1 auto}
}
""".strip()
