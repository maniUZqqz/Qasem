"""Page probes for the Instagram login flow: selectors, error reading, state classification."""
import asyncio
import random
import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Instagram renamed the login inputs (username/password -> email/pass); accept both.
SEL_USER = 'input[name="email"], input[name="username"]'
SEL_PASS = 'input[name="pass"], input[name="password"]'
SEL_CODE = ('input[name="verificationCode"], input[name="security_code"], '
            'input[autocomplete="one-time-code"]')
SEL_HOME = 'a[href="/direct/inbox/"], svg[aria-label="Home"], [aria-label="Home"]'

COOKIE_BUTTONS = [r"decline optional", r"only allow essential", r"allow essential", r"allow all cookies"]

# Pages that need a human (or a code): Instagram's newer "auth_platform" flow lives under its own path.
CHALLENGE_URLS = ("/auth_platform", "/challenge", "two_factor", "/accounts/suspended")
RE_CHALLENGE = re.compile(
    r"confirm it.s you|help us confirm|unusual login|suspicious login|verify your identity|"
    r"check your (email|phone|text)|enter the (6-digit |login |security |confirmation )?code|"
    r"we sent (you )?(a|an|the) (code|text|email)|try another way", re.I)
RE_ERROR_HINT = re.compile(
    r"incorrect|doesn.t belong|isn.t connected|can.t find an account|wait a few minutes|try again later|too many|"
    r"went wrong|suspended|disabled|automated|couldn.t|isn.t valid|not valid|invalid|isn.t right|expired|"
    r"check the (security )?code", re.I)
RE_NOISE = re.compile(r"being validated|loading", re.I)  # live-region chatter, never a complaint
SKIP_LINES = {"code", "continue", "try another way", "next", "back", "confirm", "submit"}
# Instagram's "continue as <remembered account> / use another profile" page.
RE_ANOTHER = r"^(use another (profile|account)|log into another account|switch accounts?)$"
RE_CONTINUE = r"^(continue|continue as .+|log in as .+)$"

# Error text on screen. Alert nodes that look like errors win; then error-looking lines of the form
# (or the whole page); a calm alert (an invisible live region, say) is returned last and never counts as an error.
JS_ALERT = """() => {
  const re = new RegExp("__ERR__", "i");
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.right > 0 && r.left < innerWidth;
  };
  const alerts = [...document.querySelectorAll('#slfErrorAlert, [data-testid="login-error-message"], [role="alert"]')]
    .filter(shown).map(el => (el.innerText || '').trim()).filter(Boolean);
  const hit = alerts.find(t => re.test(t));
  if (hit) return hit;
  const root = document.querySelector('form') || document.body;
  const lines = (root.innerText || '').split('\\n').map(s => s.trim()).filter(l => l && l.length < 240 && re.test(l));
  return lines.length ? lines.slice(0, 3).join(' ') : (alerts[0] || null);
}""".replace("__ERR__", RE_ERROR_HINT.pattern)

# Marks the one visible input that takes a verification code; the newer pages name it freely ("Code").
JS_MARK_CODE = """() => {
  document.querySelectorAll('[data-igs-code]').forEach(n => n.removeAttribute('data-igs-code'));
  const skip = /^(email|username|pass|password)$/i;
  const boxes = [...document.querySelectorAll('input')].filter(i => {
    const r = i.getBoundingClientRect(), t = (i.type || 'text').toLowerCase();
    return r.width > 0 && r.height > 0 && !i.disabled && !i.readOnly && !skip.test(i.name || '')
      && ['text', 'tel', 'number', 'search'].includes(t);
  });
  // the 2026 pages (auth_platform/codeentry) name the box only through a separate <label>: «Code»
  const label = (i) => [...(i.labels || [])].map(l => l.innerText || '').join(' ')
    + ' ' + ((document.getElementById(i.getAttribute('aria-labelledby') || '') || {}).innerText || '');
  const named = boxes.find(i => /code|otp|verif|security/i.test([i.name, i.id, i.autocomplete, i.placeholder, i.getAttribute('aria-label'), label(i)].join(' ')));
  const only = boxes.length === 1 && (/code/i.test(document.body.innerText || '') || location.pathname.includes('/codeentry')) ? boxes[0] : null;
  const el = named || only;
  if (el) el.setAttribute('data-igs-code', '1');
  return !!el;
}"""

# The profile header, read by meaning (aria-labels, alt text, title attributes, "<n> followers" text), never by
# Instagram's generated class names, which change. Returns null when the page has no profile header.
JS_PROFILE = """(want) => {
  const heads = [...document.querySelectorAll('header')];
  const header = heads.find(h => [...h.querySelectorAll('h1, h2')].some(e => (e.innerText || '').trim().toLowerCase() === want.toLowerCase())) || heads[0];
  if (!header) return null;
  const text = (el) => ((el && el.innerText) || '').trim();
  const out = {username: text(header.querySelector('h2, h1')), verified: !!header.querySelector('svg[aria-label="Verified"]')};
  const img = header.querySelector('img[alt*="profile picture"]');
  out.avatar = img ? (img.currentSrc || img.src) : null;

  const re = /^(\\d[\\d.,]*\\s?[KkMmBb]?)\\s+(posts?|followers?|following)$/;
  const stats = {}, els = {};
  for (const el of header.querySelectorAll('*')) {
    const m = text(el).match(re);
    if (!m || [...el.children].some(c => re.test(text(c)))) continue;
    const kind = m[2].toLowerCase().replace(/s$/, '');
    const titled = el.querySelector('[title]');
    stats[kind] = {text: m[1].replace(/\\s/g, ''), title: titled ? titled.getAttribute('title') : el.getAttribute('title')};
    els[kind] = el;
  }
  out.stats = stats;

  // The block after the stats row holds the bio and the link; the block before it holds the full name.
  const found = Object.values(els);
  let row = found[0];
  while (row && !found.every(e => row.contains(e))) row = row.parentElement;
  if (row) {
    const before = row.previousElementSibling;
    out.full_name = before && !before.querySelector('h1, h2') ? text(before) : null;
    const sec = row.closest('section') || header;  // never look past the section that holds the stats
    let node = row;
    while (node.parentElement && node.parentElement !== sec && !node.nextElementSibling) node = node.parentElement;
    const block = node.nextElementSibling;
    if (block) {
      const button = [...block.querySelectorAll('button')].find(b => b.querySelector('svg[aria-label="Link icon"]'));
      out.link_text = button ? text(button) : null;
      const lines = text(block).split('\\n').map(s => s.trim()).filter(Boolean).filter(l => l !== out.link_text);
      out.mutual = lines.find(l => /^Followed by /i.test(l)) || null;
      const bio = lines.filter(l => !/^Followed by /i.test(l) && !/^(Follow|Following|Message|Edit profile|View archive)$/i.test(l));
      out.bio = bio.join('\\n');
      out.hrefs = [...block.querySelectorAll('a[href]')].map(a => a.href).filter(h => /^https?:/.test(h) && !h.endsWith('#'));
    }
  }
  const body = document.body.innerText || '';
  out.private_note = /This account is private/i.test(body);
  out.has_posts = !!document.querySelector('main a[href*="/p/"], main a[href*="/reel/"]');
  return out;
}"""

JS_META = """() => {
  const get = (sel) => (document.querySelector(sel) || {}).content || null;
  return {og_title: get('meta[property="og:title"]'), og_description: get('meta[property="og:description"]'),
          description: get('meta[name="description"]'), og_image: get('meta[property="og:image"]'), title: document.title};
}"""

# The like count of a post, in its action bar (the section that holds both the Like and the Comment icons).
# It is the first number there; the comment count is the second. Marks it so Playwright can click it.
JS_LIKES_MARK = """() => {
  document.querySelectorAll('[data-igs-likes]').forEach(n => n.removeAttribute('data-igs-likes'));
  const bar = [...document.querySelectorAll('section')].find(s => s.querySelector('svg[aria-label="Comment"]') && s.querySelector('svg[aria-label="Like"], svg[aria-label="Unlike"]'));
  if (!bar) return null;
  const counts = [...bar.querySelectorAll('span[role="button"]')].filter(e => /^[\\d.,]+\\s?[KMB]?$/i.test((e.innerText || '').trim()));
  if (!counts.length) return null;
  counts[0].setAttribute('data-igs-likes', '1');
  return {likes: counts[0].innerText.trim(), comments: counts[1] ? counts[1].innerText.trim() : null};
}"""

# The scrollable list of comments next to a post: the tallest scrollable block that has comments (a "Reply" button) in it.
JS_COMMENT_PANE = """() => {
  const c = [...document.querySelectorAll('div, ul')].filter(e => e.scrollHeight > e.clientHeight + 40 && getComputedStyle(e).overflowY !== 'visible' && e.clientHeight > 150);
  c.sort((a, b) => b.scrollHeight - a.scrollHeight);
  const e = c.find(x => (x.innerText || '').includes('Reply')) || c[0];
  if (!e) return null;
  const r = e.getBoundingClientRect();
  return {x: r.x + r.width / 2, y: r.y + r.height / 2};
}"""

JS_LINES = "() => (document.body.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 14)"

# What a page offers, for the technical details when a step is unfamiliar.
JS_DESCRIBE = """() => {
  const shown = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const attrs = (i) => [i.type || 'text', i.name && 'name=' + i.name, i.getAttribute('aria-label') && 'label=' + i.getAttribute('aria-label'),
    i.autocomplete && 'ac=' + i.autocomplete, i.placeholder && 'ph=' + i.placeholder].filter(Boolean).join(' ');
  return {
    lines: (document.body.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 12),
    inputs: [...document.querySelectorAll('input')].filter(shown).slice(0, 6).map(attrs),
    buttons: [...document.querySelectorAll('button, [role=button]')].filter(shown).map(b => (b.innerText || '').trim()).filter(Boolean).slice(0, 8),
  };
}"""

# The nav avatar's alt text is "<username>'s profile picture" once logged in.
JS_WHO = """() => {
  for (const img of document.querySelectorAll('img[alt]')) {
    const m = img.alt.match(/^(.+?).s profile picture$/i);
    if (m) return {username: m[1], avatar: img.currentSrc || img.src};
  }
  return null;
}"""


async def pause(lo=0.5, hi=1.2):
    await asyncio.sleep(random.uniform(lo, hi))


async def human_type(page, text):
    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.05, 0.16))


async def is_visible(page, selector):
    try:
        return await page.locator(selector).first.is_visible()
    except Exception:
        return False


async def click_button(page, pattern):
    """Click the first visible button, link or text matching pattern (Instagram uses all three)."""
    target = await find_visible(page, pattern)
    if target is None:
        return False
    try:
        await target.click(timeout=3000)
        return True
    except Exception:
        return False


async def find_visible(page, pattern):
    """First visible button, link or text matching pattern, or None."""
    rx = re.compile(pattern, re.I)
    for loc in (page.get_by_role("button", name=rx), page.get_by_role("link", name=rx), page.get_by_text(rx)):
        try:
            if await loc.count() and await loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


async def dismiss_cookie_banner(page):
    for pattern in COOKIE_BUTTONS:
        if await click_button(page, pattern):
            return pattern
    return None


async def read_alert(page):
    """The error text Instagram shows on screen, whitespace-collapsed, or None."""
    try:
        text = await page.evaluate(JS_ALERT)
    except Exception:
        return None
    return " ".join(text.split())[:400] if text else None


def error_text(text):
    """Only error-looking text counts as Instagram's complaint; live-region chatter does not."""
    return text if text and RE_ERROR_HINT.search(text) else None


async def mark_code_input(page):
    """Find the verification-code box even when its name is unknown; code_locator() then finds it."""
    try:
        return bool(await page.evaluate(JS_MARK_CODE))
    except Exception:
        return False


async def code_locator(page):
    if await is_visible(page, SEL_CODE):
        return page.locator(SEL_CODE).first
    return page.locator('[data-igs-code="1"]').first


async def page_lines(page):
    try:
        return await page.evaluate(JS_LINES)
    except Exception:
        return []


RE_NOT_FOUND = re.compile(r"sorry, this page isn.t available", re.I)


async def not_found_text(page):
    """Instagram's own 'page isn't available' sentence (with the line under it), or None."""
    lines = await page_lines(page)
    for i, line in enumerate(lines):
        if RE_NOT_FOUND.search(line):
            return " ".join(lines[i:i + 2])[:300]
    return None


async def page_text(page):
    """The first lines Instagram shows on the page, verbatim (for example 'Check your email')."""
    keep = [t for t in await page_lines(page)
            if len(t) > 3 and t.lower() not in SKIP_LINES and not RE_NOISE.search(t)]
    return "\n".join(keep[:4])[:320] or None


RE_UNAVAILABLE = re.compile(r"page isn.t available", re.I)


async def unavailable(page):
    """Instagram's «Page isn't available» screen. Since 2026-10 /accounts/login/ shows it to some visitors (the server):
    the login form is on the home page instead."""
    try:
        return bool(RE_UNAVAILABLE.search((await page.locator("body").inner_text(timeout=1500))[:600]))
    except Exception:
        return False


async def page_kind(page):
    """Which page is this? 'form' (login inputs), 'home' (signed in), 'chooser' (continue as the
    remembered account, or use another) or 'other'."""
    if await is_visible(page, SEL_USER):
        return "form"
    if await ui_logged_in(page):
        return "home"
    if await find_visible(page, RE_ANOTHER):
        return "chooser"
    return "other"


async def chooser_account(page):
    """The username the chooser page offers: the line just above its Continue button."""
    lines = await page_lines(page)
    for i, line in enumerate(lines):
        if line.lower() == "continue" and i > 0 and re.fullmatch(r"[A-Za-z0-9._]{2,30}", lines[i - 1]):
            return lines[i - 1]
    return None


async def describe_page(page):
    """Path (never the query: it holds one-time tokens), inputs and buttons of the page."""
    out = {"page_url": urlparse(page.url).path}
    try:
        info = await page.evaluate(JS_DESCRIBE)
        out["page_lines"] = " / ".join(info["lines"])[:500]
        out["page_inputs"] = " | ".join(info["inputs"]) or "none"
        out["page_buttons"] = " | ".join(info["buttons"]) or "none"
    except Exception:
        pass
    return out


async def auth_cookies(ctx, base):
    """sessionid + ds_user_id exist only after Instagram accepted the login."""
    got = {c["name"]: c["value"] for c in await ctx.cookies(base)}
    if got.get("sessionid") and got.get("ds_user_id"):
        return {"user_id": got["ds_user_id"]}
    return None


async def ui_logged_in(page):
    return await is_visible(page, SEL_HOME) and not await is_visible(page, SEL_USER)


async def read_identity(page, wait=8.0):
    """Username + avatar of the signed-in account, read from the page itself."""
    loop = asyncio.get_event_loop()
    end = loop.time() + wait
    while loop.time() < end:
        try:
            who = await page.evaluate(JS_WHO)
        except Exception:
            who = None
        if who:
            return who
        await asyncio.sleep(0.5)
    return None


@dataclass
class Probe:
    kind: str                 # logged_in | need_code | need_manual | error | pending
    text: str | None = None   # on-screen alert text, calm or not; error_text() tells which
    form: bool = False        # the login form is still on screen


def on_challenge(page):
    """A page only a person can pass (a code, "confirm you're human"): Instagram sends every address there until it is done."""
    return any(part in (page.url or "") for part in CHALLENGE_URLS)


async def probe(page, ctx, base):
    # Before the cookies: a suspended account keeps them, yet every page is "confirm you're human" (2026-11-10).
    if on_challenge(page) and await auth_cookies(ctx, base):
        alert = await read_alert(page)
        if await is_visible(page, SEL_CODE) or await mark_code_input(page):
            return Probe("need_code", alert)
        return Probe("need_manual", alert)
    if await auth_cookies(ctx, base):
        return Probe("logged_in")
    form = await is_visible(page, SEL_USER)
    alert = await read_alert(page)
    if await is_visible(page, SEL_CODE) or (not form and await mark_code_input(page)):
        return Probe("need_code", alert, form)
    if error_text(alert):
        return Probe("error", alert, form)
    if on_challenge(page):
        return Probe("need_manual", alert, form)
    try:
        body = await page.locator("body").inner_text(timeout=1500)
    except Exception:
        body = ""
    if RE_CHALLENGE.search(body[:3000]):
        return Probe("need_manual", alert, form)
    return Probe("pending", alert, form)


def classify_error(text, stage="login"):
    """Map Instagram's own wording to a stable kind the UI can explain in Persian."""
    t = text.lower()
    if re.search(r"wait a few minutes|try again later|too many|few moments|temporarily", t):
        return "rate_limit"
    if stage == "code":
        return "bad_code"
    if re.search(r"automated", t):
        return "automated"
    if re.search(r"doesn.t belong to an account|isn.t connected to an account|can.t find an account", t):
        return "bad_username"
    if re.search(r"password.{0,40}incorrect|incorrect.{0,25}password|wrong password", t):
        return "bad_password"
    if re.search(r"login information|check your (username|login)|incorrect", t):
        return "bad_credentials"
    if re.search(r"disabled|suspended|locked|violat", t):
        return "disabled"
    return "other"


def refine(kind, api):
    """Instagram's JSON says whether the username exists; use it when the text can't tell."""
    if kind not in ("bad_credentials", "other") or not api:
        return kind
    if api.get("user") == "False":
        return "bad_username"
    if api.get("user") == "True" and api.get("authenticated") == "False":
        return "bad_password"
    return kind
