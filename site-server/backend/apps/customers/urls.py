from django.urls import path

from .views_inbox import (
    ConversationAssignView,
    ConversationTagsView,
    InboxReplyView,
    InboxView,
)
from .views_outreach import ProspectDetailView, ProspectListView
from .views_calls import CallPrepView, ConsentView, RecordingListView
from .views_webhook import InboundWebhook
from .views import (
    ChatView,
    ConversationListView,
    HandoffView,
    MessageListView,
    NotificationListView,
    NotificationReadView,
    OrderDecisionView,
    OrderListView,
    OrderReceiptView,
    TicketListView,
    TicketResolveView,
)

urlpatterns = [
    # ---- پیام ورودی از پلتفرم‌ها -----------------------------------------
    # بدون احراز هویت کاربر: فرستنده پلتفرم است نه آدم. اعتبارسنجی با راز
    # داخل آدرس + امضای خود پلتفرم انجام می‌شود (webhooks.verify).
    path(
        "webhooks/<str:channel>/<str:secret>/",
        InboundWebhook.as_view(), name="inbound-webhook",
    ),
    # ---- صفحه ۷ — بازاریابی تلفنی (فهرست، بدون ضبط و بدون جست‌وجو) ---------
    path(
        "stores/<int:store_id>/prospects/",
        ProspectListView.as_view(), name="store-prospects",
    ),
    path(
        "stores/<int:store_id>/prospects/<int:pk>/",
        ProspectDetailView.as_view(), name="store-prospect",
    ),
    # ضبط تماس — رضایت اول، بعد فایل. بدون ردیف رضایت چیزی ذخیره نمی‌شود.
    path(
        "stores/<int:store_id>/prospects/<int:pk>/consent/",
        ConsentView.as_view(), name="prospect-consent",
    ),
    path(
        "stores/<int:store_id>/prospects/<int:pk>/recordings/",
        RecordingListView.as_view(), name="prospect-recordings",
    ),
    path(
        "stores/<int:store_id>/prospects/<int:pk>/prep/",
        CallPrepView.as_view(), name="prospect-prep",
    ),
    # ---- unified inbox (§9.7) --------------------------------------------
    path("stores/<int:store_id>/inbox/", InboxView.as_view(), name="store-inbox"),
    path(
        "stores/<int:store_id>/inbox/<int:pk>/assign/",
        ConversationAssignView.as_view(), name="inbox-assign",
    ),
    path(
        "stores/<int:store_id>/inbox/<int:pk>/tags/",
        ConversationTagsView.as_view(), name="inbox-tags",
    ),
    path(
        "stores/<int:store_id>/inbox/<int:pk>/reply/",
        InboxReplyView.as_view(), name="inbox-reply",
    ),
    path("stores/<int:store_id>/chat/", ChatView.as_view(), name="store-chat"),
    path(
        "stores/<int:store_id>/conversations/",
        ConversationListView.as_view(),
        name="store-conversations",
    ),
    path("stores/<int:store_id>/orders/", OrderListView.as_view(), name="store-orders"),
    path("stores/<int:store_id>/tickets/", TicketListView.as_view(), name="store-tickets"),
    path("conversations/<int:pk>/messages/", MessageListView.as_view(), name="conversation-messages"),
    path("conversations/<int:pk>/handoff/", HandoffView.as_view(), name="conversation-handoff"),
    path("orders/<int:pk>/receipt/", OrderReceiptView.as_view(), name="order-receipt"),
    path(
        "orders/<int:pk>/confirm/",
        OrderDecisionView.as_view(),
        {"decision": "confirm"},
        name="order-confirm",
    ),
    path(
        "orders/<int:pk>/reject/",
        OrderDecisionView.as_view(),
        {"decision": "reject"},
        name="order-reject",
    ),
    path(
        "orders/<int:pk>/cod/",
        OrderDecisionView.as_view(),
        {"decision": "cod"},
        name="order-cod",
    ),
    path(
        "orders/<int:pk>/cancel/",
        OrderDecisionView.as_view(),
        {"decision": "cancel"},
        name="order-cancel",
    ),
    path("tickets/<int:pk>/resolve/", TicketResolveView.as_view(), name="ticket-resolve"),
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/read-all/", NotificationReadView.as_view(), name="notifications-read-all"),
    path("notifications/<int:pk>/read/", NotificationReadView.as_view(), name="notification-read"),
]
