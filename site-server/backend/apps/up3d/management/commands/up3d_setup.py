"""راه‌اندازیِ اولیه: کاربرِ مدیر، کارگرِ محلی، تنظیماتِ AI (اختیاری از متغیرهای محیطی)."""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.up3d.models import AiSettings, Worker


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--admin-user', default='admin')
        parser.add_argument('--admin-pass', default='')
        parser.add_argument('--local-worker', default='server-cpu')

    def handle(self, *args, **o):
        U = get_user_model()
        if o['admin_pass']:
            u, created = U.objects.get_or_create(username=o['admin_user'], defaults={'is_staff': True, 'is_superuser': True})
            u.is_staff = u.is_superuser = True
            u.set_password(o['admin_pass'])
            u.save()
            self.stdout.write('admin user: %s (%s)' % (u.username, 'created' if created else 'password reset'))
        w, _ = Worker.objects.get_or_create(name=o['local_worker'])
        data = os.environ.get('UP3D_DATA')
        if data:
            path = os.path.join(data, 'local-worker.token')
            with open(path, 'w') as fh:
                fh.write(w.token)
            os.chmod(path, 0o600)
        ai = AiSettings.get()
        for env, field in (('UP3D_AI_KEY', 'api_key'), ('UP3D_AI_BASE_URL', 'base_url'), ('UP3D_AI_MODEL', 'model')):
            if os.environ.get(env) and not getattr(ai, field):
                setattr(ai, field, os.environ[env])
        ai.save()
        self.stdout.write('local worker: %s ; ai configured: %s' % (w.name, bool(ai.api_key)))
