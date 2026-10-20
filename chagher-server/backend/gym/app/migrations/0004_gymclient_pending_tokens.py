from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0003_paymentgatewayconfig_smsconfig'),
    ]

    operations = [
        migrations.AddField(
            model_name='gymclient',
            name='pending_tokens',
            field=models.IntegerField(
                default=0,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name='توکن رزروشده قبل از فعال‌سازی'
            ),
        ),
    ]
