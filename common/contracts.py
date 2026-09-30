from rest_framework import serializers


class DetailResponse(serializers.Serializer):
    detail = serializers.CharField()


class CSRFResponse(serializers.Serializer):
    csrfToken = serializers.CharField()


class AuthRequest(serializers.Serializer):
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    password = serializers.CharField(required=False, write_only=True)
    uid = serializers.CharField(required=False)
    token = serializers.CharField(required=False)


class AuthResponse(serializers.Serializer):
    username = serializers.CharField(required=False)
    csrfToken = serializers.CharField(required=False)
    detail = serializers.CharField(required=False)


class PasswordChangeRequest(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)


class DeleteAccountRequest(serializers.Serializer):
    password = serializers.CharField(write_only=True)


class ProcessRequest(serializers.Serializer):
    pages = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)


class ReviewRequest(serializers.Serializer):
    page = serializers.IntegerField()
    text = serializers.CharField(allow_blank=True)


class AskRequest(serializers.Serializer):
    question = serializers.CharField(max_length=3000)


class SubmitRequest(serializers.Serializer):
    answers = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=3))


class PlanRequest(serializers.Serializer):
    reason = serializers.CharField(required=False)


class SessionStateRequest(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "started", "completed", "skipped"], required=False)
    actual_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)
    locked = serializers.BooleanField(required=False)


class RescheduleRequest(serializers.Serializer):
    starts_at = serializers.DateTimeField()


class MasterySummary(serializers.Serializer):
    score = serializers.FloatField()
    answered = serializers.IntegerField()
    state = serializers.CharField()
    method = serializers.CharField()


class MappingSummary(serializers.Serializer):
    id = serializers.IntegerField()
    page = serializers.IntegerField()
    page__document = serializers.IntegerField()
    page__number = serializers.IntegerField()
    reason = serializers.CharField()
    confirmed = serializers.BooleanField()
    score = serializers.FloatField()


class CoverageResponse(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    coverage = serializers.ChoiceField(choices=["covered", "partial", "missing"])
    estimated_minutes = serializers.IntegerField()
    estimate = serializers.BooleanField()
    mastery = MasterySummary()
    mappings = MappingSummary(many=True)
