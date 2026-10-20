from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RegisterView, PersonalRegisterView, LoginView, LogoutView,
    PasswordResetRequestView, PasswordResetConfirmView, ChangePasswordView,
    UserProfileView,
    EquipmentViewSet, EquipmentCategoryViewSet, MealViewSet,
    EquipmentSuggestionView, EquipmentBulkAddView,
    GenerateProgramView, EditProgramView, GeneratePDFView, ProgramDetailView, HistoryView,
    ProgramShareCodeView, RedeemProgramCodeView,
    GenerateWorkoutPDFView, GenerateMealPDFView
)
from .views_extended import (
    TokenPackageViewSet, PurchaseTokenView, PaymentCallbackView,
    ValidateDiscountCodeView, GymBrandView, CoachInstructionView, GymClientViewSet,
    ClientAccessView, ClientProfileView, TokenRequestViewSet,
    HomePageView, BlogPostViewSet, ContactMessageView,
    TeamMemberListView, FeatureListView, mock_payment_page,
    CardPaymentInfoView, PaymentMethodsView, UploadPaymentReceiptView, MyPurchasesView,
    PaymentReceiptFileView
)
from .sms_views import SendRegisterCodeView, PeekRegisterCodeView
from .sms_webhook import sms_webhook
from .sms_gateway import next_otp, mark_sent


# Router برای ViewSets
router = DefaultRouter()
router.register(r'equipments', EquipmentViewSet, basename='equipment')
router.register(r'equipment-categories', EquipmentCategoryViewSet, basename='equipment-category')
router.register(r'meals', MealViewSet, basename='meal')
router.register(r'token-packages', TokenPackageViewSet, basename='token-package')
router.register(r'gym-clients', GymClientViewSet, basename='gym-client')
router.register(r'token-requests', TokenRequestViewSet, basename='token-request')
router.register(r'blog', BlogPostViewSet, basename='blog')

urlpatterns = [
    # ==================== Authentication ====================
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('auth/password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('auth/register-personal/', PersonalRegisterView.as_view(), name='register-personal'),

    # ==================== User Profile ====================
    path('user/profile/', UserProfileView.as_view(), name='user-profile'),

    # ==================== Equipment Suggestions ====================
    path('equipment-suggestions/', EquipmentSuggestionView.as_view(), name='equipment-suggestions'),
    path('equipments/bulk-add/', EquipmentBulkAddView.as_view(), name='equipment-bulk-add'),

    # ==================== Programs ====================
    path('programs/generate/', GenerateProgramView.as_view(), name='generate-program'),
    path('programs/<int:program_id>/edit/', EditProgramView.as_view(), name='edit-program'),
    path('programs/<int:program_id>/pdf/', GeneratePDFView.as_view(), name='generate-pdf'),
    path('programs/<int:program_id>/', ProgramDetailView.as_view(), name='program-detail'),
    path('programs/history/', HistoryView.as_view(), name='program-history'),

    # کد یکبارمصرف دانلود برنامه‌ای که مربی از قبل ساخته است
    path(
        'programs/<int:program_id>/share-code/',
        ProgramShareCodeView.as_view(),
        name='program-share-code',
    ),
    path(
        'programs/redeem-code/',
        RedeemProgramCodeView.as_view(),
        name='program-redeem-code',
    ),

    path('programs/<int:program_id>/pdf-workout/', GenerateWorkoutPDFView.as_view(), name='program-pdf-workout'),
    path('programs/<int:program_id>/pdf-meal/', GenerateMealPDFView.as_view(), name='program-pdf-meal'),

    # ==================== Token Purchase & Payment ====================
    path('purchase-token/', PurchaseTokenView.as_view(), name='purchase-token'),
    path('payment-callback/', PaymentCallbackView.as_view(), name='payment-callback'),

    # روش‌های پرداخت فعال (کارت‌به‌کارت / درگاه)
    path('payment-methods/', PaymentMethodsView.as_view(), name='payment-methods'),

    # پرداخت کارت‌به‌کارت
    path('payment-card/', CardPaymentInfoView.as_view(), name='payment-card'),
    path(
        'purchase-token/<int:purchase_id>/receipt/',
        UploadPaymentReceiptView.as_view(),
        name='purchase-receipt',
    ),
    path(
        'purchase-token/<int:purchase_id>/receipt/file/',
        PaymentReceiptFileView.as_view(),
        name='purchase-receipt-file',
    ),
    path('my-purchases/', MyPurchasesView.as_view(), name='my-purchases'),
    # صفحه شبیه‌ساز درگاه — فقط وقتی درگاه فعال از نوع «تستی» باشد
    path('mock-payment/', mock_payment_page, name='mock-payment'),
    path('validate-discount-code/', ValidateDiscountCodeView.as_view(), name='validate-discount-code'),

    # ==================== Gym Branding ====================
    path('gym-brand/', GymBrandView.as_view(), name='gym-brand'),
    path('coach-instructions/', CoachInstructionView.as_view(), name='coach-instructions'),

    # ==================== Client Access ====================
    path('client-access/', ClientAccessView.as_view(), name='client-access'),
    path('client-profile/', ClientProfileView.as_view(), name='client-profile'),



    # ==================== Content Pages (Public) ====================
    path('homepage/', HomePageView.as_view(), name='homepage'),
    path('contact/', ContactMessageView.as_view(), name='contact'),
    path('team-members/', TeamMemberListView.as_view(), name='team-members'),
    path('features/', FeatureListView.as_view(), name='features'),

    # ==================== Router URLs ====================
    path('', include(router.urls)),
    
    
    
    # ==================== SMS Verification ====================
    path('auth/send-register-code/', SendRegisterCodeView.as_view(), name='send-register-code'),
    # ⚠️ فقط برای دیباگ:
    path('auth/peek-register-code/', PeekRegisterCodeView.as_view(), name='peek-register-code'),
    path('sms/webhook/', sms_webhook, name='sms-webhook'),

    # ==================== گیت‌وی پیامک (گوشی) ====================
    # مثل نمونهٔ فلسک بدون / انتهایی؛ با / هم کار می‌کند
    path('next-otp', next_otp, name='sms-next-otp'),
    path('next-otp/', next_otp),
    path('mark-sent', mark_sent, name='sms-mark-sent'),
    path('mark-sent/', mark_sent),
]

# ── کتابخانهٔ حرکت‌ها (دیتاستِ چغر) ──
from . import exercise_library_api as _exlib  # noqa: E402

urlpatterns += [
    path('exercise-library/import/', _exlib.import_exercises, name='exlib-import'),
    path('exercise-library/status/', _exlib.import_status, name='exlib-status'),
    path('exercise-library/<str:external_id>/media/', _exlib.upload_media, name='exlib-media'),
    path('exercise-library/', _exlib.list_exercises, name='exlib-list'),
]

# ── برنامهٔ دستیِ مربی (بدونِ هوش مصنوعی) ──
from . import views_manual as _man  # noqa: E402

urlpatterns += [
    path('programs/manual/quota/', _man.ManualProgramQuotaView.as_view(), name='manual-program-quota'),
    path('programs/manual/<int:program_id>/', _man.ManualProgramDetailView.as_view(), name='manual-program-detail'),
    path('programs/manual/', _man.ManualProgramView.as_view(), name='manual-program'),
]

# ── اسکنِ دستگاه‌های باشگاه با دوربین ──
from . import views_scan as _scan  # noqa: E402

urlpatterns += [
    path('equipment-scan/candidates/', _scan.EquipmentScanCandidatesView.as_view(), name='equipment-scan-candidates'),
    path('equipment-scan/start/', _scan.EquipmentScanStartView.as_view(), name='equipment-scan-start'),
    path('equipment-scan/<int:scan_id>/frame/', _scan.EquipmentScanFrameView.as_view(), name='equipment-scan-frame'),
    path('equipment-scan/<int:scan_id>/confirm/', _scan.EquipmentScanConfirmView.as_view(), name='equipment-scan-confirm'),
    path('equipment-scan/<int:scan_id>/', _scan.EquipmentScanDetailView.as_view(), name='equipment-scan-detail'),
    path('equipment-scan/', _scan.EquipmentScanView.as_view(), name='equipment-scan'),
]

# ── ورزشکارِ شخصی (B2C) ──
from . import views_b2c as _b2c  # noqa: E402

urlpatterns += [
    path('me/athlete-profile/', _b2c.AthleteProfileView.as_view(), name='athlete-profile'),
    path('me/status/', _b2c.MyStatusView.as_view(), name='my-status'),
    path('me/features/', _b2c.MyFeaturesView.as_view(), name='my-features'),
]

# ── بررسیِ درستیِ حرکت با دوربین (با کلیدِ خاموش/روشن در جنگو ادمین) ──
from . import views_formcheck as _fcv  # noqa: E402

urlpatterns += [
    path('form-check/session/<int:session_id>/frame/', _fcv.FormCheckFrameView.as_view(), name='form-check-frame'),
    path('form-check/session/<int:session_id>/finish/', _fcv.FormCheckFinishView.as_view(), name='form-check-finish'),
    path('form-check/<str:external_id>/start/', _fcv.FormCheckStartView.as_view(), name='form-check-start'),
    path('form-check/<str:external_id>/', _fcv.FormCheckInfoView.as_view(), name='form-check-info'),
]

# ── حرکت‌های خودِ مربی (مورد ۵) ──
from . import exercise_mine_api as _mine  # noqa: E402

urlpatterns += [
    path('exercise-library/mine/', _mine.my_exercises, name='my-exercises'),
    path('exercise-library/mine/<str:external_id>/', _mine.my_exercise_detail,
         name='my-exercise-detail'),
]

# ── پلِ سرورِ هوش مصنوعیِ بی‌آی‌پی (مورد ۷) ──
# این مسیرها را **کارگرِ محلی** صدا می‌زند، نه کاربر. احراز با کلیدِ مشترکی که
# در جنگو ادمین روی همان ارائه‌دهنده گذاشته می‌شود.
from . import ai_bridge as _bridge  # noqa: E402

urlpatterns += [
    path('ai-bridge/claim/', _bridge.claim, name='ai-bridge-claim'),
    path('ai-bridge/heartbeat/', _bridge.heartbeat, name='ai-bridge-heartbeat'),
    path('ai-bridge/<int:job_id>/result/', _bridge.result, name='ai-bridge-result'),
    path('ai-bridge/<int:job_id>/fail/', _bridge.fail, name='ai-bridge-fail'),
]
