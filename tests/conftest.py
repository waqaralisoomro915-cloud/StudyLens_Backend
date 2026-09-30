import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from accounts.models import Profile
from courses.models import Course, Topic


@pytest.fixture
def student(db):
    user = User.objects.create_user("alice", "alice@example.com", "Long-password-390!")
    Profile.objects.create(user=user, availability=[{"day": d, "start": "08:00", "end": "20:00"} for d in range(7)])
    return user


@pytest.fixture
def client(student):
    client = APIClient()
    client.force_authenticate(student)
    return client


@pytest.fixture
def course(student):
    return Course.objects.create(owner=student, title="Database Systems", code="CS402")


@pytest.fixture
def topic(student, course):
    return Topic.objects.create(owner=student, course=course, title="Database normalization", estimated_minutes=90)


@pytest.fixture(autouse=True)
def private_files(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "private"
