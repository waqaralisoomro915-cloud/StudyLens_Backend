from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from accounts.views import AuthView, ProfileView, csrf
from common.views import (
    CourseViewSet,
    TopicViewSet,
    DocumentViewSet,
    MappingViewSet,
    ChatViewSet,
    QuizViewSet,
    AttemptViewSet,
    ExamViewSet,
    PlanViewSet,
    SessionViewSet,
    MemoryViewSet,
    NotificationViewSet,
    FeedbackViewSet,
    ExportViewSet,
)

router = DefaultRouter()
for name, view in [
    ("courses", CourseViewSet),
    ("topics", TopicViewSet),
    ("documents", DocumentViewSet),
    ("mappings", MappingViewSet),
    ("chats", ChatViewSet),
    ("quizzes", QuizViewSet),
    ("attempts", AttemptViewSet),
    ("exams", ExamViewSet),
    ("plans", PlanViewSet),
    ("sessions", SessionViewSet),
    ("memory", MemoryViewSet),
    ("notifications", NotificationViewSet),
    ("feedback", FeedbackViewSet),
    ("exports", ExportViewSet),
]:
    router.register(name, view, basename=name)
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", lambda r: JsonResponse({"status": "ok"})),
    path("api/auth/csrf/", csrf),
    path("api/auth/<str:action>/", AuthView.as_view()),
    path("api/profile/", ProfileView.as_view()),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    path("api/", include(router.urls)),
]
