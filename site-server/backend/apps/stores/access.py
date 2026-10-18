"""Who may do what inside a store.

Until this module existed, every view asked the same question the same way:

    get_object_or_404(Store, pk=pk, owner=request.user)

That is a correct answer to "is this my store?" and the only possible answer to
"may my colleague answer customer messages?" was no — one store, one person, one
login shared around the office. The roadmap (§9.10) asks for real roles;
this is where they are decided.

Two deliberate choices:

* **`Store.owner` stays.** It is who pays and who can delete the store, and
  that is not a role — it is the tenant's anchor. Memberships grant access;
  ownership is not one of them.
* **Permissions are checked here, never inline in a view.** Thirty-two call
  sites asked the ownership question directly, and a single missed one is a
  tenant-isolation hole rather than a missing feature. `tests_access.py` fails
  the build if a view goes back to asking on its own.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404

# ---- what there is to do --------------------------------------------------

BILLING = "billing"           # plans, payments, subscription
MEMBERS = "members"           # invite and remove people
SETTINGS = "settings"         # brand profile, data policy, integrations
PRODUCTS = "products"         # the catalogue
CONTENT = "content"           # captions, images, video
CAMPAIGNS = "campaigns"       # campaigns and publishing
ANALYTICS = "analytics"       # reports
CONVERSATIONS = "conversations"  # customer chat, orders, tickets

ALL = (BILLING, MEMBERS, SETTINGS, PRODUCTS, CONTENT, CAMPAIGNS, ANALYTICS, CONVERSATIONS)


class Role:
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MARKETING = "MARKETING"
    CONTENT_MANAGER = "CONTENT"
    SUPPORT = "SUPPORT"
    VIEWER = "VIEWER"

    CHOICES = [
        (OWNER, "مالک — همه‌چیز، شامل پرداخت و حذف فروشگاه"),
        (ADMIN, "مدیر — همه‌چیز جز پرداخت"),
        (MARKETING, "بازاریابی — کمپین، تحلیل، محتوا"),
        (CONTENT_MANAGER, "مدیر محتوا — محصولات و محتوا"),
        (SUPPORT, "پشتیبانی — گفتگو و سفارش مشتری"),
        (VIEWER, "بازدیدکننده — فقط مشاهده"),
    ]


#: What each role may CHANGE. Reading is a separate, wider question below.
WRITE = {
    Role.OWNER: set(ALL),
    # An admin runs the shop but does not spend the owner's money.
    Role.ADMIN: set(ALL) - {BILLING},
    Role.MARKETING: {CAMPAIGNS, CONTENT},
    Role.CONTENT_MANAGER: {PRODUCTS, CONTENT},
    Role.SUPPORT: {CONVERSATIONS},
    Role.VIEWER: set(),
}

#: What each role may SEE. Wider than write on purpose — a marketer who cannot
#: read the catalogue cannot write a campaign about it. Billing and members are
#: the exceptions: prices paid and who else has access are the owner's business.
READ = {
    Role.OWNER: set(ALL),
    Role.ADMIN: set(ALL),
    Role.MARKETING: {PRODUCTS, CONTENT, CAMPAIGNS, ANALYTICS},
    Role.CONTENT_MANAGER: {PRODUCTS, CONTENT, CAMPAIGNS, ANALYTICS},
    Role.SUPPORT: {CONVERSATIONS, PRODUCTS},
    Role.VIEWER: set(ALL) - {BILLING, MEMBERS},
}


class NoAccess(PermissionDenied):
    """The user is in this store but not allowed to do this particular thing.

    Distinct from Http404 on purpose: hiding a store the user genuinely belongs
    to would have them filing a bug instead of asking for a role change.
    """


def role_of(user, store) -> str | None:
    """This user's role in this store, or None if they are not a member."""
    if not getattr(user, "is_authenticated", False):
        return None
    if store.owner_id == user.pk:
        return Role.OWNER
    from .models import Membership

    row = Membership.objects.filter(store=store, user=user, is_active=True).first()
    return row.role if row else None


def can(user, store, permission: str, *, write: bool = True) -> bool:
    """May this user do this here?"""
    role = role_of(user, store)
    if role is None:
        return False
    table = WRITE if write else READ
    return permission in table.get(role, set())


def stores_for(user):
    """Every store this user can reach — owned or joined.

    Used by the list endpoint so a colleague sees the shop they were added to
    rather than an empty dashboard.
    """
    from .models import Store

    if not getattr(user, "is_authenticated", False):
        return Store.objects.none()
    return Store.objects.filter(
        Q(owner=user) | Q(memberships__user=user, memberships__is_active=True)
    ).distinct()


def get_store(user, pk, permission: str | None = None, *, write: bool = True):
    """The store, if this user may reach it — otherwise the right refusal.

    This replaces `get_object_or_404(Store, pk=pk, owner=request.user)` at every
    call site. The two failure modes stay distinct:

    * not a member at all → 404, because the store's existence is not theirs to
      learn;
    * a member without this permission → 403 with a message naming the role, so
      the fix is "ask the owner for a different role", not "file a bug".
    """
    from .models import Store

    store = Store.objects.filter(pk=pk).first()
    if store is None:
        raise Http404("فروشگاه پیدا نشد.")

    role = role_of(user, store)
    if role is None:
        raise Http404("فروشگاه پیدا نشد.")

    if permission is not None and not can(user, store, permission, write=write):
        label = dict(Role.CHOICES).get(role, role)
        raise NoAccess(
            f"نقش شما در این فروشگاه «{label.split('—')[0].strip()}» است و "
            f"اجازه‌ی این کار را ندارد. از مالک فروشگاه بخواهید نقش‌تان را تغییر دهد."
        )
    return store
