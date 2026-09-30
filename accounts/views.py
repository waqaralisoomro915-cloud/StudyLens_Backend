from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Profile
from drf_spectacular.utils import extend_schema, extend_schema_view
from common.contracts import (
    CSRFResponse,
    AuthRequest,
    AuthResponse,
    PasswordChangeRequest,
    DeleteAccountRequest,
    DetailResponse,
)


@extend_schema(responses=CSRFResponse)
@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(request):
    return Response({"csrfToken": get_token(request)})


class Credentials(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    email = serializers.EmailField(required=False)


@method_decorator(csrf_protect, name="dispatch")
class AuthView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=AuthRequest, responses=AuthResponse)
    def post(self, request, action):
        if action in ("register", "login"):
            data = Credentials(data=request.data)
            data.is_valid(raise_exception=True)
            values = data.validated_data
            if action == "register":
                if not values.get("email"):
                    raise serializers.ValidationError({"email": "Email is required."})
                if User.objects.filter(username=values["username"]).exists():
                    raise serializers.ValidationError({"username": "This username is taken."})
                if User.objects.filter(email__iexact=values["email"]).exists():
                    raise serializers.ValidationError({"email": "Unable to register with this email."})
                user = User(username=values["username"], email=values["email"])
                try:
                    validate_password(values["password"], user)
                except DjangoValidationError as e:
                    raise serializers.ValidationError({"password": e.messages})
                with transaction.atomic():
                    user.set_password(values["password"])
                    user.save()
                    Profile.objects.create(user=user)
            else:
                user = authenticate(request, username=values["username"], password=values["password"])
                if user is None:
                    raise serializers.ValidationError("Invalid username or password.")
            login(request, user)
            return Response({"username": user.username, "csrfToken": get_token(request)})
        if action == "logout":
            logout(request)
            return Response({"detail": "Signed out."})
        if action == "forgot-password":
            email = serializers.EmailField().run_validation(request.data.get("email"))
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                send_mail(
                    "Reset your StudyLens password",
                    f"{settings.FRONTEND_URL}/reset/{uid}/{token}",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                )
            return Response({"detail": "If this account exists, a reset link has been sent."})
        if action == "reset-password":
            try:
                user = User.objects.get(pk=force_str(urlsafe_base64_decode(request.data.get("uid", ""))))
            except (User.DoesNotExist, ValueError, TypeError, UnicodeDecodeError):
                raise serializers.ValidationError("Invalid reset link.")
            if not default_token_generator.check_token(user, request.data.get("token", "")):
                raise serializers.ValidationError("Invalid or expired reset link.")
            password = serializers.CharField(max_length=128, trim_whitespace=False).run_validation(
                request.data.get("password")
            )
            try:
                validate_password(password, user)
            except DjangoValidationError as e:
                raise serializers.ValidationError(e.messages)
            user.set_password(password)
            user.save()
            return Response({"detail": "Password reset. You can sign in."})
        return Response({"detail": "Unknown action."}, status=404)


class ProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Profile
        exclude = ["user"]

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise serializers.ValidationError("Use an IANA timezone, for example Asia/Kolkata.")
        return value

    def validate(self, data):
        limits = {"daily_limit": (15, 720), "session_minutes": (15, 120), "break_minutes": (0, 60)}
        for name, (low, high) in limits.items():
            if name in data and not low <= data[name] <= high:
                raise serializers.ValidationError({name: f"Must be between {low} and {high}."})
        if "availability" in data and (not isinstance(data["availability"], list) or len(data["availability"]) > 28):
            raise serializers.ValidationError({"availability": "Provide at most 28 weekly time windows."})
        for window in data.get("availability", []):
            try:
                from datetime import time

                if not isinstance(window["day"], int) or not 0 <= window["day"] <= 6:
                    raise ValueError()
                if time.fromisoformat(window["start"]) >= time.fromisoformat(window["end"]):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise serializers.ValidationError(
                    {"availability": "Use {day: 0..6, start: HH:MM, end: HH:MM}; no overnight windows."}
                )
        return data


@extend_schema_view(
    get=extend_schema(responses=ProfileSerializer),
    patch=extend_schema(request=ProfileSerializer, responses=ProfileSerializer),
    post=extend_schema(request=PasswordChangeRequest, responses=DetailResponse),
    delete=extend_schema(request=DeleteAccountRequest, responses={204: None}),
)
class ProfileView(APIView):
    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(ProfileSerializer(profile).data)

    def patch(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        from planning.services import propose_if_needed

        propose_if_needed(request.user, "Study preferences changed")
        return Response(serializer.data)

    def delete(self, request):
        if not request.user.check_password(request.data.get("password", "")):
            raise serializers.ValidationError("Enter your current password to delete your account.")
        request.user.delete()
        logout(request)
        return Response(status=204)

    def post(self, request):
        if not request.user.check_password(request.data.get("current_password", "")):
            raise serializers.ValidationError("Current password is incorrect.")
        password = serializers.CharField(max_length=128, trim_whitespace=False).run_validation(
            request.data.get("password")
        )
        try:
            validate_password(password, request.user)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        request.user.set_password(password)
        request.user.save()
        update_session_auth_hash(request, request.user)
        return Response({"detail": "Password changed."})
