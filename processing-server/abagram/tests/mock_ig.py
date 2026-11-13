"""A tiny stand-in for instagram.com, used only to test the login flow offline.

Log in as: good | wrongpass | nouser | newwrong | limit | twofa | challenge
"""
import json
import re
import sys
import time
import zlib
from urllib.parse import unquote

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

app = FastAPI()
STATE = {"approved": False, "manual": False, "expired": False, "no_onetap": False, "hits": {}, "requested": set(), "accepted": set()}
PIXEL = "data:image/gif;base64,R0lGODlhAQABAAAAACw="

LOGIN = """<!doctype html><meta charset=utf-8><title>Login</title>
<h1>Log into Instagram</h1>
<form id=f><input name=email aria-label="Mobile number, username or email" autocomplete="username webauthn">
<input name=pass type=password><input type=submit value="Log in"><p id=err role=alert></p></form>
<script>
f.onsubmit = async (e) => {
  e.preventDefault();
  const body = JSON.stringify({email: f.email.value, pass: f.pass.value});
  const j = await (await fetch('/api/v1/web/accounts/login/ajax/', {method: 'POST', body})).json();
  if (j.authenticated) location = '/';
  else if (j.two_factor_required) location = '/accounts/login/two_factor/';
  else if (j.checkpoint_url) location = j.checkpoint_url;
  else err.textContent = j.message || '';
};
</script>"""

TWO_FACTOR = """<!doctype html><meta charset=utf-8><title>2FA</title>
<form id=f><p>Enter the 6-digit code</p><input name=verificationCode><button type=submit>Confirm</button>
<p id=err role=alert></p></form>
<script>
f.onsubmit = async (e) => {
  e.preventDefault();
  const body = JSON.stringify({code: f.verificationCode.value});
  const j = await (await fetch('/api/v1/web/accounts/login/ajax/two_factor/', {method: 'POST', body})).json();
  if (j.authenticated) location = '/'; else err.textContent = j.message;
};
</script>"""

CHALLENGE = """<!doctype html><meta charset=utf-8><title>Challenge</title><h1>Help us confirm it's you</h1>
<script>
setInterval(async () => {
  if ((await (await fetch('/challenge/state')).json()).approved) {
    await fetch('/challenge/finish', {method: 'POST'}); location = '/';
  }
}, 400);
</script>"""

# The newer flow: an unnamed code box, a Continue that is no <button>, and an invisible live region that
# always says "validated" (the page that made the first version report a false error).
CODE_ENTRY = """<!doctype html><meta charset=utf-8><title>Instagram</title>
<div>mock_user • Instagram</div><h1>Check your email</h1>
<p>Enter the code we sent to a*****z@example.com</p>
<input type="text" aria-label="Code" id=c autocomplete="off">
<span>It may take a few minutes for you to get this code. <a href="#">Get a new code</a></span>
<div role="alert" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Input Code is being validated.</div>
<p id=bad hidden>That code isn't valid. You can request a new one.</p>
<div role=button id=go>Continue</div><div role=button>Try another way</div>
<script>
async function verify(code) {
  const j = await (await fetch('/auth_platform/verify', {method: 'POST', body: JSON.stringify({code})})).json();
  if (j.ok) location = '/'; else bad.hidden = false;
}
go.onclick = () => verify(c.value);
setInterval(async () => {  // "the user typed the code in the window by hand"
  if ((await (await fetch('/auth_platform/state')).json()).manual) verify('654321');
}, 400);
</script>"""

# ---- profile pages: the real header structure (see tests/fixtures), a few kinds of account ----
MP4 = bytes.fromhex("00000018" "66747970" "6d703432" "00000000" "6d703432" "69736f6d") + bytes(range(256)) * 1600   # about 400 KB, starting like a real MP4 (an ftyp box)
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8cfc0f00f0005010100"
                    "a1a5a3a40000000049454e44ae426082")
NAV = '<nav><a href="/direct/inbox/">Inbox</a><svg aria-label="Home" width=24 height=24></svg></nav>'
PROFILES = {  # name: shown name, bio, counts as the page shows them, how Instagram's API replies (flat | legacy | none)
    "ada.lovelace": dict(name="Ada Lovelace", bio="first programmer\nnotes below", posts="340", followers="1.2M", title="1,234,567",
                         following="12", verified=True, link="notes.example.org and 1 more", api="flat", prefix=True, post_n=7),
    "locked.user": dict(name="Locked User", bio="", posts="0", followers="900", title=None, following="15", private=True, api="legacy"),
    "bare.user": dict(name="", bio="", posts="3", followers="42", title=None, following="7", api="none"),
    "dom.only": dict(name="Dom Only", bio="no api reply here", posts="1,204", followers="1.5K", title=None, following="88", api="none"),
    "empty.user": dict(name="Empty User", bio="", posts="0", followers="0", title=None, following="0", api="none"),
    "liar.user": dict(name="Liar User", bio="", posts="0", followers="5", title=None, following="0", api="none", list_total=40),   # the list is longer than the count says
    "deny.user": dict(name="Deny User", bio="", posts="0", followers="30", title=None, following="30", api="none", deny=True),    # the dialog opens, Instagram refuses the list
    "wait.user": dict(name="Wait User", bio="", posts="0", followers="30", title=None, following="30", api="none", deny="wait"),    # ... with 'feedback_required' (an action block)
    "relog.user": dict(name="Relog User", bio="", posts="0", followers="30", title=None, following="30", api="none", deny="login"),  # ... with 'login_required' (the session is gone)
    "many.posts": dict(name="Many Posts", bio="forty posts", posts="40", followers="10", title=None, following="3", api="none", post_n=40),
    "limited": dict(limited=True, api="429"),
}


def mock_id(user):
    """Every mock person's numeric id (Instagram's pk): fixed, so a profile can be asked for by id like the real page does."""
    return "1815" if user == "ada.lovelace" else str(2000 + list(PROFILES).index(user)) if user in PROFILES else ""


def graphql_script(user, with_posts=False):
    """The page asks for its data the way Instagram's page does: one POST per query, answered as text/javascript."""
    calls = [("PolarisProfilePageContentQuery", 700)] + ([("PolarisProfilePostsQuery", 1100), ("PolarisProfileStoryHighlightsTrayContentQuery", 900),
                                                          ("PolarisProfileSuggestedUsersWithPreloadableQuery", 1300)] if with_posts else [])
    return "".join(
        "setTimeout(() => fetch('/api/graphql', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},"
        f" body: 'fb_api_req_friendly_name={name}&variables=' + encodeURIComponent(JSON.stringify({{username: '{user}'}}))}}), {ms});"
        for name, ms in calls)


def mock_post(user, i, base):
    """Post number i of a user, newest first. 0 album, 1 reel with a song, 2 photo at a place, 3 hidden likes, 4 comments off,
    5 pinned and old, 6 video."""
    code = f"Mk{i:02d}{zlib.crc32(user.encode()) % 10 ** 7:07d}"
    media, product = {0: (8, "carousel_container"), 1: (2, "clips"), 6: (2, "feed")}.get(i, (1, "feed"))
    pic = lambda w: {"url": f"{base}/cdn/avatar.png?w={w}&c={code}", "width": w, "height": w}  # noqa: E731
    node = {"code": code, "pk": str(4000000 + i), "id": f"{4000000 + i}_77", "taken_at": 1792500000 - i * 86400 - (4000000 if i == 5 else 0),
            "media_type": media, "product_type": product, "caption": {"text": f"Post {i} #tag{i} @friend.{i}. Second sentence."},
            "user": {"username": user, "pk": "77"}, "like_count": 1000 + i, "comment_count": 40 if i == 0 else 10 + i,
            "image_versions2": {"candidates": [pic(1080), pic(640), pic(320), pic(240)]},
            "usertags": {"in": []}, "coauthor_producers": [], "timeline_pinned_user_ids": []}
    if i == 0:
        node.update(carousel_media_count=3, usertags={"in": [{"user": {"username": "tagged.one", "pk": "5", "full_name": "T One"}, "position": [0.5, 0.25]}]},
                    carousel_media=[{"code": f"{code}s{k}", "pk": f"{4100000 + k}", "media_type": 1, "carousel_parent_id": node["id"],
                                     "image_versions2": {"candidates": [pic(1080), pic(320)]}} for k in range(3)])
    if i == 1:
        node.update(video_versions=[{"url": f"{base}/cdn/v.mp4", "width": 720, "height": 1280, "type": 101}], play_count=12345,
                    coauthor_producers=[{"username": "co.author", "pk": "9"}],
                    clips_metadata={"audio_type": "licensed_music", "music_info": {"music_asset_info": {"title": "Song", "display_artist": "Singer"}}})
    if i == 2:
        node["location"] = {"pk": 55, "name": "Tehran", "city": "Tehran", "lat": 35.7, "lng": 51.4}
    if i == 3:
        node.update(like_and_view_counts_disabled=True, like_count=0)
    if i == 4:
        node["comments_disabled"] = True
    if i == 5:
        node["timeline_pinned_user_ids"] = ["77"]
    if i == 6:
        node["video_versions"] = [{"url": f"{base}/cdn/v.mp4?big=1", "width": 640, "height": 640, "type": 101}]   # the one video that is 3 MB
    return node


def highlights_body(user, base):
    node = lambda i, title: {"node": {"id": f"highlight:500000{i}", "title": title, "user": {"username": user, "id": "77"}, "__typename": "XDTReelDict",  # noqa: E731
                                      "cover_media": {"cropped_image_version": {"url": f"{base}/cdn/avatar.png?hl={i}"}}}, "cursor": ""}
    return json.dumps({"data": {"highlights": {"edges": [node(1, "Trips"), node(2, "🎶 Music"), node(3, "Work")],
                                              "page_info": {"has_next_page": False, "end_cursor": None}}}})


def similar_body(base):
    users = [{"pk": str(9000 + i), "id": str(9000 + i), "username": f"similar.{i}", "full_name": f"Similar {i}", "is_verified": i % 2 == 0,
              "is_private": i == 3, "profile_pic_url": f"{base}/cdn/avatar.png?s={i}"} for i in range(5)]
    return json.dumps({"data": {"xdt_api__v1__discover__chaining": {"users": users}}})


# The grid of a long profile: the next twelve posts are asked for when the page is scrolled near its end, and the page grows with them.
GRID_JS = """
(() => {
  let cursor = '12', more = true, busy = false;
  const grid = document.getElementById('grid');
  async function next() {
    if (busy || !more) return;
    busy = true;
    const body = 'fb_api_req_friendly_name=PolarisProfilePostsTabContentQuery_connection&variables='
      + encodeURIComponent(JSON.stringify({after: cursor, before: null, data: {count: 12}, username: '__USER__'}));
    const r = await fetch('/api/graphql', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body});
    const j = JSON.parse(await r.text()).data.xdt_api__v1__feed__user_timeline_graphql_connection;
    for (const e of j.edges) grid.insertAdjacentHTML('beforeend', '<a href="/p/' + e.node.code + '/">' + e.node.code + '</a> ');
    grid.style.minHeight = (grid.offsetHeight + 1200) + 'px';   // the page grows with every batch, like a real grid
    more = j.page_info.has_next_page; cursor = j.page_info.end_cursor || ''; busy = false;
  }
  window.addEventListener('scroll', () => { if (innerHeight + scrollY >= document.documentElement.scrollHeight - 300) next(); });
})();
"""


# ---- followers / following: a dialog on the profile page that asks for pages of twelve and loads the next one when its marker shows ----
def uid_of(user):
    return 500000 + zlib.crc32(user.encode()) % 100000


def total_of(spec, which):
    """How many people the list really has, from the numbers the page shows (or the spec's own say, when the page's count is stale)."""
    if which == "followers" and spec.get("list_total"):
        return spec["list_total"]
    shown = spec.get("title") if which == "followers" and spec.get("title") else spec[which]
    m = re.fullmatch(r"([\d,]+(?:\.\d+)?)([KM]?)", shown)
    return int(float(m.group(1).replace(",", "")) * {"": 1, "K": 1000, "M": 10 ** 6}[m.group(2)])


def follow_user(owner, which, k):
    user = {"pk": str(7000000 + k), "id": str(7000000 + k), "pk_id": str(7000000 + k), "username": f"{which[:3]}_{owner.split('.')[0]}_{k}",
            "full_name": f"{which.title()} {k}", "is_private": k % 5 == 0, "is_verified": k % 7 == 0, "account_badges": [],
            "profile_pic_url": f"https://scontent-mock.cdninstagram.com/v/anon_{k}.jpg", "has_anonymous_profile_picture": k % 9 == 0,
            "latest_reel_media": 1792500000 if k % 6 == 0 else 0}
    if which == "following":
        user["is_favorite"] = k % 4 == 0
    return user


def follow_reply(owner, which, offset, count):
    """Instagram's reply for one page: pages of `count`, a next id while there are more, and big accounts cut to fifty people."""
    total = total_of(PROFILES[owner], which)
    limited = which == "followers" and total >= 100000
    end = min(total, 50) if limited else min(total, offset + count)
    more = not limited and end < total
    doc = {"users": [follow_user(owner, which, k) for k in range(offset, end)], "big_list": total > count, "page_size": 50 if limited else count}
    if more:
        doc["next_max_id"] = str(end)
    doc.update(has_more=more, should_limit_list_of_followers=limited, use_clickable_see_more=False, follow_ranking_token="mock|1|osr",
               should_limit_list_of_followings=False, status="ok")
    if which == "following":
        doc["hidden_following_account_count"] = 2 if owner == "bare.user" else 0
    return doc


# The dialog like Instagram's: a title, a search box, a scrolling block with the people, a marker that loads the next page only when it
# comes into view (an IntersectionObserver: a jump past it loads nothing), then "Suggested for you" below, and a close button.
LIST_JS = """
async function openList(which) {
  document.querySelectorAll('[role=dialog]').forEach(d => d.remove());
  const dlg = document.createElement('div');
  dlg.setAttribute('role', 'dialog'); dlg.setAttribute('aria-modal', 'true');
  dlg.style.cssText = 'position:fixed;left:25%;top:8%;width:420px;background:#fff;color:#000;z-index:99;border:1px solid #888';
  const sug = Array.from({length: 15}, (_, i) => '<div class="row" style="height:60px"><a href="/sug_' + i + '/">sug_' + i + '</a> <span>Instagram recommended</span><button>Follow</button></div>').join('');
  dlg.innerHTML = '<div role="heading" aria-level="1">' + (which === 'followers' ? 'Followers' : 'Following') + '</div><input aria-label="Search input" placeholder="Search">'
    + '<div id="sc" style="height:309px;overflow-y:auto"><div id="rows"></div><div id="mark" style="height:2px"></div><div><h3>Suggested for you</h3>' + sug + '</div></div>'
    + '<button type="button" onclick="this.closest(\\'[role=dialog]\\').remove()"><svg aria-label="Close" width="18" height="18"></svg></button>';
  document.body.append(dlg);
  const sc = dlg.querySelector('#sc'), rows = dlg.querySelector('#rows');
  let next = '', more = true, busy = false;
  async function load() {
    if (busy || !more || !dlg.isConnected) return;
    busy = true;
    const q = '?count=12' + (which === 'followers' ? '&search_surface=follow_list_page' : '') + (next ? '&max_id=' + next : '');
    let j;
    try {
      const r = await fetch('/api/v1/friendships/__UID__/' + which + '/' + q, {headers: {'X-IG-App-ID': '936619743392459'}});
      if (!r.ok) { busy = false; return; }   // like the real page: a page Instagram refused is asked again on the next scroll
      j = await r.json();
    } catch (e) { return; }   // a connection broken on the way: like the real page (2026-10-30), the list never asks again
    for (const u of j.users) rows.insertAdjacentHTML('beforeend', '<div class="row" style="height:60px"><a href="/' + u.username + '/">' + u.username + '</a> <span>' + u.full_name + '</span><button>Follow</button></div>');
    more = j.has_more; next = j.next_max_id || ''; busy = false;
    fetch('/api/v1/friendships/show_many/', {method: 'POST', body: 'user_ids=' + j.users.map(u => u.pk).join('%2C')});
  }
  new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) load(); }, {root: sc}).observe(dlg.querySelector('#mark'));
  load();
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelectorAll('[role=dialog]').forEach(d => d.remove()); });
"""


# ---- stories and highlight items: the whole reel sits inside the page's HTML; "View story" would tell the owner ----
HIGHLIGHT_ITEMS = {"5000001": 4, "5000002": 120, "5000003": 1}   # highlight id -> how many items (the second one is longer than any cap)
HIGHLIGHT_TITLES = {"5000001": "Trips", "5000002": "🎶 Music", "5000003": "Work"}
STORY_ITEMS = {"ada.lovelace": 3}                                # who has an active story, and how many items


def reel_item(k, base, highlight, expired=False):
    """Item k of a reel: even ones are pictures, odd ones videos; the first carries a link, a mention, a hashtag, a song and a poll."""
    pk = f"{(9100000 if highlight else 9200000) + k}"
    extra = "&gone=1" if (not highlight and k == 2) else "&oe=5f000000" if expired else ""   # the third story picture is gone; one highlight's addresses ran out
    pic = lambda w: {"url": f"{base}/cdn/avatar.png?st={pk}&w={w}{extra}", "width": w, "height": w}  # noqa: E731
    item = {"pk": pk, "id": f"{pk}_77", "media_type": 2 if k % 2 else 1, "taken_at": 1792500000 - k * 600, "expiring_at": 1792586400 - k * 600,
            "image_versions2": {"candidates": [pic(1080), pic(640), pic(320)]}, "original_width": 1080, "original_height": 1920, "__typename": "XDTMediaDict"}
    if k % 2:
        item.update(video_versions=[{"url": f"{base}/cdn/v.mp4?st={pk}{extra}", "width": 720, "height": 1280, "type": 101}], video_duration=12.5, has_audio=True)
    if k == 0:
        item.update(story_link_stickers=[{"x": 0.5, "story_link": {"url": "https://shop.example/a?x=1", "link_title": "Shop"}}],
                    reel_mentions=[{"user": {"username": "friend.0", "pk": "5"}}], story_hashtags=[{"hashtag": {"name": "tag0"}}],
                    story_music_stickers=[{"music_asset_info": {"title": "Song", "display_artist": "Singer"}}], story_polls=[{"poll_id": 1}])
    return item


def reel_node(user, rid, base, count, highlight):
    node = {"id": rid, "reel_type": "highlight_reel" if highlight else "user_reel", "__typename": "XDTReelDict", "latest_reel_media": 1792500000,
            "user": {"username": user, "pk": "77", "id": "77"}, "items": [reel_item(k, base, highlight, rid.endswith("5000003")) for k in range(count)]}
    if highlight:
        node["title"] = HIGHLIGHT_TITLES[rid.split(":")[1]]
    return node


def reel_page(node, highlight):
    """What Instagram sends for a story address: the reel is in the HTML already; the viewer only starts after "View story"."""
    doc = ({"xdt_api__v1__feed__reels_media__connection": {"edges": [{"node": node}]}} if highlight
           else {"xdt_api__v1__feed__reels_media": {"reels_media": [node]}})
    return f"""<!doctype html><meta charset=utf-8><title>Instagram</title>
<main><h2>{node["user"]["username"]}</h2><p>{node.get("title", "")}</p><p>Viewing this story will let {node["user"]["username"]} know you saw it.</p>
<div role="button" id="view">View story</div></main>
<script type="application/json" data-sjs>{json.dumps({"data": doc})}</script>
<script>document.getElementById('view').onclick = () => fetch('/api/graphql', {{method: 'POST', headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
  body: 'fb_api_req_friendly_name=PolarisStoriesV3SeenMutation&variables=' + encodeURIComponent(JSON.stringify({{reelId: '{node["id"]}'}}))}});</script>"""


# ---- a post page: comments sit inside the page, more come on scroll, the likers on a click on the like count ----
def post_index():
    """code -> (user, i, post node) for every post the mock accounts have."""
    out = {}
    for user, spec in PROFILES.items():
        for i in range(spec.get("post_n") or 0):
            node = mock_post(user, i, "http://x")
            out[node["code"]] = (user, i, node)
    return out


def comment_edge(code, k):
    """Comment number k of a post; every fifth has replies."""
    return {"node": {"__typename": "XDTCommentDict", "pk": f"{7000000 + k}", "created_at": 1792400000 + k * 60, "text": f"Comment {k} on {code[:4]}",
                     "comment_like_count": k % 7, "child_comment_count": 3 if k % 5 == 0 else 0, "has_liked_comment": False, "is_edited": k == 2,
                     "is_pinned": True if k == 0 else None, "parent_comment_id": None, "giphy_media_info": None,
                     "user": {"pk": f"{8000000 + k}", "id": f"{8000000 + k}", "username": f"commenter_{k}", "is_verified": k % 4 == 0,
                              "profile_pic_url": "http://127.0.0.1/none.jpg"}}, "cursor": ""}


def comments_page(code, total, start, size=15):
    edges = [comment_edge(code, k) for k in range(start, min(total, start + size))]
    more = start + size < total
    return {"edges": edges, "page_info": {"has_next_page": more, "end_cursor": str(start + size) if more else None}}


def post_page(code, user, i, node, base):
    total = 0 if node.get("comments_disabled") else node["comment_count"]
    blob = json.dumps({"data": {"xdt_api__v1__media__media_id__comments__connection": comments_page(code, total, 0)}})
    likes = "" if node.get("like_and_view_counts_disabled") else f'<span role="button">{node["like_count"]}</span>'
    comments = "" if node.get("comments_disabled") else f'<span role="button">{node["comment_count"]}</span>'
    rows = "".join(f'<li><span>{e["node"]["user"]["username"]}</span> {e["node"]["text"]} <svg aria-label="Like" width="16" height="16"></svg>'
                   f'<div role="button">Reply</div></li>' for e in comments_page(code, total, 0)["edges"])
    return f"""<!doctype html><meta charset=utf-8><title>Instagram</title>{NAV}
<main><article><div id="side"><div id="pane" style="height:260px;overflow-y:auto"><ul id="list">{rows}</ul></div>
<section><div><span><div role="button"><svg aria-label="Like" width="24" height="24"></svg></div></span>{likes}
<span><div role="button"><svg aria-label="Comment" width="24" height="24"></svg></div></span>{comments}
<div role="button"><svg aria-label="Share" width="24" height="24"></svg></div></div></section></div></article></main>
<script type="application/json" data-sjs>{blob}</script>
<script>
const CODE = '{code}', PK = '{node["pk"]}'; let more = {str(total > 15).lower()}, cursor = '15', busy = false;
const pane = document.getElementById('pane');
pane.addEventListener('scroll', async () => {{
  if (busy || !more || pane.scrollTop + pane.clientHeight < pane.scrollHeight - 60) return;
  busy = true;
  const r = await fetch('/api/graphql', {{method: 'POST', headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
    body: 'fb_api_req_friendly_name=PolarisPostCommentsPaginationQuery&variables=' + encodeURIComponent(JSON.stringify({{after: cursor, code: CODE}}))}});
  const j = JSON.parse(await r.text()).data.xdt_api__v1__media__media_id__comments__connection;
  for (const e of j.edges) document.getElementById('list').insertAdjacentHTML('beforeend', '<li><span>' + e.node.user.username + '</span> ' + e.node.text + ' <svg aria-label="Like" width="16" height="16"></svg><div role="button">Reply</div></li>');
  more = j.page_info.has_next_page; cursor = j.page_info.end_cursor; busy = false;
}});
const count = document.querySelector('section span[role=button]');
if (count && /^[0-9.,KMB]+$/.test(count.innerText.trim()) && count === [...document.querySelectorAll('section span[role=button]')][0]) count.addEventListener('click', async () => {{
  const j = await (await fetch('/api/v1/media/' + PK + '/likers/')).json();
  document.body.insertAdjacentHTML('beforeend', '<div role="dialog"><h2>Likes</h2>' + j.users.map(u => '<a href="/' + u.username + '/">' + u.username + '</a>').join('') + '</div>');
}});
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') document.querySelectorAll('[role=dialog]').forEach(d => d.remove()); }});
</script>"""


PAGE_OF_POSTS = 12


def posts_body(user, spec, base, after=0):
    """The first twelve posts (the page's own query) or the twelve after `after` (what scrolling asks for), with the cursor for the next."""
    nodes = [mock_post(user, i, base) for i in range(spec["post_n"])]
    nodes.sort(key=lambda n: not n["timeline_pinned_user_ids"])  # pinned posts come first in the grid, whatever their age
    end = min(len(nodes), after + PAGE_OF_POSTS)
    return json.dumps({"data": {"xdt_api__v1__feed__user_timeline_graphql_connection": {
        "edges": [{"node": n} for n in nodes[after:end]], "page_info": {"has_next_page": end < len(nodes), "end_cursor": str(end) if end < len(nodes) else None}}}})


def profile_page(user, spec, base):
    esc = lambda s: s.replace("&", "&amp;").replace('"', "&quot;")  # noqa: E731
    name, bio = spec["name"], spec["bio"]
    counts = f"{spec['followers']} Followers, {spec['following']} Following, {spec['posts']} Posts"
    title = f' title="{spec["title"]}"' if spec.get("title") else ""
    verified = '<div><svg aria-label="Verified" role="img"><title>Verified</title></svg></div>' if spec.get("verified") else ""
    name_div = f'<div><span dir="auto">{name}</span></div>' if name else ""
    link = ('<div><button type="button"><div><span><svg aria-label="Link icon" role="img"></svg></span>'
            f'<div dir="auto">{spec["link"]}</div></div></button></div>') if spec.get("link") else ""
    bio_block = (f'<div><div><span dir="auto"><div role="button"><span dir="auto" style="white-space:pre-line">{bio}</span></div></span>'
                 f'{link}</div></div>') if (bio or link) else ""
    who = "following" if user in STATE["accepted"] else "requested" if user in STATE["requested"] else "follow"
    label = {"follow": "Follow", "requested": "Requested", "following": "Following"}[who]
    follow = (f'<section><div><button type="button" id="fbtn"><div><div dir="auto">{label}</div></div></button></div></section>'
              f"<script>fbtn.onclick = async () => {{ const r = await fetch('/api/v1/friendships/create/{uid_of(user)}/', {{method: 'POST'}});"
              f" const j = await r.json(); fbtn.querySelector('[dir=auto]').textContent = j.friendship_status.following ? 'Following' : 'Requested'; }};</script>") if spec.get("private") else ""
    main = (follow + "<h2>This account is private</h2><p>Follow to see their photos and videos.</p>" if spec.get("private")
            else '<div id="grid" style="min-height:1800px"><a href="/p/AAA/">post one</a></div>' + (f"<script>{GRID_JS.replace('__USER__', user)}</script>" if (spec.get("post_n") or 0) > PAGE_OF_POSTS else ""))
    head_name = f"{name} (@{user})" if name else f"@{user}"
    # The counts are links that open the lists, except on a private account we do not follow (plain text there).
    opener = (lambda which: f'<a href="#" role="link" onclick="openList(\'{which}\');return false">') if not spec.get("private") else (lambda which: "<span>")  # noqa: E731
    closer = "</a>" if not spec.get("private") else "</span>"
    return f"""<!doctype html><meta charset=utf-8><title>Instagram</title>
<meta property="og:title" content="{esc(head_name)} • Instagram photos and videos">
<meta property="og:description" content="{counts} - See Instagram photos and videos from {esc(head_name)}">
<meta name="description" content="{counts} - {esc(head_name)} on Instagram: &quot;{esc(bio)}&quot;">
{NAV}<header><section><img alt="{user}'s profile picture" src="{base}/cdn/avatar.png"></section>
<section><div><div><a href="#" role="link"><h2 dir="auto"><span>{user}</span></h2></a>{verified}</div>{name_div}
<div><div><span dir="auto"><span><span>{spec['posts']}</span></span> posts</span></div>
<div>{opener("followers")}<span dir="auto"><span{title}><span>{spec['followers']}</span></span> followers</span>{closer}</div>
<div>{opener("following")}<span dir="auto"><span><span>{spec['following']}</span></span> following</span>{closer}</div></div></div>
{bio_block}</section></header><main>{main}</main><script>{graphql_script(user, bool(spec.get("post_n")))}</script>
<script>{LIST_JS.replace("__UID__", str(uid_of(user)))}</script>"""


def graphql_body(user, spec):
    shape = spec["api"]
    if shape == "flat":
        node = {"username": user, "pk": "1815", "full_name": spec["name"], "biography": spec["bio"], "follower_count": 1234567,
                "following_count": 12, "media_count": 340, "is_private": False, "is_verified": True, "category": "Science",
                "bio_links": [{"title": "Notes", "url": "https://l.instagram.com/?u=https%3A%2F%2Fnotes.example.org%2F&e=1"}],
                "friendship_status": {"following": False, "followed_by": False, "outgoing_request": False},
                "account_type": 2, "address_street": "Valiasr 1", "city_name": "Tehran", "zip": "1234", "public_email": "hi@ada.example",
                "latest_reel_media": int(time.time()) - 3 * 3600, "total_clips_count": 4, "has_chaining": True, "show_text_post_app_badge": True,
                "fbid_v2": "17841400000000001", "mutual_followers_count": 3,
                "biography_with_entities": {"entities": [{"user": {"username": "babbage"}}, {"hashtag": {"name": "maths"}}]}}
    else:
        node = {"username": user, "id": mock_id(user), "full_name": spec["name"], "biography": spec["bio"], "is_private": True,
                "friendship_status": {"following": user in STATE["accepted"], "outgoing_request": user in STATE["requested"] and user not in STATE["accepted"]},
                "edge_followed_by": {"count": 900}, "edge_follow": {"count": 15}, "edge_owner_to_timeline_media": {"count": 0}}
    return ("for (;;);" if spec.get("prefix") else "") + json.dumps({"data": {"user": node}})


NOT_FOUND = (f"<!doctype html><meta charset=utf-8><title>Page Not Found • Instagram</title>{NAV}"
             "<main><span>Sorry, this page isn't available.</span><p>The link you followed may be broken, "
             "or the page may have been removed.</p></main>")
LIMITED = (f"<!doctype html><meta charset=utf-8><title>Instagram</title>{NAV}<main>"
           '<div role="alert">Please wait a few minutes before you try again.</div></main>'
           "<script>" + graphql_script("limited") + "</script>")

WEIRD ="<!doctype html><meta charset=utf-8><title>Instagram</title><h1>Welcome back</h1><p>Something unfamiliar</p>"

HOME = """<!doctype html><meta charset=utf-8><title>Home</title>
<nav><a href="/direct/inbox/">Inbox</a><svg aria-label="Home" width=24 height=24></svg>
<img alt="{user}'s profile picture" src="%s" width=24 height=24></nav>
<div id=d><p>Save your login info?</p>
<button onclick="document.cookie='onetap=1;path=/;max-age=2592000';d.remove()">Save info</button></div>""" % PIXEL

# What Instagram shows to a browser that remembers an account but has no live session.
CHOOSER = """<!doctype html><meta charset=utf-8><title>Instagram</title>
<h1>See everyday moments from your close friends.</h1><div>{user}</div>
<div role=button id=go>Continue</div><div role=button id=other>Use another profile</div><div role=button>Create new account</div>
<script>
other.onclick = () => { location = '/accounts/login/?form=1'; };
go.onclick = async () => {
  const j = await (await fetch('/chooser/continue', {method: 'POST'})).json();
  location = j.ok ? '/' : '/accounts/login/?form=1';
};
</script>"""


def signed_in(user):
    r = JSONResponse({"authenticated": True, "user": True, "status": "ok", "ok": True})
    STATE["expired"] = STATE["no_onetap"] = False
    for name, value in (("sessionid", "mock-session"), ("ds_user_id", "424242"), ("uname", user), ("remembered", user)):
        r.set_cookie(name, value, path="/", max_age=2592000)  # persistent, like the real sessionid
    return r


@app.get("/")
@app.get("/accounts/login/")
async def page(request: Request):
    user = request.cookies.get("uname")
    if request.cookies.get("sessionid") and user and not STATE["expired"]:
        return HTMLResponse(HOME.replace("{user}", user))
    remembered = request.cookies.get("remembered")
    if remembered and not request.query_params.get("form"):
        return HTMLResponse(CHOOSER.replace("{user}", remembered))
    return HTMLResponse(LOGIN)


@app.post("/chooser/continue")
async def chooser_continue(request: Request):
    """One-tap login: works only if 'Save info' was pressed in this browser."""
    if request.cookies.get("onetap") and not STATE["no_onetap"] and request.cookies.get("remembered"):
        return signed_in(request.cookies["remembered"])
    return JSONResponse({"ok": False})


@app.post("/test/expire")
async def expire(forget: int = 0):
    STATE["expired"], STATE["no_onetap"] = True, bool(forget)
    return {"ok": True}


@app.post("/api/v1/web/accounts/login/ajax/")
async def login(request: Request):
    user = (await request.json()).get("email", "")
    if user in ("good", "good2"):         # good2: his second account (the account switcher's tests)
        return signed_in(user)
    if user == "wrongpass":
        return JSONResponse({"authenticated": False, "user": True, "status": "ok",
                             "message": "Sorry, your password was incorrect. Please double-check your password."})
    if user == "nouser":
        return JSONResponse({"authenticated": False, "user": False, "status": "ok",
                             "message": "The username you entered doesn't belong to an account. Please check your username and try again."})
    if user == "newwrong":
        return JSONResponse({"authenticated": False, "status": "fail",
                             "message": "The login information you entered is incorrect. Find your account and log in."}, 400)
    if user == "limit":
        return JSONResponse({"status": "fail", "message": "Please wait a few minutes before you try again."}, 429)
    if user == "twofa":
        return JSONResponse({"two_factor_required": True, "status": "ok"})
    if user == "emailcode":
        return JSONResponse({"checkpoint_url": "/auth_platform/codeentry/?apc=abc", "status": "fail"}, 400)
    if user == "codelabel":   # the 2026 page: the code box is named only by a separate <label>
        return JSONResponse({"checkpoint_url": "/auth_platform/codeentry/?apc=abc&v=label", "status": "fail"}, 400)
    if user == "weird":
        return JSONResponse({"checkpoint_url": "/welcome/back/", "status": "fail"}, 400)
    return JSONResponse({"checkpoint_url": "/challenge/abc/", "status": "fail", "message": "checkpoint_required"}, 400)


@app.get("/accounts/login/two_factor/")
async def two_factor():
    return HTMLResponse(TWO_FACTOR)


@app.post("/api/v1/web/accounts/login/ajax/two_factor/")
async def two_factor_post(request: Request):
    if (await request.json()).get("code") == "123456":
        return signed_in("twofa")
    return JSONResponse({"authenticated": False, "status": "fail",
                         "message": "Please check the security code and try again."})


@app.get("/auth_platform/codeentry/")
async def code_entry(v: str = ""):
    if v != "label":
        return HTMLResponse(CODE_ENTRY)
    page = CODE_ENTRY.replace('<input type="text" aria-label="Code" id=c autocomplete="off">',
                              '<label for=c>Code</label><input type="text" id=c autocomplete="off">')
    return HTMLResponse(page)


@app.get("/auth_platform/state")
async def code_state():
    return {"manual": STATE["manual"]}


@app.post("/auth_platform/verify")
async def code_verify(request: Request):
    if (await request.json()).get("code") == "654321":
        STATE["manual"] = False
        return signed_in("emailcode")
    return JSONResponse({"ok": False})


@app.post("/test/manual-code")
async def manual_code():
    STATE["manual"] = True
    return {"ok": True}


@app.get("/welcome/back/")
async def weird():
    return HTMLResponse(WEIRD)


@app.get("/challenge/abc/")
async def challenge():
    return HTMLResponse(CHALLENGE)


@app.get("/challenge/state")
async def challenge_state():
    return {"approved": STATE["approved"]}


@app.post("/challenge/approve")
async def challenge_approve():
    STATE["approved"] = True
    return {"ok": True}


@app.post("/challenge/finish")
async def challenge_finish():
    return signed_in("challenge")


@app.get("/cdn/avatar.png")
async def avatar(gone: int = 0):
    if gone:
        return Response(status_code=403)   # an address Instagram's picture host no longer serves
    return Response(PNG, media_type="image/png")


@app.get("/cdn/v.mp4")
async def video(big: int = 0):
    return Response(MP4 * 8 if big else MP4, media_type="video/mp4")


@app.post("/api/graphql")
async def graphql(request: Request):
    body = (await request.body()).decode("utf-8", "replace")
    variables = json.loads(unquote(body.split("variables=", 1)[1]))
    friendly = (re.search(r"fb_api_req_friendly_name=(\w+)", body) or [None, ""])[1]
    if friendly == "PolarisStoriesV3SeenMutation":   # the one request that tells the owner of a story that somebody looked
        STATE["seen"] = STATE.get("seen", 0) + 1
        return Response("{}", media_type="text/javascript")
    if friendly == "PolarisPostCommentsPaginationQuery":   # asked by a post page, not by a profile page
        code = variables["code"]
        total = post_index()[code][2]["comment_count"]
        return Response(json.dumps({"data": {"xdt_api__v1__media__media_id__comments__connection": comments_page(code, total, int(variables["after"]))}}),
                        media_type="text/javascript")
    user = variables.get("username") or next((u for u in PROFILES if mock_id(u) == str(variables.get("id", ""))), "")
    STATE["hits"]["query:" + user.lower()] = STATE["hits"].get("query:" + user.lower(), 0) + (friendly == "PolarisProfilePageContentQuery")
    spec = PROFILES.get(user.lower())
    if not spec:
        return Response("{}", media_type="text/javascript")
    if friendly == "PolarisProfilePostsTabContentQuery_connection" and spec.get("post_n"):   # the grid asked for the next twelve
        return Response(posts_body(user.lower(), spec, str(request.base_url).rstrip("/"), int(variables["after"])), media_type="text/javascript")
    if spec["api"] == "none":   # a page with no API data of its own; only its posts are answered
        if friendly == "PolarisProfilePostsQuery" and spec.get("post_n"):
            return Response(posts_body(user.lower(), spec, str(request.base_url).rstrip("/")), media_type="text/javascript")
        return Response("{}", media_type="text/javascript")
    if spec["api"] == "429":
        return Response("", status_code=429)
    if friendly == "PolarisProfileStoryHighlightsTrayContentQuery":
        return Response(highlights_body(user.lower(), str(request.base_url).rstrip("/")), media_type="text/javascript")
    if friendly == "PolarisProfileSuggestedUsersWithPreloadableQuery":
        return Response(similar_body(str(request.base_url).rstrip("/")), media_type="text/javascript")
    if friendly == "PolarisProfilePostsQuery":
        return Response(posts_body(user.lower(), spec, str(request.base_url).rstrip("/")), media_type="text/javascript")
    return Response(graphql_body(user.lower(), spec), media_type="text/javascript")


@app.get("/api/v1/media/{pk}/likers/")
async def likers(pk: int):
    """The first sixty people who liked it, Instagram's own total, and no next page (that is how the real one behaves)."""
    node = next((n for _, _, n in post_index().values() if n["pk"] == str(pk)), None)
    if node is None:
        return JSONResponse({"status": "fail"}, status_code=404)
    users = [{"pk": str(6000000 + k), "id": str(6000000 + k), "username": f"liker_{k}", "full_name": f"Liker {k}", "is_private": k % 6 == 0,
              "is_verified": k % 9 == 0, "profile_pic_url": "http://127.0.0.1/none.jpg", "latest_reel_media": 0} for k in range(min(60, node["like_count"]))]
    return {"users": users, "user_count": node["like_count"], "follow_ranking_token": "t", "status": "ok"}


@app.get("/api/v1/friendships/{uid}/{which}/")
async def friendships(uid: int, which: str, request: Request, count: int = 12, max_id: int = 0):
    """One page of a person's followers or following. Private accounts are not served (they would be an error for a stranger)."""
    owner = next((u for u in PROFILES if uid_of(u) == uid and not PROFILES[u].get("limited")), None)
    deny = PROFILES[owner].get("deny") if owner else None
    if deny == "wait":
        return JSONResponse({"message": "feedback_required", "spam": True, "status": "fail"}, status_code=400)
    if deny == "login":
        return JSONResponse({"message": "login_required", "status": "fail"}, status_code=403)
    if which not in ("followers", "following") or owner is None or PROFILES[owner].get("private") or deny or not is_signed_in(request):
        return JSONResponse({"message": "Not authorized to view user.", "status": "fail"}, status_code=403)
    boom = STATE.get("fail_once")
    if boom and boom["owner"] == owner and max_id >= boom["after"]:   # a server error deep in the list, for a few requests in a row
        boom["times"] = boom.get("times", 1) - 1
        if boom["times"] <= 0:
            STATE["fail_once"] = None
        return JSONResponse({"message": "Sorry, something went wrong", "status": "fail"}, status_code=500)
    bye = STATE.get("logout_once")
    if bye and bye["owner"] == owner and max_id >= bye["after"]:   # Instagram logs the account out deep in the list, with a «wait»
        STATE["logout_once"] = None
        r = JSONResponse({"message": "feedback_required", "spam": True, "status": "fail"}, status_code=400)
        for name in ("sessionid", "ds_user_id"):
            r.delete_cookie(name, path="/")
        return r
    drop = STATE.get("drop_once")
    if drop and drop["owner"] == owner and max_id >= drop["after"]:   # the connection breaks on the way (a VPN drop): no whole answer
        drop["times"] = drop.get("times", 1) - 1
        if drop["times"] <= 0:
            STATE["drop_once"] = None
        return Response(b'{"users": [', media_type="application/json", headers={"content-length": "4096"})
    once = STATE.get("wait_once")
    if once and once["owner"] == owner and max_id >= once["after"]:   # «wait» once, deep in the list (then the list goes on)
        STATE["wait_once"] = None
        return JSONResponse({"message": "feedback_required", "spam": True, "status": "fail"}, status_code=400)
    STATE["hits"][f"{which}:{owner}"] = STATE["hits"].get(f"{which}:{owner}", 0) + 1
    return follow_reply(owner, which, max_id, min(max(count, 1), 12))


@app.get("/test/id/{user}")
async def test_id(user: str):
    return {"id": mock_id(user.lower())}


@app.post("/test/fail-once")
async def fail_once(request: Request):
    STATE["fail_once"] = await request.json()
    return {"ok": True}


@app.post("/test/logout-once")
async def logout_once(request: Request):
    STATE["logout_once"] = await request.json()
    return {"ok": True}


@app.post("/test/drop-once")
async def drop_once(request: Request):
    STATE["drop_once"] = await request.json()
    return {"ok": True}


@app.post("/test/wait-once")
async def wait_once(request: Request):
    STATE["wait_once"] = await request.json()
    return {"ok": True}


@app.post("/api/v1/friendships/create/{uid}/")
async def friendship_create(uid: int):
    owner = next((u for u in PROFILES if uid_of(u) == uid), None)
    if owner is None:
        return JSONResponse({"status": "fail"}, status_code=404)
    STATE["requested"].add(owner)
    return {"friendship_status": {"following": owner in STATE["accepted"], "outgoing_request": owner not in STATE["accepted"]}, "status": "ok"}


@app.post("/test/accept/{user}")
async def test_accept(user: str):
    STATE["accepted"].add(user.lower())
    return {"ok": True}


@app.post("/api/v1/friendships/show_many/")
async def show_many():
    return {"friendship_statuses": {}, "status": "ok"}


@app.get("/test/hits")
async def hits():
    return STATE["hits"]


@app.get("/test/seen")
async def seen():
    return {"seen": STATE.get("seen", 0)}


def is_signed_in(request: Request):
    return bool(request.cookies.get("sessionid") and request.cookies.get("uname") and not STATE["expired"])


@app.get("/stories/highlights/{hid}/")
async def highlight_view(hid: str, request: Request):
    if hid not in HIGHLIGHT_ITEMS:
        return HTMLResponse(NOT_FOUND, status_code=404)
    if not is_signed_in(request):
        return await page(request)
    STATE["hits"]["hl" + hid] = STATE["hits"].get("hl" + hid, 0) + 1
    node = reel_node("ada.lovelace", f"highlight:{hid}", str(request.base_url).rstrip("/"), HIGHLIGHT_ITEMS[hid], True)
    return HTMLResponse(reel_page(node, True))


@app.get("/stories/{username}/")
async def story_view(username: str, request: Request):
    """Registered before the two-part post path. A person without a story is sent back to the profile, like Instagram does."""
    key = username.lower()
    if key not in PROFILES:
        return HTMLResponse(NOT_FOUND, status_code=404)
    if not is_signed_in(request):
        return await page(request)
    STATE["hits"]["story:" + key] = STATE["hits"].get("story:" + key, 0) + 1
    if key not in STORY_ITEMS:
        return RedirectResponse(f"/{key}/")
    node = reel_node(key, "77", str(request.base_url).rstrip("/"), STORY_ITEMS[key], False)
    return HTMLResponse(reel_page(node, False))


@app.get("/{kind}/{code}/")
async def post_view(kind: str, code: str, request: Request):
    """/p/<code>/ and /reel/<code>/ (any other two-part path is not a page here)."""
    if kind not in ("p", "reel") or code not in post_index():
        return HTMLResponse(NOT_FOUND, status_code=404)
    if not (request.cookies.get("sessionid") and request.cookies.get("uname") and not STATE["expired"]):
        return await page(request)
    STATE["hits"][code] = STATE["hits"].get(code, 0) + 1
    user, i, node = post_index()[code]
    return HTMLResponse(post_page(code, user, i, node, str(request.base_url).rstrip("/")))


@app.get("/{username}/")
async def profile(username: str, request: Request):
    """Registered last so every fixed path above wins. Logged-out visitors get the same pages as the home page."""
    user = request.cookies.get("uname")
    if not (request.cookies.get("sessionid") and user and not STATE["expired"]):
        return await page(request)
    key = username.lower()
    STATE["hits"][key] = STATE["hits"].get(key, 0) + 1
    spec = PROFILES.get(key)
    if spec is None:
        return HTMLResponse(NOT_FOUND, status_code=404)
    if spec.get("limited"):
        return HTMLResponse(LIMITED)
    return HTMLResponse(profile_page(key, spec, str(request.base_url).rstrip("/")))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8791, log_level="warning")
