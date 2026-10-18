"""Payment gateway abstraction.

Every Iranian gateway this product is likely to use — ZarinPal, IDPay,
NextPay, Zibal — has the same three-step shape:

    request()  ask the gateway for a token, get back a URL to send the user to
    (user leaves the site, pays, comes back)
    verify()   ask the gateway whether that token was actually paid

So the rest of the codebase talks to this interface and never names a vendor.
Switching gateway is a settings change plus one new file here.

Two rules that matter more than the shape:

1. **Amounts are in Toman everywhere inside this project.** Several gateways
   want Rial, which is exactly ten times larger. That conversion lives in the
   provider that needs it and nowhere else — a 10× billing error is the kind of
   bug that only shows up in production, on a real customer's card.

2. **Verification is server-to-server.** The browser comes back from the
   gateway carrying a status, and that status is a hint, not evidence. Nothing
   is marked paid until the gateway itself confirms it over an API call we
   made.
"""
from __future__ import annotations

from dataclasses import dataclass


class PaymentError(Exception):
    """The gateway refused, or answered with something unusable."""


@dataclass(frozen=True)
class StartResult:
    """What the caller needs to send the user to the gateway."""

    # gateway-side identifier for this attempt (ZarinPal calls it an authority)
    token: str
    # where to send the browser
    redirect_url: str
    raw: dict


@dataclass(frozen=True)
class VerifyResult:
    """The gateway's own answer about whether money moved."""

    paid: bool
    # the bank reference a customer would quote in a dispute
    reference: str
    # Toman, as the gateway reports it — compared against what we asked for
    amount: int
    raw: dict
    message: str = ""


class PaymentProvider:
    """Base class. Subclasses implement `start` and `verify`."""

    #: short stable key stored on every Payment row
    key: str = ""
    #: shown to the user when choosing how to pay
    label: str = ""
    #: False when the provider needs a human to confirm (bank transfer)
    automatic: bool = True

    def start(self, *, amount_toman: int, description: str, callback_url: str,
              reference: str) -> StartResult:
        raise NotImplementedError

    def verify(self, *, token: str, amount_toman: int) -> VerifyResult:
        raise NotImplementedError

    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Whether this provider has what it needs to actually run."""
        return True
