import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('motion', '0002_motion_v2'),
        ('stores', '0012_storeprofile_telegram_bot_token'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MotionCustomStyle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('style_id', models.CharField(max_length=60, unique=True)),
                ('name_fa', models.CharField(max_length=60)),
                ('name_en', models.CharField(blank=True, max_length=60)),
                ('data', models.JSONField(default=dict)),
                ('base_style', models.CharField(blank=True, max_length=60)),
                ('qa', models.JSONField(blank=True, default=dict)),
                ('qa_hash', models.CharField(blank=True, max_length=40)),
                ('thumb', models.CharField(blank=True, max_length=400)),
                ('store', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='motion_custom_styles', to='stores.store')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
                'indexes': [models.Index(fields=['store', '-updated_at'], name='motion_moti_store_i_be6f12_idx')],
            },
        ),
        migrations.CreateModel(
            name='MotionStyleCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('style_hash', models.CharField(db_index=True, max_length=40)),
                ('style', models.JSONField(default=dict)),
                ('state', models.CharField(choices=[('running', 'در حال اجرا'), ('pass', 'قبول'), ('fail', 'رد'), ('error', 'خطا')], db_index=True, default='running', max_length=8)),
                ('report', models.JSONField(blank=True, default=dict)),
                ('thumb', models.CharField(blank=True, max_length=400)),
                ('store', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='motion_style_checks', to='stores.store')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['store', '-created_at'], name='motion_moti_store_i_f2f44b_idx')],
            },
        ),
    ]
