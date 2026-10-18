"""GTM endpoints. Phase 26.

Split by audience, which is also the permission boundary:

* **A shop owner** gets their own referral code and how it is doing. Nothing
  else here is theirs to see.
* **Anyone signing up** gets `CodeCheckView`, which is unauthenticated by
  necessity — the code is typed before the account exists.
* **Staff** get the intelligence report and the payout list. It spans every
  customer, so it is ours, not any one shop's.

`CodeCheckView` is the one that needs care. It is a public endpoint that says
whether a string is a real code, which is an oracle someone can enumerate. It
is throttled, it never reveals who owns a referral code, and it answers the same
way for "no such code" as for "that code is not active".
"""
import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.stores import access

from . import intelligence
from .gtm import Attribution, ReferralCode, Reward, resolve_code

logger = logging.getLogger(__name__)


class CodeThrottle(AnonRateThrottle):
    """A public endpoint that says whether a string is a real code is an oracle.
    Throttled so it cannot be enumerated at speed."""

    scope = "code_check"


class CodeCheckView(APIView):
    """«این کد چیست؟» — asked on the signup form, before there is an account."""

    permission_classes = [AllowAny]
    throttle_classes = [CodeThrottle]

    def post(self, request):
        kind, found = resolve_code(str(request.data.get("code", "")))

        if kind in ("none", "unknown") or found is None:
            # One answer for "no such code" and "code exists but is off". The
            # difference tells someone whether they guessed a real prefix.
            return Response({
                "valid": False,
                "message": "این کد شناخته نشد.",
            })

        if kind == "referral":
            return Response({
                "valid": True,
                "kind": "referral",
                # Never the owner's name or shop. A signup form is not a place
                # to learn who our customers are.
                "message": (
                    f"کد معرفی معتبر است — {found.friend_discount_percent}٪ تخفیف "
                    "روی دوره‌ی اول شما."
                    if found.friend_discount_percent
                    else "کد معرفی معتبر است."
                ),
                "discount_percent": found.friend_discount_percent,
            })

        if kind == "affiliate":
            return Response({
                "valid": True,
                "kind": "affiliate",
                "message": f"از طریق {found.name} آمده‌اید.",
                "discount_percent": 0,
            })

        reason = found.unusable_because()
        if reason:
            return Response({"valid": False, "message": reason})
        return Response({
            "valid": True,
            "kind": "discount",
            "message": (
                f"{found.value}٪ تخفیف" if found.kind == found.Kind.PERCENT
                else f"{found.value:,} تومان تخفیف"
            ),
            "discount_percent": found.value if found.kind == found.Kind.PERCENT else 0,
        })


class MyReferralView(APIView):
    """A shop's own invite code and how it is doing. §26"""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.SETTINGS, write=False)
        code = ReferralCode.objects.filter(store=store).first()
        if code is None:
            return Response({"code": None, "signups": 0, "paying": 0, "earned_toman": 0})
        return Response(self._payload(code))

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.SETTINGS)
        # The code belongs to the **store**, and the reward goes to whoever
        # owns it — not to whichever colleague happened to press the button.
        # Keying this on `request.user` gave a shop with two admins two codes,
        # split its referral count between them, and paid the reward to the
        # faster clicker rather than to the account that pays the bills.
        code, _ = ReferralCode.objects.get_or_create(
            store=store,
            defaults={
                "owner": store.owner,
                "reward_toman": 0,
                "friend_discount_percent": 10,
            },
        )
        return Response(self._payload(code), status=status.HTTP_201_CREATED)

    def _payload(self, code) -> dict:
        earned = sum(
            r.amount_toman for r in Reward.objects.filter(
                user=code.owner, kind=Reward.Kind.REFERRAL,
            )
        )
        paid = sum(
            r.amount_toman for r in Reward.objects.filter(
                user=code.owner, kind=Reward.Kind.REFERRAL, state=Reward.State.PAID,
            )
        )
        return {
            "code": code.code,
            "friend_discount_percent": code.friend_discount_percent,
            "reward_toman": code.reward_toman,
            "signups": code.signups,
            # The two are shown side by side on purpose: a referrer with twelve
            # signups and no paying customers should see why nothing was earned.
            "paying": code.paying,
            "earned_toman": earned,
            "paid_toman": paid,
            "pending_toman": earned - paid,
        }


class MarketingReportView(APIView):
    """Where our customers come from. Staff only — it spans every shop."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            days = max(1, min(730, int(request.query_params.get("days", 90))))
        except (TypeError, ValueError):
            days = 90
        return Response(intelligence.report(days))


class RewardListView(APIView):
    """What we owe, and marking it paid. Staff only.

    Payment is a person pressing a button, never an automatic consequence of a
    signup. The whole reason `Reward` exists as a row rather than a transfer.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        state = request.query_params.get("state") or Reward.State.PENDING
        rows = Reward.objects.filter(state=state).select_related(
            "user", "affiliate", "attribution__store",
        )[:200]
        return Response({
            "rewards": [
                {
                    "id": r.pk,
                    "kind": r.get_kind_display(),
                    "state": r.state,
                    "amount_toman": r.amount_toman,
                    "to": r.user.username if r.user else (
                        r.affiliate.name if r.affiliate else "—"
                    ),
                    "store": r.attribution.store.name,
                    "because": r.because,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
            "total_toman": sum(r.amount_toman for r in rows),
        })

    def post(self, request):
        reward = Reward.objects.filter(pk=request.data.get("id")).first()
        if reward is None:
            return Response(
                {"error": {"code": "not_found", "message": "این پاداش پیدا نشد."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        action = str(request.data.get("action", "pay"))
        if action == "void":
            reward.state = Reward.State.VOID
            reward.save(update_fields=["state", "updated_at"])
        elif action == "approve":
            reward.state = Reward.State.APPROVED
            reward.save(update_fields=["state", "updated_at"])
        else:
            reward.pay(request.user)
        return Response({"id": reward.pk, "state": reward.state})


class AttributionView(APIView):
    """One shop's own "where did we come from". Read-only by design.

    Written once at signup and never edited — a customer who could change their
    own attribution could change what we owe somebody.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.SETTINGS, write=False)
        row = Attribution.objects.filter(store=store).first()
        if row is None:
            return Response({"channel": None})
        return Response({
            "channel": row.channel,
            "channel_title": row.get_channel_display(),
            "campaign": row.campaign,
            "source": row.source,
            "landing_path": row.landing_path,
            "became_paying_at": row.became_paying_at,
            "days_to_pay": row.days_to_pay,
        })


class CRMView(APIView):
    """Lead → Customer → Onboarding → Support → Retention, in one read.

    Staff only: it spans every customer and names the ones about to leave.
    Read-only by design — a CRM that quietly changes subscription state is a
    CRM that fights with billing.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        from . import crm

        try:
            limit = max(1, min(500, int(request.query_params.get("limit", 200))))
        except (TypeError, ValueError):
            limit = 200
        return Response(crm.board(limit))
