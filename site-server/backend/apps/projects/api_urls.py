# -*- coding: utf-8 -*-
"""همهٔ نشانی‌های APIِ استودیو — در config/urls.py با
`path("api/v1/studio/", include("apps.projects.api_urls"))` سوار می‌شود.
رابطِ گرافیکی صفحه‌های پنلِ React است (frontend/src/features/tools/studio)."""
from django.urls import path

from apps.ai_engine import api as ai
from apps.project_importer import api as imp
from . import api
from .builder import api as vb
from .hosting import api as hosting
from .hosting import api as hosting

urlpatterns = [
    # پروژه‌ها
    path('projects/', api.project_list),                                      # GET فهرست · POST ساخت
    path('projects/<slug:slug>/', api.project_detail),                        # GET نمای کلی · DELETE حذف
    path('projects/<slug:slug>/settings/', api.project_settings),             # GET · POST/PUT
    path('projects/<slug:slug>/build/', api.do_build),                        # POST تولیدِ کد
    path('projects/<slug:slug>/migrate/', api.do_migrate),                    # POST مهاجرت
    path('projects/<slug:slug>/export/', api.do_export),                      # GET ZIP (?git=1)

    # بک‌اند: اپ / مدل / فیلد / ویو / نشانی
    path('projects/<slug:slug>/backend/', api.backend_studio),
    path('projects/<slug:slug>/apps/', api.app_add),                          # POST
    path('projects/<slug:slug>/apps/<int:pk>/', api.app_detail),              # GET · POST/PUT · DELETE
    path('projects/<slug:slug>/models/', api.model_add),                      # POST
    path('projects/<slug:slug>/models/<int:pk>/', api.model_detail),          # GET · POST/PUT · DELETE
    path('projects/<slug:slug>/models/<int:pk>/crud/', api.model_crud),       # POST
    path('projects/<slug:slug>/fields/', api.field_add),                      # POST
    path('projects/<slug:slug>/fields/<int:pk>/', api.field_detail),          # GET · POST/PUT · DELETE
    path('projects/<slug:slug>/fields/<int:pk>/move/', api.field_move),       # POST {dir: up|down}
    path('projects/<slug:slug>/views/', api.view_add),                        # POST
    path('projects/<slug:slug>/views/<int:pk>/', api.view_detail),            # GET · POST/PUT · DELETE
    path('projects/<slug:slug>/views/<int:pk>/reset/', api.view_reset),       # POST
    path('projects/<slug:slug>/routes/', api.routes_page),                    # GET نقشه · POST افزودن
    path('projects/<slug:slug>/routes/<int:pk>/', api.route_detail),          # GET · POST/PUT · DELETE

    # فرانت
    path('projects/<slug:slug>/frontend/', api.frontend_studio),
    path('projects/<slug:slug>/pages/', api.page_add),                        # POST
    path('projects/<slug:slug>/pages/<int:pk>/', api.page_detail),            # GET · POST/PUT · DELETE
    path('projects/<slug:slug>/pages/<int:pk>/reload/', imp.page_reload),     # POST (واردشده)
    path('projects/<slug:slug>/shared/<str:kind>/', api.shared_detail),       # GET · POST/PUT

    # ویرایشگرِ دیداری
    # انتشار روی اینترنت
    path('projects/<slug:slug>/hosting/', hosting.status),                    # GET وضعیت (?light=1)
    path('projects/<slug:slug>/hosting/publish/', hosting.do_publish),        # POST
    path('projects/<slug:slug>/hosting/stop/', hosting.do_stop),
    path('projects/<slug:slug>/hosting/start/', hosting.do_start),
    path('projects/<slug:slug>/hosting/rollback/', hosting.do_rollback),
    path('projects/<slug:slug>/hosting/unpublish/', hosting.do_unpublish),
    path('projects/<slug:slug>/hosting/purge/', hosting.do_purge),
    path('projects/<slug:slug>/hosting/reset-admin/', hosting.do_reset_admin),
    path('projects/<slug:slug>/hosting/domain/', hosting.domain),             # POST ثبت · DELETE جدا کردن
    path('projects/<slug:slug>/hosting/domain/check/', hosting.domain_check),  # POST
    path('projects/<slug:slug>/hosting/messages/', hosting.messages),         # GET · POST خوانده‌شدن

    # انتشار روی اینترنت
    path('projects/<slug:slug>/hosting/', hosting.status),                    # GET وضعیت (?light=1)
    path('projects/<slug:slug>/hosting/publish/', hosting.do_publish),        # POST
    path('projects/<slug:slug>/hosting/stop/', hosting.do_stop),
    path('projects/<slug:slug>/hosting/start/', hosting.do_start),
    path('projects/<slug:slug>/hosting/rollback/', hosting.do_rollback),
    path('projects/<slug:slug>/hosting/unpublish/', hosting.do_unpublish),
    path('projects/<slug:slug>/hosting/purge/', hosting.do_purge),
    path('projects/<slug:slug>/hosting/reset-admin/', hosting.do_reset_admin),
    path('projects/<slug:slug>/hosting/domain/', hosting.domain),             # POST ثبت · DELETE جدا کردن
    path('projects/<slug:slug>/hosting/domain/check/', hosting.domain_check),  # POST
    path('projects/<slug:slug>/hosting/messages/', hosting.messages),         # GET · POST خوانده‌شدن

    path('projects/<slug:slug>/builder/catalog/', vb.catalog),                # GET کتابخانهٔ بلوک‌ها و قالب‌ها
    path('projects/<slug:slug>/builder/bootstrap/', vb.bootstrap),            # GET ?target=page&page=<id>
    path('projects/<slug:slug>/builder/design/', vb.design_save),             # PUT پیش‌نویس
    path('projects/<slug:slug>/builder/render/', vb.render_canvas),           # POST رندرِ بوم
    path('projects/<slug:slug>/builder/publish/', vb.publish),                # POST انتشار
    path('projects/<slug:slug>/builder/versions/<int:pk>/', vb.version_detail),  # GET · POST بازگشت
    path('projects/<slug:slug>/builder/pages/', vb.page_create),              # POST از قالبِ آماده
    path('projects/<slug:slug>/builder/pages/<int:pk>/starter/', vb.page_starter),
    path('projects/<slug:slug>/builder/pages/<int:pk>/meta/', vb.page_meta),
    path('projects/<slug:slug>/builder/pages/<int:pk>/roundtrip-check/', vb.roundtrip_check),
    path('projects/<slug:slug>/builder/shared/<str:kind>/roundtrip-check/', vb.shared_roundtrip_check),
    path('projects/<slug:slug>/quick-edit/upload/', vb.quick_upload),         # POST
    path('projects/<slug:slug>/quick-edit/<str:kind>/<int:pk>/', vb.quick_edit),  # GET · POST
    path('projects/<slug:slug>/builder/theme/', vb.theme_detail),             # GET · PUT پوسته و منو
    path('projects/<slug:slug>/builder/media/', vb.media_list),               # GET · POST آپلود
    path('projects/<slug:slug>/builder/media/<int:pk>/', vb.media_detail),    # PUT · DELETE
    path('projects/<slug:slug>/builder/sections/', vb.section_list),          # GET · POST
    path('projects/<slug:slug>/builder/sections/<int:pk>/', vb.section_detail),
    path('projects/<slug:slug>/builder/models/<int:pk>/seed/', vb.model_seed),  # POST دادهٔ نمونه
    path('builder-media/<slug:slug>/u/<path:rel>', vb.public_user_media),
    path('builder-media/<slug:slug>/<str:name>', vb.public_media),
    path('builder-fonts/<str:name>', vb.public_font),

    # فایل، تاریخچه، پیش‌نمایش
    path('projects/<slug:slug>/files/', api.file_browser),
    path('projects/<slug:slug>/files/content/', api.file_read),               # ?f=rel/path
    path('projects/<slug:slug>/history/', api.history),
    path('projects/<slug:slug>/history/<str:sha>/', api.history_commit),
    path('projects/<slug:slug>/preview/', api.preview),
    path('projects/<slug:slug>/preview/start/', api.preview_start),           # POST
    path('projects/<slug:slug>/preview/stop/', api.preview_stop),             # POST

    # هوشِ مصنوعی
    path('ai/settings/', ai.ai_settings),                                     # GET · POST/PUT
    path('ai/route/', ai.ai_route),                                           # GET · POST {mode}
    path('ai/route/pull/', ai.ai_route_pull),                                 # POST دانلودِ مدل روی گره
    path('ai/settings/test/', ai.ai_settings_test),                           # POST
    path('projects/<slug:slug>/ai/', ai.ai_home),                             # GET · POST {act}
    path('projects/<slug:slug>/ai/page/<int:pk>/', ai.ai_edit_page),          # POST
    path('projects/<slug:slug>/ai/shared/<str:kind>/', ai.ai_edit_shared),    # POST
    path('projects/<slug:slug>/ai/view/<int:pk>/', ai.ai_edit_view),          # POST
    path('projects/<slug:slug>/ai/proposals/<int:pk>/', ai.ai_proposal),
    path('projects/<slug:slug>/ai/proposals/<int:pk>/status/', ai.ai_proposal_status),
    path('projects/<slug:slug>/ai/proposals/<int:pk>/apply/', ai.ai_apply),   # POST {change: [ids]}
    path('projects/<slug:slug>/ai/proposals/<int:pk>/reject/', ai.ai_reject), # POST
    path('projects/<slug:slug>/ai/proposals/<int:pk>/revert/', ai.ai_revert), # POST

    # واردکردن
    path('import/', imp.import_form),                                         # GET ریشه‌ها · POST (multipart)
    path('projects/<slug:slug>/import-report/', imp.import_report),
    path('projects/<slug:slug>/deps/', imp.deps_install),                     # POST
]
