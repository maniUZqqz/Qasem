from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    # Required, and unique. Django's User.email is optional and non-unique by
    # default, which quietly breaks the only way back into an account: a person
    # who signs up without an address can never reset a forgotten password, and
    # two accounts sharing one address make "send the reset link" ambiguous.
    email = serializers.EmailField(
        required=True,
        allow_blank=False,
        error_messages={
            "required": "ایمیل لازم است — تنها راه بازیابی رمز فراموش‌شده همین است.",
            "blank": "ایمیل لازم است — تنها راه بازیابی رمز فراموش‌شده همین است.",
        },
    )

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]

    def validate_email(self, value):
        value = value.strip()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "با این ایمیل قبلاً حسابی ساخته شده. وارد شوید، "
                "یا اگر رمز را یادتان نیست از «رمزم را فراموش کردم» استفاده کنید."
            )
        return value

    def validate(self, attrs):
        # pass a transient user so similarity validation (password ≈ username) works
        candidate = User(username=attrs.get("username", ""), email=attrs.get("email", ""))
        validate_password(attrs["password"], user=candidate)
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email", ""),
            password=validated_data["password"],
        )


class UserSerializer(serializers.ModelSerializer):
    """What the panel is told about whoever is logged in.

    `is_staff` is here because without it the front end has no way to know an
    admin is an admin — which is exactly why the CRM, the marketing report and
    the reward queue had endpoints, permissions and tests but no page anywhere
    in the product. Three staff tools were built and were reachable only by
    someone typing the URL into curl.

    Read-only, and it grants nothing: every staff endpoint re-checks
    `IsAdminUser` server-side. This flag only decides whether a menu entry is
    drawn.
    """

    class Meta:
        model = User
        fields = ["id", "username", "email", "date_joined", "is_staff"]
        read_only_fields = ["is_staff"]
