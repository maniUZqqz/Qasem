# -*- coding: utf-8 -*-
"""سایت‌ساز: درخواست‌های AI که چون هوش مصنوعی در دسترس نبود در صف مانده‌اند، با برگشتنِ AI خودکار اجرا می‌شوند (apps/ai_engine/parking.py)."""
from celery import shared_task


@shared_task(name='apps.ai_engine.tasks.resume_parked', ignore_result=True)
def resume_parked():
    from . import parking
    return parking.resume_due()
