# -*- coding: utf-8 -*-
"""CSSِ مشترکِ قطعه‌های آماده. همه‌چیز با متغیرهای پوسته (--brand، --ink، --card، --line، --r) و متغیرهای سبک (--st-*، با مقدارِ پیش‌فرض)
نوشته شده؛ پس با عوضِ شدنِ سبک یا رنگ، قطعه‌ها هم عوض می‌شوند. راست‌به‌چپ با ویژگی‌های منطقی (inline/block/start/end)."""

BASE = r"""
.nbc{--nbc-gap:var(--st-gap,24px);position:relative}
.nbc .nb-wrap{max-width:var(--nb-width,1140px);margin-inline:auto;padding-inline:20px;width:100%}
.nbc.nb-section{padding-block:var(--st-sec-py,clamp(44px,7vw,84px))}
.nbc .nb-wrap>*+*{margin-top:0}
.nbc,.nbc *{box-sizing:border-box}.nbc img{max-width:100%;height:auto}
.nbc .nbc-kicker{display:inline-block;font-size:.84rem;font-weight:700;color:var(--brand);margin:0 0 12px;letter-spacing:.01em}
.nbc .nbc-title{font-family:var(--nb-font-head,inherit);font-size:clamp(1.7rem,4vw,2.75rem);font-weight:var(--st-head-w,800);line-height:1.28;letter-spacing:var(--st-head-ls,-.01em);margin:0 0 14px;text-transform:var(--st-head-tt,none)}
.nbc .nbc-h3{font-family:var(--nb-font-head,inherit);font-size:1.18rem;font-weight:var(--st-head-w,800);line-height:1.5;margin:0 0 6px}
.nbc .nbc-lead{font-size:1.06rem;line-height:2;color:var(--ink-2);margin:0 0 22px;max-width:62ch}
.nbc .nbc-text{color:var(--ink-2);line-height:1.95;margin:0;font-size:.97rem}
.nbc .nbc-muted{color:var(--ink-3);font-size:.88rem}
.nbc .nbc-head{max-width:720px;margin:0 auto clamp(26px,4vw,44px);text-align:center}
.nbc .nbc-head.is-start{margin-inline:0;text-align:start}
.nbc .nbc-head .nbc-lead{margin-inline:auto}
.nbc .nbc-head.is-start .nbc-lead{margin-inline:0}
.nbc .nbc-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:12px 26px;font:inherit;font-weight:700;line-height:1.5;text-decoration:none;cursor:pointer;
  border-radius:var(--nb-btn-radius,999px);border:var(--st-btn-bw,1.5px) solid var(--st-btn-bc,transparent);background:var(--brand);color:var(--brand-ink,#fff);
  box-shadow:var(--st-btn-sh,0 10px 22px -12px var(--brand));transition:transform .15s,filter .15s,box-shadow .15s;white-space:nowrap}
.nbc .nbc-btn:hover{transform:translateY(-1px);filter:brightness(1.06)}
.nbc .nbc-btn:focus-visible{outline:3px solid color-mix(in srgb,var(--brand) 45%,transparent);outline-offset:2px}
.nbc .nbc-btn.is-alt{background:transparent;color:var(--brand);border-color:var(--brand);box-shadow:none}
.nbc .nbc-btn.is-ghost{background:transparent;color:inherit;border-color:color-mix(in srgb,currentColor 38%,transparent);box-shadow:none}
.nbc .nbc-btn.is-light{background:var(--brand-ink,#fff);color:var(--brand);box-shadow:none}
.nbc .nbc-btn .nb-svg{width:18px;height:18px}
.nbc .nbc-btns{display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.nbc .nbc-card{background:var(--st-card-bg,var(--card));color:var(--ink);border:var(--st-card-bd,1px solid var(--line));border-radius:var(--st-card-r,var(--r,16px));
  box-shadow:var(--st-card-sh,0 1px 2px rgba(0,0,0,.03),0 12px 28px -22px rgba(0,0,0,.25));padding:clamp(18px,2.4vw,26px);-webkit-backdrop-filter:var(--st-bf,none);backdrop-filter:var(--st-bf,none)}
.nbc .nbc-img{width:100%;height:auto;display:block;border-radius:var(--st-card-r,var(--r,16px));object-fit:cover}
.nbc .nbc-ic{display:inline-grid;place-items:center;width:48px;height:48px;flex:none;border-radius:var(--st-ic-r,14px);background:var(--st-ic-bg,color-mix(in srgb,var(--brand) 13%,transparent));color:var(--st-ic-fg,var(--brand))}
.nbc .nbc-ic .nb-svg{width:24px;height:24px}
.nbc .nbc-grid{display:grid;gap:var(--nbc-gap)}
.nbc .nbc-auto{grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr))}
.nbc .nbc-c2{grid-template-columns:repeat(2,minmax(0,1fr))}
.nbc .nbc-c3{grid-template-columns:repeat(3,minmax(0,1fr))}
.nbc .nbc-c4{grid-template-columns:repeat(4,minmax(0,1fr))}
.nbc .nbc-split{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:clamp(24px,5vw,64px);align-items:center}
.nbc .nbc-list{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.nbc .nbc-list li{display:flex;gap:10px;align-items:flex-start;color:var(--ink-2);line-height:1.8}
.nbc .nbc-list .nb-svg,.nbc .nbc-check{width:20px;height:20px;flex:none;color:var(--brand);margin-top:4px}
.nbc .nbc-pill{display:inline-flex;align-items:center;gap:6px;padding:5px 14px;border-radius:999px;font-size:.84rem;font-weight:600;background:color-mix(in srgb,currentColor 12%,transparent)}
.nbc .nbc-links{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.nbc .nbc-links a,.nbc a.nbc-link{color:inherit;text-decoration:none;opacity:.86}
.nbc .nbc-links a:hover,.nbc a.nbc-link:hover{opacity:1;color:var(--brand);text-decoration:underline;text-underline-offset:4px}
.nbc .nbc-avatar{width:48px;height:48px;border-radius:50%;object-fit:cover;flex:none}
.nbc .nbc-on-dark{color:var(--brand-ink,#fff)}
@media (max-width:1024px){.nbc .nbc-c4,.nbc .nbc-c3{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:760px){.nbc .nbc-split{grid-template-columns:minmax(0,1fr)}}
@media (max-width:640px){.nbc .nbc-c2,.nbc .nbc-c3,.nbc .nbc-c4{grid-template-columns:minmax(0,1fr)}.nbc .nbc-btns .nbc-btn{flex:1 1 auto}}
""".strip()
