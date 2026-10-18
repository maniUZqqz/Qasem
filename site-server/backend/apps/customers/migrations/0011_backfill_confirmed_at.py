"""Give the orders that were already confirmed a confirmation date.

The sales chart now groups revenue by `confirmed_at`, so without this every
order placed before the field existed would fall out of every report — the
numbers would not just shift, they would vanish. `updated_at` is the closest
truth available: confirming was the last thing done to those rows.

They are also marked APPLIED so nobody's warehouse is retroactively emptied:
those items left the shop months ago, and re-running the deduction now would
subtract a whole history of sales from today's shelf.
"""
from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    Order = apps.get_model("customers", "Order")
    Order.objects.filter(status="CONFIRMED", confirmed_at__isnull=True).update(
        confirmed_at=F("updated_at")
    )
    Order.objects.filter(status="CONFIRMED").update(stock_state="APPLIED")


def unbackfill(apps, schema_editor):
    Order = apps.get_model("customers", "Order")
    Order.objects.update(confirmed_at=None, stock_state="NONE")


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0010_order_confirmed_at_order_reserved_until_and_more"),
    ]

    operations = [migrations.RunPython(backfill, unbackfill)]
