"""CRM: contacts, segments, broadcasts, follow-ups."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.customers.models import Conversation, Customer, Order
from apps.stores import access

from . import broadcast as bc
from . import contacts as contacts_mod
from . import followups, norm, segments, serializers as ser, sla
from .models import Broadcast, BroadcastRecipient, Contact, FollowUp, Segment
from .views_conversations import conversation_of, fail, store_of


def _marketing_store(request, store_id, *, write=False):
    """Broadcasts are made by support *or* marketing people; approved only by admins."""
    store = access.get_store(request.user, store_id)
    for permission in (access.CONVERSATIONS, access.CAMPAIGNS):
        if access.can(request.user, store, permission, write=write):
            return store
    raise access.NoAccess("نقش شما اجازهٔ ساخت ارسال گروهی را ندارد. از مالک فروشگاه بخواهید نقش‌تان را تغییر دهد.")


# --------------------------------------------------------------- contacts


class ContactListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = store_of(request, store_id)
        qp = request.query_params
        rows = Contact.objects.filter(store=store)
        if qp.get("test") != "1":
            rows = rows.filter(is_test=False)
        term = (qp.get("q") or "").strip()
        if term:
            rows = rows.filter(Q(name__icontains=term) | Q(phone__icontains=norm.ascii_digits(term)) | Q(email__icontains=term))
        if qp.get("segment"):
            seg = get_object_or_404(Segment, pk=qp["segment"], store=store)
            ids = {c.pk for c in segments.contacts_in(store, seg.rules, include_test=qp.get("test") == "1")}
            rows = rows.filter(pk__in=ids)
        if qp.get("tag"):
            tag = qp["tag"].lower()
            keep = [c.pk for c in rows if tag in [str(t).lower() for t in (c.tags or [])]]
            rows = rows.filter(pk__in=keep)
        total = rows.count()
        limit = min(int(qp.get("limit", 50) or 50), 200)
        offset = max(int(qp.get("offset", 0) or 0), 0)
        page = list(rows.order_by("-last_activity_at", "-id")[offset: offset + limit])
        facts = segments.facts_for(page)
        data = []
        for c in page:
            item = ser.contact_json(c)
            item["channels"] = sorted(facts[c.pk]["channel"])
            data.append(item)
        return Response({
            "contacts": data, "total": total,
            #: how many test/demo contacts exist - the page offers «show test» only when there are some
            "test_total": Contact.objects.filter(store=store, is_test=True).count(),
        })

    def post(self, request, store_id):
        """Create or update by phone - what a shop does with a list it already owns."""
        store = store_of(request, store_id, write=True)
        phone = norm.normalize_phone(str(request.data.get("phone", "")))
        name = str(request.data.get("name", "")).strip()[:200]
        if not phone and not name:
            return fail("empty", "نام یا شمارهٔ موبایل لازم است.")
        contact = Contact.objects.filter(store=store, phone=phone).first() if phone else None
        created = contact is None
        if contact is None:
            contact = Contact.objects.create(store=store, name=name, phone=phone, source="manual")
        elif name and not contact.name:
            contact.name = name
        tags = request.data.get("tags")
        if isinstance(tags, list):
            contact.tags = sorted({str(t).strip()[:40] for t in tags if str(t).strip()})[:30]
        contact.save()
        return Response(ser.contact_json(contact, detail=True), status=status.HTTP_201_CREATED if created else 200)


class ContactDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = store_of(request, store_id)
        contact = get_object_or_404(Contact, pk=pk, store=store)
        return Response(_contact_panel(contact))

    def patch(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        contact = get_object_or_404(Contact, pk=pk, store=store)
        data = request.data
        if "name" in data:
            contact.name = str(data["name"]).strip()[:200]
        if "phone" in data:
            phone = norm.normalize_phone(str(data["phone"]))
            other = Contact.objects.filter(store=store, phone=phone).exclude(pk=contact.pk).first() if phone else None
            if other is not None:
                return fail("phone_taken", f"این شماره برای «{other.name or other.phone}» ثبت است؛ برای یکی کردن، «ادغام» را بزنید.")
            contact.phone = phone
        if "email" in data:
            contact.email = str(data["email"]).strip()[:200]
        if "notes" in data:
            contact.notes = str(data["notes"])[:4000]
        if "tags" in data and isinstance(data["tags"], list):
            contact.tags = sorted({str(t).strip()[:40] for t in data["tags"] if str(t).strip()})[:30]
        contact.save()
        if "opt_out" in data and isinstance(data["opt_out"], dict):
            for channel, value in data["opt_out"].items():
                contacts_mod.set_opt_out(contact, channel, bool(value))
            contact.refresh_from_db()
        return Response(_contact_panel(contact))


def _contact_panel(contact: Contact) -> dict:
    """The right-hand customer panel: profile, orders, history across channels."""
    contacts_mod.refresh_stats(contact)
    customers = list(Customer.objects.filter(inbox_link__contact=contact))
    conversations = list(
        Conversation.objects.filter(customer__in=customers).select_related("customer", "inbox_meta")
        .order_by("-updated_at")[:20]
    )
    orders = Order.objects.filter(customer__in=customers).order_by("-created_at")[:10]
    seg_hits = []
    segments.ensure_builtin(contact.store)
    facts = segments.facts_for([contact])[contact.pk]
    for seg in Segment.objects.filter(store=contact.store):
        try:
            if segments.matches(segments.validate(seg.rules or {}), facts):
                seg_hits.append(seg.name)
        except segments.RuleError:
            continue
    data = ser.contact_json(contact, detail=True)
    data.update({
        "segments": seg_hits,
        "customers": [
            {"id": c.id, "channel": c.channel.upper(), "name": c.name,
             "matched_by": getattr(getattr(c, "inbox_link", None), "matched_by", "")}
            for c in customers
        ],
        "conversations": [
            {"id": c.id, "channel": c.channel, "state": c.state, "updated_at": c.updated_at,
             "is_test": bool(c.is_test)} for c in conversations
        ],
        "orders": [
            {"id": o.id, "status": o.status, "status_title": o.get_status_display(),
             "total": float(o.total), "at": o.confirmed_at or o.created_at,
             "items": o.items.count()} for o in orders
        ],
        "history": contacts_mod.history(contact, limit=60),
    })
    return data


class ConversationContactView(APIView):
    """The customer panel for the open conversation."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = store_of(request, store_id)
        conversation = conversation_of(store, pk)
        link = getattr(conversation.customer, "inbox_link", None)
        if link:
            contact = link.contact
        else:
            # Looking at a test chat must not put a real-looking contact into
            # the CRM, the segments and the «all contacts» audience.
            contact = contacts_mod.identify(
                conversation.customer, source=conversation.channel.lower(), is_test=sla.is_test(conversation),
            )
        return Response(_contact_panel(contact))


class ContactMergeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        keep = get_object_or_404(Contact, pk=pk, store=store)
        other = get_object_or_404(Contact, pk=request.data.get("with_contact"), store=store)
        merged = contacts_mod.merge(keep, other)
        return Response(_contact_panel(merged))


class CustomerUnlinkView(APIView):
    """Undo a wrong merge: this channel identity becomes its own contact again."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, customer_id):
        store = store_of(request, store_id, write=True)
        customer = get_object_or_404(Customer, pk=customer_id, store=store)
        fresh = contacts_mod.unlink(customer)
        return Response(_contact_panel(fresh))


# -------------------------------------------------------------- segments


class SegmentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = store_of(request, store_id)
        segments.ensure_builtin(store)
        rows = Segment.objects.filter(store=store)
        everyone = [c for c in Contact.objects.filter(store=store, is_test=False)]
        facts = segments.facts_for(everyone)
        out = []
        for seg in rows:
            try:
                rules = segments.validate(seg.rules or {})
                count = sum(1 for c in everyone if segments.matches(rules, facts[c.pk]))
            except segments.RuleError:
                count = None
            out.append(ser.segment_json(seg, count))
        return Response({
            "segments": out, "total_contacts": len(everyone),
            "fields": [{"key": k, "kind": v[0], "label": v[1]} for k, v in segments.FIELDS.items()],
        })

    def post(self, request, store_id):
        store = store_of(request, store_id, write=True)
        name = str(request.data.get("name", "")).strip()[:80]
        if not name:
            return fail("empty", "نام بخش را بنویسید.")
        try:
            rules = segments.validate(request.data.get("rules") or {"match": "all", "rules": []})
        except segments.RuleError as exc:
            return fail("bad_rules", str(exc))
        row = Segment.objects.create(
            store=store, name=name, rules=rules, description=str(request.data.get("description", ""))[:300],
        )
        return Response(ser.segment_json(row, segments.count_in(store, rules)), status=status.HTTP_201_CREATED)


class SegmentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        row = get_object_or_404(Segment, pk=pk, store=store)
        if row.builtin_key:
            return fail("builtin", "بخش‌های آماده را نمی‌شود ویرایش کرد؛ یک نسخه از آن بسازید.")
        if "name" in request.data:
            row.name = str(request.data["name"]).strip()[:80] or row.name
        if "rules" in request.data:
            try:
                row.rules = segments.validate(request.data["rules"])
            except segments.RuleError as exc:
                return fail("bad_rules", str(exc))
        if "description" in request.data:
            row.description = str(request.data["description"])[:300]
        row.save()
        return Response(ser.segment_json(row, segments.count_in(store, row.rules)))

    def delete(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        row = get_object_or_404(Segment, pk=pk, store=store)
        if row.builtin_key:
            return fail("builtin", "بخش‌های آماده حذف نمی‌شوند.")
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SegmentPreviewView(APIView):
    """How many people does this question select? (Nothing is saved.)"""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = store_of(request, store_id)
        try:
            rules = segments.validate(request.data.get("rules") or {})
            people = segments.contacts_in(store, rules)
        except segments.RuleError as exc:
            return fail("bad_rules", str(exc))
        return Response({"count": len(people), "sample": [ser.contact_json(c) for c in people[:5]]})


# ------------------------------------------------------------- broadcasts


def _broadcast_of(store, pk) -> Broadcast:
    return get_object_or_404(Broadcast.objects.select_related("segment", "created_by", "approved_by"), pk=pk, store=store)


class BroadcastListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = store_of(request, store_id)
        rows = Broadcast.objects.filter(store=store).select_related("segment", "created_by", "approved_by")[:100]
        can_approve = access.can(request.user, store, access.SETTINGS, write=True)
        return Response({
            "broadcasts": [ser.broadcast_json(b, request.user) for b in rows],
            "can_approve": can_approve,
            "sendable_channels": bc.sendable_channels(store),
            "rates": {c: bc.rate_for(store, c) for c in bc.PRIORITY},
        })

    def post(self, request, store_id):
        store = _marketing_store(request, store_id, write=True)
        name = str(request.data.get("name", "")).strip()[:120]
        text = str(request.data.get("text", "")).strip()
        if not name or not text:
            return fail("empty", "نام و متن پیام لازم است.")
        segment = None
        if request.data.get("segment_id"):
            segment = get_object_or_404(Segment, pk=request.data["segment_id"], store=store)
        scheduled = parse_datetime(str(request.data["scheduled_at"])) if request.data.get("scheduled_at") else None
        if scheduled is not None and timezone.is_naive(scheduled):
            scheduled = timezone.make_aware(scheduled)
        row = Broadcast.objects.create(
            store=store, name=name, text=text, segment=segment, created_by=request.user,
            channels=[c.upper() for c in (request.data.get("channels") or []) if c],
            dedupe=bool(request.data.get("dedupe", True)), scheduled_at=scheduled,
            is_test=bool(request.data.get("is_test", False)),
        )
        return Response(ser.broadcast_json(row, request.user), status=status.HTTP_201_CREATED)


class BroadcastDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = store_of(request, store_id)
        row = _broadcast_of(store, pk)
        data = ser.broadcast_json(row, request.user)
        sample = list(
            row.recipients.select_related("contact").order_by("id").values(
                "channel", "status", "skip_reason", "error", "contact__name", "contact__phone")[:30]
        )
        # Titles travel with the codes: the panel never has to print «SENT» or «opted_out».
        status_titles = dict(BroadcastRecipient.Status.choices)
        for item in sample:
            item["status_title"] = status_titles.get(item["status"], item["status"])
            item["skip_reason_title"] = bc.SKIP_REASON_TITLES.get(item["skip_reason"], "") if item["skip_reason"] else ""
        data["recipients_sample"] = sample
        return Response(data)

    def patch(self, request, store_id, pk):
        store = _marketing_store(request, store_id, write=True)
        row = _broadcast_of(store, pk)
        if row.status not in (Broadcast.Status.DRAFT, Broadcast.Status.REJECTED):
            return fail("locked", "فقط پیش‌نویس قابل ویرایش است.")
        for field in ("name", "text"):
            if field in request.data:
                setattr(row, field, str(request.data[field]).strip()[:120 if field == "name" else 4000])
        if "channels" in request.data:
            row.channels = [c.upper() for c in (request.data.get("channels") or []) if c]
        if "dedupe" in request.data:
            row.dedupe = bool(request.data["dedupe"])
        if "segment_id" in request.data:
            row.segment = get_object_or_404(Segment, pk=request.data["segment_id"], store=store) if request.data["segment_id"] else None
        if "scheduled_at" in request.data:
            when = parse_datetime(str(request.data["scheduled_at"])) if request.data["scheduled_at"] else None
            if when is not None and timezone.is_naive(when):
                when = timezone.make_aware(when)
            row.scheduled_at = when
        row.save()
        return Response(ser.broadcast_json(row, request.user))

    def delete(self, request, store_id, pk):
        store = _marketing_store(request, store_id, write=True)
        row = _broadcast_of(store, pk)
        if row.status not in (Broadcast.Status.DRAFT, Broadcast.Status.REJECTED, Broadcast.Status.CANCELLED):
            return fail("locked", "این ارسال را فقط می‌شود لغو کرد، نه حذف.")
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BroadcastPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = store_of(request, store_id)
        return Response(bc.preview(_broadcast_of(store, pk)))


class BroadcastActionView(APIView):
    """`submit` (ask for approval), `approve`, `reject`, `cancel`."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk, action):
        store = _marketing_store(request, store_id, write=True) if action in ("submit", "cancel") \
            else access.get_store(request.user, store_id)
        row = _broadcast_of(store, pk)
        if action in ("approve", "reject") and not access.can(request.user, store, access.SETTINGS, write=True):
            # A role problem is a 403 with the usual «ask the owner» sentence, not a business-rule 409.
            access.get_store(request.user, store_id, access.SETTINGS)
        try:
            if action == "submit":
                bc.submit(row, request.user)
            elif action == "approve":
                bc.approve(row, request.user)
            elif action == "reject":
                bc.reject(row, request.user, str(request.data.get("note", "")))
            elif action == "cancel":
                bc.cancel(row, request.user)
            else:
                return fail("bad_action", "کار نامعتبر است.")
        except bc.BroadcastError as exc:
            return fail("broadcast_rule", str(exc), status.HTTP_409_CONFLICT)
        row.refresh_from_db()
        return Response(ser.broadcast_json(row, request.user))


# -------------------------------------------------------------- follow-ups


class FollowUpListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = store_of(request, store_id)
        qp = request.query_params
        rows = FollowUp.objects.filter(store=store).select_related("assigned_to", "conversation__customer")
        if qp.get("status"):
            rows = rows.filter(status=qp["status"].upper())
        if qp.get("kind"):
            rows = rows.filter(kind=qp["kind"].upper())
        if qp.get("mine") == "1":
            rows = rows.filter(assigned_to=request.user)
        if qp.get("test") != "1":
            rows = rows.filter(is_test=False)
        rows = rows.order_by("due_at")[:200]
        return Response({
            "followups": [ser.followup_json(r) for r in rows],
            "test_total": FollowUp.objects.filter(store=store, is_test=True).count(),
        })


class FollowUpDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, store_id, pk):
        store = store_of(request, store_id, write=True)
        row = get_object_or_404(FollowUp, pk=pk, store=store)
        followups.cancel(row)
        return Response(ser.followup_json(row))
