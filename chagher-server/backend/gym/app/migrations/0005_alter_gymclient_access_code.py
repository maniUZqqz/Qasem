from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0004_gymclient_pending_tokens'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gymclient',
            name='access_code',
            field=models.CharField(max_length=20, unique=True, verbose_name='کد دسترسی یکبار مصرف'),
        ),
    ]
