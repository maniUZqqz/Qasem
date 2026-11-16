"""Contacts: one person, however many channels they used.

`customers.Customer` is "this sender on this platform" - `(store, channel,
external_id)` - so the same woman writing on Telegram and then sending an SMS is
two customers and, in the old inbox, two strangers. A `Contact` ties them
together, and this module is the only place that decides when two customers are
one person:

* the **same normalised phone** (always),
* the **same username** across platforms (when the store keeps `merge_by_username`
  on - a handle is a weaker signal than a phone number, so it can be turned off
  and a wrong merge can always be undone with `unlink`).

Never merges across stores: a contact belongs to exactly one store.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.customers.models import Customer, Message, Order

from . import norm
from .models import Contact, ContactLink

#: Statuses that count as a purchase. A draft or an order still waiting for a
#: receipt is not revenue, and a segment called «مشتریِ دائمی» must not be
#: made of people who only ever started a cart.
PAID = (Order.Status.CONFIRMED, Order.Status.CASH_ON_DELIVERY)


def _add_username(contact: Contact, username: str) -> bool:
    handle = norm.normalize_username(username)
    if handle and handle not in (contact.usernames or []):
        contact.usernames = [*(contact.usernames or []), handle][:10]
        return True
    return False


def find_match(store, *, phone: str = "", username: str = "", merge_by_username: bool = True):
    """The existing contact this phone/username belongs to, and why."""
    if phone:
        found = Contact.objects.filter(store=store, phone=phone).order_by("id").first()
        if found:
            return found, "phone"
    handle = norm.normalize_username(username)
    if handle and merge_by_username:
        # `usernames` is a JSON list; SQLite cannot `contains` it, so look at
        # the few contacts that have any rather than inventing a query.
        for candidate in Contact.objects.filter(store=store).exclude(usernames=[]).only("id", "usernames"):
            if handle in (candidate.usernames or []):
                return Contact.objects.get(pk=candidate.pk), "username"
    return None, ""


@transaction.atomic
def identify(
    customer: Customer, *, phone: str = "", username: str = "", name: str = "",
    source: str = "", is_test: bool = False,
) -> Contact:
    """The contact for this customer - created, or found and linked."""
    from .team import settings_for

    store = customer.store
    phone = norm.normalize_phone(phone or customer.phone)
    username = norm.normalize_username(username)
    name = (name or customer.name or "").strip()
    now = timezone.now()
    if username and (customer.metadata or {}).get("username") != username:
        # Remember whose handle this is, so «unlink» can take it back off the contact.
        customer.metadata = {**(customer.metadata or {}), "username": username}
        customer.save(update_fields=["metadata"])

    link = ContactLink.objects.select_related("contact").filter(customer=customer).first()
    if link is not None:
        contact = link.contact
        changed = False
        if phone and not contact.phone:
            other = Contact.objects.filter(store=store, phone=phone).exclude(pk=contact.pk).first()
            if other is not None:
                contact = merge(other, contact)  # the phone proves they are one person
            else:
                contact.phone = phone
            changed = True
        if name and not contact.name:
            contact.name = name[:200]
            changed = True
        if username and _add_username(contact, username):
            changed = True
        contact.last_activity_at = now
        contact.save()
        if phone and not customer.phone:
            customer.phone = phone
            customer.save(update_fields=["phone"])
        return contact

    cfg = settings_for(store)
    contact, how = find_match(store, phone=phone, username=username, merge_by_username=cfg.merge_by_username)
    if contact is None:
        contact = Contact.objects.create(
            store=store, name=name[:200], phone=phone, source=source or customer.channel,
            first_seen_at=now, last_activity_at=now, is_test=is_test,
        )
        how = "new"
        if username:
            _add_username(contact, username)
            contact.save(update_fields=["usernames", "updated_at"])
    else:
        if name and not contact.name:
            contact.name = name[:200]
        if phone and not contact.phone:
            contact.phone = phone
        _add_username(contact, username)
        contact.last_activity_at = now
        contact.save()
    ContactLink.objects.create(contact=contact, customer=customer, matched_by=how)
    if phone and not customer.phone:
        customer.phone = phone
        customer.save(update_fields=["phone"])
    return contact


@transaction.atomic
def merge(keep: Contact, drop: Contact) -> Contact:
    """Fold `drop` into `keep`. Same-store only; returns `keep`."""
    if keep.pk == drop.pk:
        return keep
    if keep.store_id != drop.store_id:
        raise ValueError("مخاطب‌های دو فروشگاه جدا را نمی‌شود یکی کرد.")
    ContactLink.objects.filter(contact=drop).update(contact=keep, matched_by="manual")
    keep.name = keep.name or drop.name
    keep.phone = keep.phone or drop.phone
    keep.email = keep.email or drop.email
    for handle in drop.usernames or []:
        _add_username(keep, handle)
    keep.tags = sorted(set(keep.tags or []) | set(drop.tags or []))
    if drop.notes:
        keep.notes = (keep.notes + "\n\n" if keep.notes else "") + drop.notes
    # The most restrictive wish wins: a person who said stop on one channel
    # said it to the shop.
    flags = dict(keep.opt_out or {})
    for key, value in (drop.opt_out or {}).items():
        flags[key] = bool(flags.get(key) or value)
    keep.opt_out = flags
    keep.first_seen_at = min(keep.first_seen_at, drop.first_seen_at)
    stamps = [t for t in (keep.last_activity_at, drop.last_activity_at) if t]
    keep.last_activity_at = max(stamps) if stamps else None
    keep.is_test = keep.is_test and drop.is_test
    keep.save()
    drop.delete()
    refresh_stats(keep)
    return keep


@transaction.atomic
def unlink(customer: Customer) -> Contact:
    """Undo a wrong merge: this customer becomes a contact of its own again."""
    link = ContactLink.objects.select_related("contact").filter(customer=customer).first()
    old = link.contact if link else None
    fresh = Contact.objects.create(
        store=customer.store, name=customer.name[:200], source=customer.channel,
        phone="", last_activity_at=timezone.now(),
    )
    if link is None:
        ContactLink.objects.create(contact=fresh, customer=customer, matched_by="manual")
    else:
        link.contact = fresh
        link.matched_by = "manual"
        link.save(update_fields=["contact", "matched_by"])
    if old is not None:
        _take_identity_along(old, fresh, customer)
        refresh_stats(old)
        if not old.links.exists():
            old.delete()
    refresh_stats(fresh)
    return fresh


def _take_identity_along(old: Contact, fresh: Contact, customer: Customer) -> None:
    """What only this identity brought (its phone, its handle) leaves the old contact with it.

    A wrong merge copies the newcomer's phone and username onto the contact it
    joined. Undoing the merge must undo that too - otherwise the original contact
    keeps a number that belongs to someone else, and the next message from
    that number is merged back into it.
    """
    rest = list(customers_of(old))
    phone = norm.normalize_phone(customer.phone)
    if phone and old.phone == phone and not any(norm.normalize_phone(c.phone) == phone for c in rest):
        old.phone = ""
        fresh.phone = phone
    handle = norm.normalize_username((customer.metadata or {}).get("username", ""))
    if handle and handle in (old.usernames or []) and not any(
        norm.normalize_username((c.metadata or {}).get("username", "")) == handle for c in rest
    ):
        old.usernames = [h for h in old.usernames if h != handle]
        _add_username(fresh, handle)
    old.save()
    fresh.save()


def customers_of(contact: Contact):
    return Customer.objects.filter(inbox_link__contact=contact)


def refresh_stats(contact: Contact) -> Contact:
    """Recount orders, spend and last purchase from real paid orders."""
    orders = Order.objects.filter(customer__inbox_link__contact=contact, status__in=PAID)
    total = orders.aggregate(total=Sum("total"))["total"] or Decimal(0)
    last = orders.exclude(confirmed_at__isnull=True).order_by("-confirmed_at").values_list(
        "confirmed_at", flat=True,
    ).first()
    contact.orders_count = orders.count()
    contact.total_spent = total
    contact.last_purchase_at = last
    contact.save(update_fields=["orders_count", "total_spent", "last_purchase_at", "updated_at"])
    return contact


def history(contact: Contact, limit: int = 200) -> list[dict]:
    """Every message this person wrote or received, across channels, oldest first."""
    rows = (
        Message.objects.filter(conversation__customer__inbox_link__contact=contact)
        .select_related("conversation").order_by("-created_at")[:limit]
    )
    return [
        {
            "id": m.id, "role": m.role, "text": m.text, "at": m.created_at,
            "channel": m.conversation.channel, "conversation_id": m.conversation_id,
        }
        for m in reversed(list(rows))
    ]


def set_opt_out(contact: Contact, channel: str = "ALL", value: bool = True) -> Contact:
    flags = dict(contact.opt_out or {})
    flags[(channel or "ALL").upper()] = bool(value)
    contact.opt_out = {k: v for k, v in flags.items() if v}
    contact.save(update_fields=["opt_out", "updated_at"])
    return contact


#: A customer who writes one of these (alone) is asking not to receive
#: marketing. Matched against the whole normalised message, not a substring:
#: «لغو سفارش» is an order question, not an unsubscribe.
OPT_OUT_WORDS = {"لغو", "لغو عضویت", "لغو11", "stop", "unsubscribe", "cancel sub", "خروج", "حذف من"}
OPT_IN_WORDS = {"عضویت", "شروع", "start", "subscribe"}


def opt_word(text: str) -> str:
    """`"out"`, `"in"` or `""` for a whole-message opt keyword."""
    cleaned = norm.ascii_digits((text or "").strip().lower()).strip(" .!؟?")
    if cleaned in OPT_OUT_WORDS:
        return "out"
    if cleaned in OPT_IN_WORDS:
        return "in"
    return ""
