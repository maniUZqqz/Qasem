# -*- coding: utf-8 -*-
from django.db import models


class ImportReport(models.Model):
    """گزارشِ سازگاریِ یک پروژهٔ واردشده (idea.md §۸ گامِ ۳)."""
    LEVELS = [(1, 'سطح ۱ — فقط مشاهده'), (2, 'سطح ۲ — ویرایشِ قالب‌ها و افزودنِ اپِ تازه'),
              (3, 'سطح ۳ — توسعهٔ گرافیکیِ عمیق')]
    project = models.OneToOneField('projects.Project', on_delete=models.CASCADE, related_name='import_report')
    level = models.PositiveSmallIntegerField(choices=LEVELS, default=1, verbose_name='سطحِ پشتیبانی')
    data = models.TextField(blank=True, verbose_name='تحلیل (JSON)')
    warnings = models.TextField(blank=True, verbose_name='هشدارها')
    unsupported = models.TextField(blank=True, verbose_name='پشتیبانی‌نشده')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'گزارشِ واردکردن'
        verbose_name_plural = 'گزارش‌های واردکردن'

    def __str__(self):
        return '%s — سطح %d' % (self.project.slug, self.level)

    @property
    def warning_list(self):
        return [x for x in self.warnings.splitlines() if x.strip()]

    @property
    def unsupported_list(self):
        return [x for x in self.unsupported.splitlines() if x.strip()]
