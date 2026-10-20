from rest_framework import serializers
from django.contrib.auth import authenticate
from drf_spectacular.utils import extend_schema_field

from .models import (
    CustomUser, Equipment, EquipmentCategory, Meal, ClientProgram, TokenPackage, DiscountCode, DiscountCodeUsage, TokenPurchase, GymBrand, GymClient, TokenRequest, HomePage, BlogPost, ContactMessage, TeamMember, Feature, CardPaymentAccount, ProgramShareCode
)






# ==================== Registration OTP Serializers ====================

class SendRegisterCodeSerializer(serializers.Serializer):
    """درخواست ارسال کد تایید ثبت‌نام."""
    phone_number = serializers.CharField(max_length=11)
    
    




# ==================== Authentication Serializers ====================
class RegisterSerializer(serializers.ModelSerializer):
    """سریالایزر ثبت‌نام"""
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)
    verification_code = serializers.CharField(write_only=True, min_length=4, max_length=4)

    class Meta:
        model = CustomUser
        fields = ['phone_number', 'password', 'password_confirm', 'gym_name', 'verification_code']

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "رمزهای عبور مطابقت ندارند."})

        # ✅ تایید کد پیامکی — اتمیک و یک‌بارمصرف
        from .sms_hook import verify_registration_code
        if not verify_registration_code(attrs['phone_number'], attrs['verification_code']):
            raise serializers.ValidationError(
                {"verification_code": "کد تایید نامعتبر یا منقضی است."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        validated_data.pop('verification_code')
        return CustomUser.objects.create_user(
            phone_number=validated_data['phone_number'],
            password=validated_data['password'],
            gym_name=validated_data.get('gym_name', ''),
        )


class PersonalRegisterSerializer(serializers.ModelSerializer):
    """سریالایزر ثبت‌نام کاربر شخصی (B2C)"""
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)
    verification_code = serializers.CharField(write_only=True, min_length=4, max_length=4)
    full_name = serializers.CharField(max_length=100, required=False, allow_blank=True)

    class Meta:
        model = CustomUser
        fields = ['phone_number', 'password', 'password_confirm', 'full_name', 'verification_code']

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "رمزهای عبور مطابقت ندارند."})

        from .sms_hook import verify_registration_code
        if not verify_registration_code(attrs['phone_number'], attrs['verification_code']):
            raise serializers.ValidationError(
                {"verification_code": "کد تایید نامعتبر یا منقضی است."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        validated_data.pop('verification_code')
        full_name = validated_data.pop('full_name', '')
        user = CustomUser.objects.create_user(
            phone_number=validated_data['phone_number'],
            password=validated_data['password'],
            account_type=CustomUser.ACCOUNT_TYPE_PERSONAL,
        )
        if full_name:
            user.first_name = full_name
            user.save(update_fields=['first_name'])
        return user




class LoginSerializer(serializers.Serializer):
    """سریالایزر ورود"""
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')

        if phone_number and password:
            user = authenticate(username=phone_number, password=password)
            if not user:
                raise serializers.ValidationError('شماره تلفن یا رمز عبور اشتباه است.')
        else:
            raise serializers.ValidationError('شماره تلفن و رمز عبور الزامی است.')

        attrs['user'] = user
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    """درخواست کد بازیابی رمز عبور (مرحله اول — ارسال پیامک)"""
    phone_number = serializers.CharField(max_length=11)


class PasswordResetConfirmSerializer(serializers.Serializer):
    """تایید کد بازیابی و تعیین رمز جدید (مرحله دوم)"""
    phone_number = serializers.CharField(max_length=11)
    code = serializers.CharField(min_length=4, max_length=4)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({"new_password": "رمزهای عبور مطابقت ندارند."})
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    """سریالایزر تغییر رمز عبور کاربر لاگین‌شده (با تایید رمز فعلی)"""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({"new_password": "رمزهای عبور مطابقت ندارند."})

        user = self.context['request'].user
        if not user.check_password(attrs['old_password']):
            raise serializers.ValidationError({"old_password": "رمز عبور فعلی اشتباه است."})

        if attrs['old_password'] == attrs['new_password']:
            raise serializers.ValidationError({"new_password": "رمز عبور جدید نباید با رمز فعلی یکسان باشد."})

        return attrs


class UserSerializer(serializers.ModelSerializer):
    """سریالایزر نمایش اطلاعات کاربر"""
    token_balance = serializers.SerializerMethodField()
    real_token_balance = serializers.SerializerMethodField()
    ai_free_left = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id', 'phone_number', 'gym_name', 'token_balance', 'account_type',
                  'real_token_balance', 'ai_free_left']
        read_only_fields = ['id', 'token_balance', 'account_type',
                            'real_token_balance', 'ai_free_left']

    def get_token_balance(self, obj) -> int:
        # عددی که اپ نشان می‌دهد: توکنِ واقعی + ارزشِ برنامه‌های رایگانِ مانده.
        # کسرِ واقعی جای دیگری انجام می‌شود و دست‌نخورده است.
        return obj.display_token_balance()

    def get_real_token_balance(self, obj) -> int:
        return obj.get_effective_token_balance()

    def get_ai_free_left(self, obj) -> int:
        return obj.ai_free_left()


# ==================== Equipment Serializers ====================

class EquipmentCategorySerializer(serializers.ModelSerializer):
    """سریالایزر دسته‌بندی دستگاه‌ها"""
    is_global = serializers.SerializerMethodField(
        help_text='دسته سراسری برای همه مربی‌ها قابل مشاهده اما فقط‌خواندنی است'
    )

    class Meta:
        model = EquipmentCategory
        fields = ['id', 'name', 'description', 'is_global']

    def get_is_global(self, obj) -> bool:
        return obj.owner_id is None


class EquipmentSerializer(serializers.ModelSerializer):
    """سریالایزر دستگاه‌های ورزشی"""
    category_name = serializers.CharField(source='category.name', read_only=True)

    # دستگاه و کاتالوگ یک چیزند؛ اپ باید عکس و نامِ رسمی را ببیند
    image_url = serializers.SerializerMethodField()
    catalog_name = serializers.CharField(source='catalog.name', read_only=True)

    class Meta:
        model = Equipment
        fields = ['id', 'name', 'description', 'category', 'category_name',
                  'muscle_group', 'image', 'image_url', 'catalog', 'catalog_name',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'catalog', 'catalog_name', 'image_url',
                            'created_at', 'updated_at']

    def get_image_url(self, obj):
        url = obj.display_image_url()
        request = self.context.get('request')
        if url and request is not None:
            return request.build_absolute_uri(url)
        return url

    def validate_category(self, category):
        # دسته باید سراسری یا متعلق به خود مربی باشد — نه دسته باشگاه دیگر
        request = self.context.get('request')
        if category and category.owner_id and request and category.owner_id != request.user.id:
            raise serializers.ValidationError('دسته‌بندی انتخابی معتبر نیست.')
        return category

    def create(self, validated_data):
        # افزودن کاربر فعلی به دستگاه
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


# ==================== Meal Serializers ====================

class MealSerializer(serializers.ModelSerializer):
    """سریالایزر غذاها"""
    class Meta:
        model = Meal
        fields = ['id', 'name', 'description', 'calories', 'protein', 'carbs', 'fat', 'allergens', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def create(self, validated_data):
        # افزودن کاربر فعلی به غذا
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


# ==================== Program Serializers ====================

class ClientProgramSerializer(serializers.ModelSerializer):
    """سریالایزر برنامه مشتری"""
    class Meta:
        model = ClientProgram
        fields = [
            'id', 'name', 'age', 'gender', 'height', 'weight',
            'injuries', 'food_allergies', 'body_issues', 'chronic_diseases',
            'extra_notes', 'exercise_history', 'program_days', 'program_type',
            'training_place', 'generated_workout', 'generated_meal_plan',
            'tokens_consumed', 'source', 'gym_client', 'created_at', 'updated_at'
        ]
        # source و gym_client را سرور تعیین می‌کند؛ اپ فقط می‌خواند تا بفهمد
        # این برنامه را هوش مصنوعی ساخته یا خودِ مربی نوشته است.
        read_only_fields = ['id', 'generated_workout', 'generated_meal_plan', 'tokens_consumed',
                            'source', 'gym_client', 'created_at', 'updated_at']











class GenerateProgramSerializer(serializers.Serializer):
    """سریالایزر درخواست تولید برنامه"""
    name = serializers.CharField(max_length=100)
    age = serializers.IntegerField(required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=ClientProgram.GENDER_CHOICES, required=False, allow_null=True
    )
    height = serializers.FloatField(required=False, allow_null=True)
    weight = serializers.FloatField(required=False, allow_null=True)
    injuries = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    food_allergies = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    body_issues = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    chronic_diseases = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    extra_notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    exercise_history = serializers.CharField(
        required=False, 
        allow_blank=True, 
        allow_null=True,
        help_text='توضیحات کامل درباره سابقه ورزشی کاربر'
    )
    program_days = serializers.IntegerField(min_value=1, max_value=7, default=7)
    training_place = serializers.ChoiceField(
        choices=[c[0] for c in ClientProgram.TRAINING_PLACE_CHOICES],
        required=False,
        help_text=('محیط تمرین. برای باشگاه: gym_equipment (پیش‌فرض، از تجهیزات ثبت‌شده). '
                   'برای کاربر شخصی: public_gym / home_basic / home_none')
    )
    program_type = serializers.ChoiceField(
        choices=ClientProgram.PROGRAM_TYPE_CHOICES,
        default='both',
        required=False,
        help_text='نوع برنامه: both(هر دو - 50 توکن), workout(فقط ورزشی - 25 توکن), meal(فقط غذایی - 25 توکن)'
    )
    generate_pdf = serializers.BooleanField(default=False)
    pdf_type = serializers.ChoiceField(
        choices=ClientProgram.PROGRAM_TYPE_CHOICES,
        default='both',
        required=False,
        help_text='نوع PDF: both(هر دو), workout(ورزشی), meal(غذایی)'
    )




class EditProgramSerializer(serializers.Serializer):
    """سریالایزر ویرایش برنامه با بازخورد"""
    feedback = serializers.CharField()
    generate_pdf = serializers.BooleanField(default=False)
    pdf_type = serializers.ChoiceField(
        choices=ClientProgram.PROGRAM_TYPE_CHOICES,
        default='both',
        required=False,
        help_text='نوع PDF: both(هر دو), workout(ورزشی), meal(غذایی)'
    )




class ProgramHistorySerializer(serializers.ModelSerializer):
    """سریالایزر تاریخچه برنامه‌ها"""
    user_phone = serializers.CharField(source='user.phone_number', read_only=True)

    class Meta:
        model = ClientProgram
        fields = ['id', 'user_id', 'name', 'user_phone', 'exercise_history', 'created_at', 'program_days', 'program_type']
        read_only_fields = fields


# ==================== Token Package Serializers ====================

class TokenPackageSerializer(serializers.ModelSerializer):
    """سریالایزر بسته‌های توکن"""
    calculated_price = serializers.SerializerMethodField()

    class Meta:
        model = TokenPackage
        fields = ['id', 'name', 'token_amount', 'price_per_50_tokens', 'calculated_price', 'is_active']
        read_only_fields = ['id']

    def get_calculated_price(self, obj) -> float:
        """محاسبه قیمت بسته"""
        return float(obj.calculate_price())


class PurchaseTokenSerializer(serializers.Serializer):
    """سریالایزر خرید توکن"""
    token_amount = serializers.IntegerField(min_value=50)
    package_id = serializers.IntegerField(required=False)
    discount_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(
        choices=TokenPurchase.PAYMENT_METHOD_CHOICES,
        required=False,
        default=TokenPurchase.METHOD_GATEWAY,
        help_text='gateway = درگاه آنلاین | card = کارت به کارت',
    )

    def validate_token_amount(self, value):
        if value % 50 != 0:
            raise serializers.ValidationError('تعداد توکن باید مضربی از 50 باشد.')
        return value


# ==================== Card Payment Serializers ====================

class CardPaymentAccountSerializer(serializers.ModelSerializer):
    """اطلاعات کارت مقصد که به کاربر نمایش داده می‌شود."""
    formatted_card_number = serializers.CharField(read_only=True)

    class Meta:
        model = CardPaymentAccount
        fields = [
            'id', 'title', 'card_number', 'formatted_card_number',
            'card_holder', 'bank_name', 'sheba', 'instructions',
        ]
        read_only_fields = fields


class UploadReceiptSerializer(serializers.Serializer):
    """بارگذاری رسید پرداخت کارت‌به‌کارت."""
    receipt_image = serializers.ImageField(
        required=True,
        help_text='تصویر رسید واریز (اسکرین‌شات یا عکس)',
    )
    receipt_reference = serializers.CharField(
        max_length=100, required=False, allow_blank=True,
        help_text='شماره پیگیری واریز',
    )
    receipt_note = serializers.CharField(
        max_length=500, required=False, allow_blank=True,
    )


class TokenPurchaseStatusSerializer(serializers.ModelSerializer):
    """وضعیت یک سفارش برای نمایش در پنل کاربر."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_display = serializers.CharField(
        source='get_payment_method_display', read_only=True
    )
    card_account = CardPaymentAccountSerializer(read_only=True)
    has_receipt = serializers.SerializerMethodField()

    class Meta:
        model = TokenPurchase
        fields = [
            'id', 'token_amount', 'original_price', 'discount_amount', 'final_price',
            'status', 'status_display', 'payment_method', 'payment_method_display',
            'card_account', 'has_receipt', 'receipt_reference', 'receipt_uploaded_at',
            'review_note', 'created_at',
        ]
        read_only_fields = fields

    def get_has_receipt(self, obj) -> bool:
        return bool(obj.receipt_image)


# ==================== Discount Code Serializers ====================

class DiscountCodeSerializer(serializers.ModelSerializer):
    """سریالایزر کد تخفیف"""
    creator_phone = serializers.CharField(source='creator.phone_number', read_only=True)

    class Meta:
        model = DiscountCode
        fields = [
            'id', 'code', 'discount_percent', 'is_active', 'single_use_per_user',
            'creator', 'creator_phone', 'commission_percent', 'used_count', 'created_at'
        ]
        read_only_fields = ['id', 'used_count', 'created_at']


class ValidateDiscountCodeSerializer(serializers.Serializer):
    """سریالایزر اعتبارسنجی کد تخفیف"""
    code = serializers.CharField(max_length=50)
    purchase_amount = serializers.DecimalField(max_digits=10, decimal_places=2)


# ==================== Gym Brand Serializers ====================

class GymBrandSerializer(serializers.ModelSerializer):
    """سریالایزر برندسازی باشگاه"""

    class Meta:
        model = GymBrand
        fields = [
            'id', 'gym_name', 'logo', 'primary_color', 'secondary_color',
            'accent_color', 'description', 'program_instructions', 'address',
            'phone', 'email', 'instagram', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CoachInstructionSerializer(serializers.Serializer):
    """دستورالعمل ثابت مربی که در تولید هر برنامه رعایت می‌شود"""
    program_instructions = serializers.CharField(
        required=True, allow_blank=True, max_length=4000,
        help_text='برای پاک‌کردن دستورالعمل، رشته خالی بفرستید.'
    )


# ==================== Gym Client Serializers ====================

class GymBrandSummarySerializer(serializers.Serializer):
    """شکل برند باشگاه آن‌طور که داخل پاسخ مشتری برمی‌گردد.

    فقط برای مستندسازی Swagger است؛ جایی برای خواندن/نوشتن استفاده نمی‌شود.
    بدون آن، این فیلد در مستندات «string» دیده می‌شود و فرانت اشتباه می‌خواند.
    """
    gym_name = serializers.CharField()
    logo = serializers.CharField(allow_null=True)
    primary_color = serializers.CharField()
    secondary_color = serializers.CharField()
    accent_color = serializers.CharField()


class GymClientSerializer(serializers.ModelSerializer):
    """سریالایزر مشتری باشگاه"""
    gym_owner_name = serializers.CharField(source='gym_owner.gym_name', read_only=True)
    gym_brand = serializers.SerializerMethodField()
    client_token_balance = serializers.SerializerMethodField()
    access_code_is_expired = serializers.BooleanField(read_only=True)
    access_code_is_permanent = serializers.BooleanField(
        read_only=True,
        help_text='true یعنی کد دائمی است و تایمری ندارد.'
    )
    access_code_remaining_seconds = serializers.IntegerField(
        read_only=True,
        help_text='شمارش معکوس اعتبار کد به ثانیه (مثل تایمر کد پیامکی). '
                  'null = کد دائمی، 0 = منقضی شده.'
    )
    access_code_validity_days = serializers.IntegerField(
        write_only=True, required=False, allow_null=True, min_value=0,
        help_text='مدت اعتبار کد دسترسی به روز از همین لحظه. '
                  'ارسال‌نکردن/خالی = کد دائمی (بدون تغییر). مقدار 0 = تبدیل به کد دائمی.'
    )
    access_code_validity_minutes = serializers.IntegerField(
        write_only=True, required=False, allow_null=True, min_value=0,
        help_text='مدت اعتبار کد به دقیقه — برای کدهای کوتاه‌مدت (مثلاً 10 دقیقه). '
                  'اگر همراه access_code_validity_days بیاید، با هم جمع می‌شوند.'
    )

    class Meta:
        model = GymClient
        fields = [
            'id', 'gym_owner', 'gym_owner_name', 'access_code',
            'access_code_expires_at', 'access_code_is_expired', 'access_code_is_permanent',
            'access_code_remaining_seconds',
            'access_code_validity_days', 'access_code_validity_minutes',
            'is_used', 'client_user', 'name', 'age', 'gender', 'height', 'weight',
            'goal', 'injuries', 'food_allergies', 'gym_brand', 'pending_tokens', 'client_token_balance', 'created_at'
        ]
        read_only_fields = [
            'id', 'gym_owner', 'access_code', 'access_code_expires_at',
            'is_used', 'pending_tokens', 'created_at'
        ]

    def _apply_validity(self, instance, days, minutes):
        instance.set_access_code_validity(days=days or 0, minutes=minutes or 0)
        instance.save(update_fields=['access_code_expires_at', 'updated_at'])

    def create(self, validated_data):
        validity_days = validated_data.pop('access_code_validity_days', None)
        validity_minutes = validated_data.pop('access_code_validity_minutes', None)
        instance = super().create(validated_data)
        if validity_days or validity_minutes:
            self._apply_validity(instance, validity_days, validity_minutes)
        return instance

    def update(self, instance, validated_data):
        validity_days = validated_data.pop('access_code_validity_days', None)
        validity_minutes = validated_data.pop('access_code_validity_minutes', None)
        instance = super().update(instance, validated_data)
        if validity_days is not None or validity_minutes is not None:
            self._apply_validity(instance, validity_days, validity_minutes)
        return instance

    @extend_schema_field(GymBrandSummarySerializer(allow_null=True))
    def get_gym_brand(self, obj):
        """دریافت اطلاعات برند باشگاه"""
        try:
            brand = obj.gym_owner.gym_brand
            return {
                'gym_name': brand.gym_name,
                'logo': brand.logo.url if brand.logo else None,
                'primary_color': brand.primary_color,
                'secondary_color': brand.secondary_color,
                'accent_color': brand.accent_color,
            }
        except GymBrand.DoesNotExist:
            return None

    def get_client_token_balance(self, obj) -> int:
        if obj.client_user:
            return obj.client_user.token_balance
        return obj.pending_tokens


class ClientAccessCodeSerializer(serializers.Serializer):
    """سریالایزر ورود مشتری با کد دسترسی"""
    # کدهای جدید از 6 رقم شروع می‌شوند؛ min_length=4 برای سازگاری با کدهای قدیمی است
    access_code = serializers.CharField(min_length=4, max_length=20)


class ClientUpdateInfoSerializer(serializers.Serializer):
    """سریالایزر آپدیت اطلاعات مشتری"""
    name = serializers.CharField(max_length=100)
    age = serializers.IntegerField(required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=ClientProgram.GENDER_CHOICES, required=False, allow_null=True
    )
    height = serializers.FloatField(required=False, allow_null=True)
    weight = serializers.FloatField(required=False, allow_null=True)
    goal = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    injuries = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    food_allergies = serializers.CharField(required=False, allow_blank=True, allow_null=True)


# ==================== Token Request Serializers ====================

class TokenRequestSerializer(serializers.ModelSerializer):
    """سریالایزر درخواست توکن"""
    client_name = serializers.CharField(source='client.name', read_only=True)
    gym_owner_name = serializers.CharField(source='gym_owner.gym_name', read_only=True)

    class Meta:
        model = TokenRequest
        fields = [
            'id', 'client', 'client_name', 'gym_owner', 'gym_owner_name',
            'requested_tokens', 'status', 'message', 'response_message',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'client', 'client_name', 'gym_owner', 'gym_owner_name',
            'status', 'response_message', 'created_at', 'updated_at'
        ]


class TokenRequestResponseSerializer(serializers.Serializer):
    """سریالایزر پاسخ به درخواست توکن"""
    response_message = serializers.CharField(required=False, allow_blank=True)
    action = serializers.ChoiceField(choices=['approve', 'reject'])


class AdjustClientTokensSerializer(serializers.Serializer):
    """سریالایزر تنظیم توکن مشتری توسط مربی"""
    amount = serializers.IntegerField(
        help_text='مثبت: انتقال توکن از مربی به مشتری | منفی: بازگشت توکن از مشتری به مربی'
    )

    def validate_amount(self, value):
        if value == 0:
            raise serializers.ValidationError('مقدار توکن نمی‌تواند صفر باشد.')
        return value


# ==================== Homepage & Content Serializers ====================

class HomePageSerializer(serializers.ModelSerializer):
    """سریالایزر صفحه اصلی"""
    class Meta:
        model = HomePage
        fields = ['id', 'title', 'subtitle', 'hero_image', 'description', 'app_download_link', 'web_app_link']


class BlogPostSerializer(serializers.ModelSerializer):
    """سریالایزر پست وبلاگ"""
    author_name = serializers.CharField(source='author.gym_name', read_only=True)

    class Meta:
        model = BlogPost
        fields = ['id', 'title', 'slug', 'author', 'author_name', 'image', 'summary', 'content', 'created_at']
        read_only_fields = ['id', 'created_at']


class ContactMessageSerializer(serializers.ModelSerializer):
    """سریالایزر پیام تماس"""
    class Meta:
        model = ContactMessage
        fields = ['id', 'name', 'email', 'phone', 'subject', 'message', 'created_at']
        read_only_fields = ['id', 'created_at']


class TeamMemberSerializer(serializers.ModelSerializer):
    """سریالایزر اعضای تیم"""
    class Meta:
        model = TeamMember
        fields = ['id', 'name', 'role', 'photo', 'icon', 'bio', 'linkedin', 'email', 'order']


class FeatureSerializer(serializers.ModelSerializer):
    """سریالایزر امکانات"""
    class Meta:
        model = Feature
        fields = ['id', 'title', 'description', 'icon', 'image', 'order']













# ==================== کد دانلود برنامه ====================

class ProgramShareCodeSerializer(serializers.ModelSerializer):
    """نمایش کد دانلود به مربی."""
    program_name = serializers.CharField(source='program.name', read_only=True)
    program_created_at = serializers.DateTimeField(
        source='program.created_at', read_only=True
    )
    is_redeemable = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProgramShareCode
        fields = [
            'id', 'code', 'program', 'program_name', 'program_created_at',
            'section', 'expires_at', 'is_used', 'used_at', 'is_expired',
            'is_redeemable', 'created_at',
        ]
        read_only_fields = [
            'id', 'code', 'is_used', 'used_at', 'created_at',
            'program_name', 'program_created_at', 'is_expired', 'is_redeemable',
        ]


class CreateProgramShareCodeSerializer(serializers.Serializer):
    """درخواست ساخت کد دانلود برای یک برنامه."""
    section = serializers.ChoiceField(
        choices=ProgramShareCode.SECTION_CHOICES, default='both', required=False
    )
    expires_in_hours = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=24 * 365,
        help_text='خالی = بدون انقضای زمانی. کد در هر حال یک‌بارمصرف است.'
    )


class RedeemProgramCodeSerializer(serializers.Serializer):
    """مصرف کد دانلود از سمت ورزشکار."""
    code = serializers.CharField(max_length=20)

class PaymentCallbackSerializer(serializers.Serializer):
    """بدنه‌ی کال‌بک درگاه پرداخت.

    فقط برای مستندسازی است؛ ویو خودش مقادیر را با حروف بزرگ/کوچک مختلف
    (Authority/authority) می‌خواند، چون هر درگاه نام‌گذاری خودش را دارد.
    محتوای این بدنه به‌تنهایی قابل اعتماد نیست — تایید نهایی با verify
    مستقیم از خود درگاه انجام می‌شود.
    """
    authority = serializers.CharField(
        required=False, help_text='شناسه تراکنش درگاه (Authority)'
    )
    status = serializers.CharField(
        required=False, help_text='OK یا NOK'
    )
    order_id = serializers.CharField(
        required=False, help_text='شماره سفارش — برای درگاه‌هایی مثل آیدی‌پی'
    )
















