"""Who may use the Growth Engine.

The tool is internal: only staff accounts (``is_staff``) - the same role the panel
already uses for «ادمین» and «ابزارها». The check is repeated on the server for
every endpoint; hiding the menu is only navigation.
"""
from rest_framework.permissions import BasePermission


class IsGrowthStaff(BasePermission):
    message = "این بخش فقط برای کارکنانِ آپ‌مارکت است."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_staff)
