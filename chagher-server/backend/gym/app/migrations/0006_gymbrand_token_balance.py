from django.db import migrations, models
import django.core.validators


def forwards(apps, schema_editor):
    GymBrand = apps.get_model('app', 'GymBrand')
    for brand in GymBrand.objects.select_related('user').all():
        # انتقال موجودی فعلی کاربر به کیف پول باشگاه در اولین مهاجرت
        if brand.token_balance == 0 and brand.user and brand.user.token_balance > 0:
            brand.token_balance = brand.user.token_balance
            brand.save(update_fields=['token_balance'])


def backwards(apps, schema_editor):
    # برگشت نیاز به اقدام خاصی ندارد.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0005_alter_gymclient_access_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='gymbrand',
            name='token_balance',
            field=models.IntegerField(
                default=0,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name='کیف پول توکن باشگاه'
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
