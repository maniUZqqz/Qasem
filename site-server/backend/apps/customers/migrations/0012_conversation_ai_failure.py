from django.db import migrations, models


class Migration(migrations.Migration):
    """The AI failing to answer a customer becomes a state of the conversation.

    Five nullable / defaulted columns, no table rebuild of consequence (see
    `Conversation.ai_failed_at` and `apps.customers.ai_retry`).
    """

    dependencies = [
        ("customers", "0011_backfill_confirmed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="ai_failed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="conversation",
            name="ai_failed_reason",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
        migrations.AddField(
            model_name="conversation",
            name="ai_retries",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="conversation",
            name="ai_retry_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="conversation",
            name="ai_ack_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
