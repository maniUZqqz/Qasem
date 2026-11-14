"""Where a notification takes the owner when they tap it.

A notification's `link` is a panel route (`NotificationsBell` does
`navigate(link)`). Three of them pointed at routes that do not exist
(`/stores/<id>/settings` renders a blank page) and several at the *overview* of
a section (`/sales`) when the thing they announce lives in a tab of it.

Every link the customers app creates is built here, so there is one place to
check them against the panel's registry — `tests_notification_links.py` does
exactly that, for every `link=` literal in the backend.
"""
from __future__ import annotations


def orders_link(store_id: int) -> str:
    """A new (draft) order — the «سفارش‌ها» tab."""
    return f"/stores/{store_id}/sales/orders"


def tickets_link(store_id: int) -> str:
    """A support ticket — the «تیکت‌ها» tab."""
    return f"/stores/{store_id}/sales/tickets"


def receipts_link(store_id: int) -> str:
    """A payment receipt waiting for a decision — the «رسیدها» tab."""
    return f"/stores/{store_id}/sales/receipts"


def data_policy_link(store_id: int) -> str:
    """«سیاست داده» — where a data-policy block is explained and changed."""
    return f"/stores/{store_id}/data"


def conversation_link(conversation) -> str:
    """The thread itself, not just the page it lives on.

    A conversation the owner started from the panel's test chat is read in the
    test chat; every other one lives in the shared inbox. Both pages open the
    conversation named by `?c=<id>`.
    """
    if conversation.is_test:
        return f"/stores/{conversation.store_id}/chat?c={conversation.id}"
    return f"/stores/{conversation.store_id}/inbox?c={conversation.id}"
