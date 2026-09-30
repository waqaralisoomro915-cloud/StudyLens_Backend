from datetime import timedelta
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from common.api import OwnedViewSet, serializer_for
from accounts.models import MemoryItem, Profile
from courses.models import Course, Topic
from documents.models import Document, DocumentPage, TopicMapping
from tutoring.models import ChatSession, ChatMessage
from quizzes.models import Quiz, Attempt
from mastery.models import TopicMastery
from exams.models import Exam
from planning.models import Plan, PlannedSession
from notifications.models import Notification
from exports.models import ExportJob
from feedback.models import Feedback
from ai.client import AIError
from drf_spectacular.utils import extend_schema, OpenApiTypes
from common.contracts import (
    DetailResponse,
    ProcessRequest,
    ReviewRequest,
    AskRequest,
    SubmitRequest,
    PlanRequest,
    SessionStateRequest,
    RescheduleRequest,
    CoverageResponse,
)


def dispatch(task, model, instance):
    def send():
        try:
            task.delay(instance.pk, instance.owner_id)
        except Exception:
            model.objects.filter(pk=instance.pk).update(
                status="failed", error="Worker queue unavailable. Start Redis and the worker, then retry."
            )

    transaction.on_commit(send)


class CourseSuggestionRequest(serializers.Serializer):
    text = serializers.CharField(max_length=2000)


class CourseSuggestionResponse(serializers.Serializer):
    course = serializers.IntegerField()
    title = serializers.CharField()
    evidence = serializers.ListField(child=serializers.CharField())


class CourseViewSet(OwnedViewSet):
    queryset = Course.objects.all()
    serializer_class = serializer_for(Course)

    @extend_schema(request=CourseSuggestionRequest, responses=CourseSuggestionResponse(many=True))
    @action(detail=False, methods=["post"])
    def suggest(self, request):
        from courses.services.suggestions import suggest_courses

        payload = CourseSuggestionRequest(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response(suggest_courses(request.user, payload.validated_data["text"]))

    @extend_schema(responses=CoverageResponse(many=True))
    @action(detail=True, methods=["get"])
    def coverage(self, request, pk=None):
        course = self.get_object()
        rows = []
        from mastery.services import summary

        for topic in course.topics.all():
            mappings = TopicMapping.objects.filter(topic=topic, page__document__confirmed=True)
            state = (
                "covered" if mappings.filter(confirmed=True).exists() else "partial" if mappings.exists() else "missing"
            )
            rows.append(
                {
                    "id": topic.pk,
                    "title": topic.title,
                    "coverage": state,
                    "estimated_minutes": topic.estimated_minutes,
                    "estimate": not topic.estimate_override,
                    "mastery": summary(TopicMastery.objects.filter(topic=topic).first()),
                    "mappings": list(
                        mappings.values("id", "page", "page__document", "page__number", "reason", "confirmed", "score")
                    ),
                }
            )
        return Response(rows)


class TopicSerializer(serializer_for(Topic)):
    def validate(self, data):
        if not 15 <= data.get("estimated_minutes", 90) <= 3000 or not 1 <= data.get("difficulty", 3) <= 5:
            raise ValidationError("Use 15–3000 minutes and difficulty 1–5.")
        if self.instance and "course" in data and data["course"] != self.instance.course:
            raise ValidationError("Create a new topic to change courses.")
        return data


class TopicViewSet(OwnedViewSet):
    queryset = Topic.objects.all()
    serializer_class = TopicSerializer

    def perform_create(self, serializer):
        topic = serializer.save(owner=self.request.user)
        from documents.services import remap

        remap(topic.course)

    def perform_update(self, serializer):
        topic = serializer.save()
        from documents.services import remap

        remap(topic.course)


class PageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentPage
        fields = ["id", "number", "text", "confidence", "warning"]


class DocumentSerializer(serializer_for(Document, ("status", "error", "confirmed", "generation"))):
    file = serializers.FileField(write_only=True)
    pages = PageSerializer(many=True, read_only=True)

    def validate_file(self, value):
        from documents.services import validate_upload

        return validate_upload(value)

    def validate(self, data):
        if self.instance and any(k in data for k in ("file", "course", "kind")):
            raise ValidationError("File, course and kind cannot change. Delete and upload a new document.")
        return data


class DocumentViewSet(OwnedViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

    @extend_schema(request=ProcessRequest, responses=DocumentSerializer)
    @action(detail=True, methods=["post"])
    def process(self, request, pk=None):
        document = self.get_object()
        from documents.tasks import enqueue

        page_numbers = request.data.get("pages")
        if page_numbers is not None:
            if (
                not isinstance(page_numbers, list)
                or not page_numbers
                or any(type(n) is not int for n in page_numbers)
                or not set(page_numbers).issubset(set(document.pages.values_list("number", flat=True)))
            ):
                raise ValidationError("Select existing page numbers to reprocess.")
        enqueue(document, page_numbers)
        document.refresh_from_db()
        return Response(self.get_serializer(document).data)

    @extend_schema(request=ReviewRequest, responses=PageSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def review(self, request, pk=None):
        document = Document.objects.select_for_update().get(pk=self.get_object().pk)
        if document.status in ("queued", "processing"):
            raise ValidationError("Wait for processing to finish.")
        page = document.pages.filter(pk=request.data.get("page")).first()
        if not page:
            raise ValidationError("Page not found in this document.")
        page.text = serializers.CharField(max_length=100000, allow_blank=True).run_validation(request.data.get("text"))
        page.warning = "Manually corrected; confirm the document when review is complete."
        page.save()
        from documents.services import invalidate

        invalidate(document)
        return Response(PageSerializer(page).data)

    @extend_schema(request=None, responses=DocumentSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def confirm(self, request, pk=None):
        document = Document.objects.select_for_update().get(pk=self.get_object().pk)
        if document.status not in ("review", "ready") or not document.pages.exclude(text="").exists():
            raise ValidationError("Process the document and review readable text before confirming.")
        document.confirmed = True
        document.status = "ready"
        document.save()
        from documents.services import remap

        remap(document.course)
        return Response(self.get_serializer(document).data)

    @extend_schema(responses=OpenApiTypes.BINARY)
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        from documents.downloads import original_download

        return original_download(self.get_object())

    @extend_schema(responses=OpenApiTypes.BINARY)
    @action(detail=True, methods=["get"], url_path="extracted-text")
    def extracted_text(self, request, pk=None):
        from documents.downloads import text_download

        return text_download(self.get_object())

    @extend_schema(request=None, responses=DetailResponse)
    @action(detail=True, methods=["post"])
    def syllabus(self, request, pk=None):
        document = self.get_object()
        if not document.confirmed or document.kind != "syllabus":
            raise ValidationError("Confirm a syllabus document first.")
        from ai.client import generate

        try:
            result = generate(
                'Extract syllabus topics. Return JSON {"topics":[{"title":string,"unit":string,"quote":exact source substring}]}. Do not invent topics.',
                {"pages": list(document.pages.values("number", "text"))},
            )
            topics = result.get("topics")
            text = "\n".join(document.pages.values_list("text", flat=True))
            if not isinstance(topics, list) or not topics or len(topics) > 200:
                raise AIError("Invalid syllabus output.")
            for t in topics:
                if (
                    not isinstance(t, dict)
                    or not isinstance(t.get("title"), str)
                    or not 1 <= len(t["title"]) <= 200
                    or not isinstance(t.get("quote"), str)
                    or len(t["quote"]) < 5
                    or t["quote"] not in text
                ):
                    raise AIError("Unverifiable syllabus topic.")
            with transaction.atomic():
                for t in topics:
                    Topic.objects.get_or_create(
                        owner=request.user,
                        course=document.course,
                        title=t["title"],
                        defaults={"unit": str(t.get("unit", ""))[:200]},
                    )
            from documents.services import remap

            remap(document.course)
            return Response(
                {"detail": f"{len(topics)} topics extracted. Review titles and estimates on the syllabus page."}
            )
        except AIError as e:
            raise ValidationError(str(e))

    @extend_schema(request=None, responses=DetailResponse)
    @action(detail=True, methods=["post"])
    def timetable(self, request, pk=None):
        document = self.get_object()
        if not document.confirmed or document.kind != "timetable":
            raise ValidationError("Confirm a timetable document first.")
        from ai.client import generate
        from django.utils.dateparse import parse_datetime

        try:
            result = generate(
                'Extract exams for the supplied course only. Return JSON {"exams":[{"title":string,"starts_at":ISO8601 with timezone or null,"duration_minutes":integer or null,"quote":exact source substring,"warning":string}]}. Never guess a year or date. Missing or ambiguous dates must be null. All dates require student confirmation.',
                {
                    "course": document.course.title,
                    "timezone": Profile.objects.get(user=request.user).timezone,
                    "pages": list(document.pages.values("number", "text")),
                },
            )
            rows = result.get("exams")
            text = "\n".join(document.pages.values_list("text", flat=True))
            if not isinstance(rows, list) or len(rows) > 50:
                raise AIError("Invalid timetable output.")
            drafts = []
            for row in rows:
                quote = row.get("quote", "")
                if not isinstance(quote, str) or len(quote) < 5 or quote not in text:
                    raise AIError("Unverifiable timetable citation.")
                start = parse_datetime(row["starts_at"]) if row.get("starts_at") else None
                if start and timezone.is_naive(start):
                    start = None
                payload = {
                    "course": document.course_id,
                    "title": row.get("title"),
                    "starts_at": start,
                    "duration_minutes": row.get("duration_minutes"),
                    "source": document.pk,
                    "source_quote": quote,
                    "warning": str(row.get("warning", "")) or "Review extracted date, year, time and timezone.",
                }
                serializer = ExamSerializer(data=payload, context={"request": request})
                serializer.is_valid(raise_exception=True)
                drafts.append(serializer)
            with transaction.atomic():
                for serializer in drafts:
                    if not Exam.objects.filter(
                        owner=request.user, source=document, source_quote=serializer.validated_data["source_quote"]
                    ).exists():
                        serializer.save(owner=request.user)
            return Response({"detail": "Exam drafts saved. Review and explicitly confirm each date."})
        except (AIError, ValueError, TypeError, AttributeError) as e:
            raise ValidationError(str(e))


class MappingViewSet(OwnedViewSet):
    queryset = TopicMapping.objects.all()
    serializer_class = serializer_for(TopicMapping)

    def perform_create(self, serializer):
        topic, page = serializer.validated_data["topic"], serializer.validated_data["page"]
        if topic.course_id != page.document.course_id or not page.document.confirmed:
            raise ValidationError("Select a confirmed page from the same course.")
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        if set(serializer.validated_data) - {"confirmed", "reason"}:
            raise ValidationError("Only confirmation and reason may be edited.")
        serializer.save()


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "text", "citations", "created_at"]


class ChatSerializer(serializer_for(ChatSession)):
    messages = MessageSerializer(many=True, read_only=True)


class ChatViewSet(OwnedViewSet):
    queryset = ChatSession.objects.all()
    serializer_class = ChatSerializer

    @extend_schema(request=AskRequest, responses=MessageSerializer)
    @action(detail=True, methods=["post"])
    def ask(self, request, pk=None):
        question = serializers.CharField(max_length=3000).run_validation(request.data.get("question"))
        from tutoring.services import answer

        try:
            message = answer(self.get_object(), question)
        except AIError as e:
            raise ValidationError(str(e))
        return Response(MessageSerializer(message).data)


class QuizSerializer(serializer_for(Quiz, ("questions", "status", "error"))):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["questions"] = [{k: q[k] for k in ("text", "choices", "topic_id")} for q in instance.questions]
        return data

    def validate(self, data):
        if not 1 <= data.get("length", 5) <= 20 or data.get("difficulty", "medium") not in ("easy", "medium", "hard"):
            raise ValidationError("Select 1–20 questions and easy, medium or hard difficulty.")
        if data.get("topic") and data["topic"].course != data.get("course"):
            raise ValidationError("Topic must belong to the selected course.")
        return data


class QuizViewSet(OwnedViewSet):
    queryset = Quiz.objects.all()
    serializer_class = QuizSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def perform_create(self, serializer):
        quiz = serializer.save(owner=self.request.user)
        from quizzes.tasks import generate_quiz

        dispatch(generate_quiz, Quiz, quiz)

    @extend_schema(request=None, responses=DetailResponse)
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        quiz = self.get_object()
        if quiz.status != "failed":
            raise ValidationError("Only failed quizzes can be retried.")
        quiz.status = "queued"
        quiz.save(update_fields=["status"])
        from quizzes.tasks import generate_quiz

        dispatch(generate_quiz, Quiz, quiz)
        return Response({"detail": "Queued"})

    @extend_schema(request=SubmitRequest, responses=serializer_for(Attempt))
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        from quizzes.services import score

        attempt = score(self.get_object(), request.user, request.data.get("answers"))
        return Response(serializer_for(Attempt)(attempt).data)


class AttemptViewSet(OwnedViewSet):
    queryset = Attempt.objects.all()
    serializer_class = serializer_for(Attempt)
    http_method_names = ["get", "delete", "head", "options"]

    def perform_destroy(self, instance):
        # Recompute evidence after deletion instead of keeping deleted results in mastery.
        course = instance.quiz.course
        instance.delete()
        TopicMastery.objects.filter(owner=self.request.user, topic__course=course).delete()
        for attempt in Attempt.objects.filter(owner=self.request.user, quiz__course=course):
            for result in attempt.results:
                record, _ = TopicMastery.objects.get_or_create(owner=self.request.user, topic_id=result["topic_id"])
                record.answered += 1
                record.correct += int(result["is_correct"])
                record.save()


class ExamSerializer(serializer_for(Exam, ("confirmed",))):
    def validate(self, data):
        course = data.get("course", self.instance.course if self.instance else None)
        topics = data.get("topics", list(self.instance.topics.all()) if self.instance else [])
        all_topics = data.get("all_topics", self.instance.all_topics if self.instance else True)
        if any(topic.course_id != course.pk for topic in topics):
            raise ValidationError({"topics": "Select topics belonging to this exam's course."})
        if not all_topics and not topics:
            raise ValidationError({"topics": "Select at least one topic or choose the whole course."})
        if all_topics:
            data["topics"] = []
        return data

    def validate_duration_minutes(self, value):
        if value is not None and not 1 <= value <= 1440:
            raise ValidationError("Duration must be 1–1440 minutes.")
        return value


class ExamViewSet(OwnedViewSet):
    queryset = Exam.objects.all()
    serializer_class = ExamSerializer

    def perform_update(self, serializer):
        serializer.save(confirmed=False)
        from planning.services import propose_if_needed

        propose_if_needed(self.request.user, "Exam details changed and require confirmation")

    @extend_schema(request=None, responses=ExamSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        exam = self.get_object()
        if not exam.starts_at or exam.starts_at <= timezone.now():
            raise ValidationError("Set an unambiguous future date and time before confirming.")
        if not exam.all_topics and not exam.topics.exists():
            raise ValidationError("Select at least one topic before confirming this exam.")
        exam.confirmed = True
        exam.save(update_fields=["confirmed"])
        from planning.services import propose_if_needed

        propose_if_needed(request.user, "Exam date confirmed")
        return Response(self.get_serializer(exam).data)


class SessionSerializer(serializer_for(PlannedSession)):
    topic_title = serializers.CharField(source="topic.title", read_only=True)


class PlanSerializer(serializer_for(Plan)):
    sessions = SessionSerializer(many=True, read_only=True)


class PlanViewSet(OwnedViewSet):
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    @extend_schema(request=PlanRequest, responses={201: PlanSerializer})
    def create(self, request, *args, **kwargs):
        from planning.services import generate_plan

        reason = serializers.CharField(max_length=500).run_validation(
            request.data.get("reason", "Requested a new study plan")
        )
        plan = generate_plan(request.user, reason)
        return Response(self.get_serializer(plan).data, status=201)

    @extend_schema(request=None, responses=PlanSerializer)
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        from planning.services import accept

        return Response(self.get_serializer(accept(self.get_object())).data)


class SessionViewSet(OwnedViewSet):
    queryset = PlannedSession.objects.all()
    serializer_class = SessionSerializer
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        raise ValidationError("Sessions are created by the plan generator.")

    @extend_schema(request=SessionStateRequest, responses=SessionSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def update_state(self, request, pk=None):
        Profile.objects.select_for_update().get(user=request.user)
        s = self.get_object()
        if s.plan.status != "accepted":
            raise ValidationError("Only sessions on the accepted plan can be changed.")
        state = request.data.get("status", s.status)
        if state not in ("pending", "started", "completed", "skipped") or s.status == "completed":
            raise ValidationError("Invalid transition or session already completed.")
        s.actual_minutes = serializers.IntegerField(min_value=0, max_value=1440).run_validation(
            request.data.get("actual_minutes", s.actual_minutes)
        )
        s.status = state
        s.locked = serializers.BooleanField().run_validation(request.data.get("locked", s.locked))
        s.save()
        if state in ("completed", "skipped"):
            from courses.services.workload import estimate

            estimate(s.topic)
            from planning.services import propose_if_needed

            propose_if_needed(request.user, "Study session " + state)
        return Response(self.get_serializer(s).data)

    @extend_schema(request=RescheduleRequest, responses={201: PlanSerializer})
    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        original = self.get_object()
        if original.plan.status != "accepted" or original.status == "completed" or original.locked:
            raise ValidationError("Reschedule an unlocked, incomplete session on the accepted plan.")
        start = serializers.DateTimeField().run_validation(request.data.get("starts_at"))
        end = start + (original.ends_at - original.starts_at)
        from planning.services import in_window, overlaps

        profile = Profile.objects.get(user=request.user)
        others = list(original.plan.sessions.exclude(pk=original.pk))
        from exams.services import next_exam

        exam = next_exam(request.user, original.topic)
        if (
            not exam
            or start < timezone.now()
            or end > exam.starts_at
            or not in_window(start, end, profile)
            or overlaps(start, end, others, timedelta(minutes=profile.break_minutes))
        ):
            raise ValidationError(
                "This time conflicts with availability, breaks, another session or the exam deadline."
            )
        with transaction.atomic():
            draft = Plan.objects.create(
                owner=request.user,
                previous=original.plan,
                reason=f"Reschedule session {original.pk}",
                unscheduled=original.plan.unscheduled,
            )
            for s in original.plan.sessions.all():
                PlannedSession.objects.create(
                    owner=request.user,
                    plan=draft,
                    topic=s.topic,
                    starts_at=start if s.pk == original.pk else s.starts_at,
                    ends_at=end if s.pk == original.pk else s.ends_at,
                    kind=s.kind,
                    status=s.status,
                    locked=s.locked,
                    actual_minutes=s.actual_minutes,
                )
        return Response(PlanSerializer(draft).data, status=201)


class MemoryViewSet(OwnedViewSet):
    queryset = MemoryItem.objects.all()
    serializer_class = serializer_for(MemoryItem)

    def perform_create(self, serializer):
        if not Profile.objects.get(user=self.request.user).memory_enabled:
            raise ValidationError("Enable AI memory explicitly in your profile first.")
        super().perform_create(serializer)


class NotificationViewSet(OwnedViewSet):
    queryset = Notification.objects.all()
    serializer_class = serializer_for(Notification, ("text", "key"))
    http_method_names = ["get", "patch", "delete", "head", "options"]


class FeedbackViewSet(OwnedViewSet):
    queryset = Feedback.objects.all()
    serializer_class = serializer_for(Feedback, ("response", "resolved"))


class ExportSerializer(serializer_for(ExportJob, ("file", "status", "error"))):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.pop("file", None)
        return data

    def validate(self, data):
        if data.get("kind") != "data" and not data.get("plan"):
            raise ValidationError("Select a plan for a PDF or calendar export.")
        return data


class ExportViewSet(OwnedViewSet):
    queryset = ExportJob.objects.all()
    serializer_class = ExportSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def perform_create(self, serializer):
        job = serializer.save(owner=self.request.user)
        from exports.tasks import build_export

        dispatch(build_export, ExportJob, job)

    @extend_schema(responses=OpenApiTypes.BINARY)
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        job = self.get_object()
        if job.status != "ready" or job.created_at < timezone.now() - timedelta(days=1):
            raise ValidationError("Export is not ready or has expired.")
        ext = "zip" if job.kind == "data" else job.kind
        return FileResponse(job.file.open("rb"), as_attachment=True, filename=f"studylens-{job.pk}.{ext}")
