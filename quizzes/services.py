from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import ValidationError
from ai.client import generate, retrieve, validate_citations, AIError
from .models import Quiz, Attempt
from mastery.models import TopicMastery


def generate_questions(quiz):
    topics = list(quiz.course.topics.all())
    query = quiz.topic.title if quiz.topic else " ".join(t.title for t in topics)
    sources = retrieve(quiz.owner, quiz.course, query or quiz.course.title)
    if not sources:
        raise AIError("No relevant confirmed material. Review your pages and add syllabus topics first.")
    result = generate(
        'Generate a multiple-choice quiz. Return JSON {"questions":[{"text":string,"choices":[four distinct strings],"correct":0..3,"explanation":string,"topic_id":integer,"citations":[{"page_id":integer,"quote":exact source substring}]}]}. Exactly the requested length; one unambiguous correct option. Use only the supplied topic IDs and sources.',
        {
            "length": quiz.length,
            "difficulty": quiz.difficulty,
            "topics": [{"id": t.pk, "title": t.title} for t in topics if not quiz.topic or t.pk == quiz.topic_id],
            "sources": sources,
        },
    )
    questions = result.get("questions")
    if not isinstance(questions, list) or len(questions) != quiz.length:
        raise AIError("AI quiz has the wrong number of questions.")
    seen = set()
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("text"), str) or not q["text"].strip() or q["text"] in seen:
            raise AIError("Invalid or duplicate quiz question.")
        seen.add(q["text"])
        choices = q.get("choices")
        if (
            not isinstance(choices, list)
            or len(choices) != 4
            or not all(isinstance(c, str) and c.strip() for c in choices)
            or len(set(choices)) != 4
            or type(q.get("correct")) is not int
            or not 0 <= q["correct"] < 4
        ):
            raise AIError("Invalid answer key or choices.")
        if (
            q.get("topic_id") not in {t.pk for t in topics if not quiz.topic or t.pk == quiz.topic_id}
            or not isinstance(q.get("explanation"), str)
            or not q["explanation"].strip()
        ):
            raise AIError("Invalid quiz topic or explanation.")
        q["citations"] = validate_citations(q.get("citations"), sources)
    return questions


@transaction.atomic
def score(quiz, owner, answers):
    quiz = Quiz.objects.select_for_update().get(pk=quiz.pk, owner=owner)
    if quiz.status != "ready":
        raise ValidationError("Quiz is not ready.")
    if Attempt.objects.filter(quiz=quiz, owner=owner).exists():
        raise ValidationError("This quiz has already been scored. Generate a new quiz for more practice.")
    if (
        not isinstance(answers, list)
        or len(answers) != len(quiz.questions)
        or any(type(a) is not int or not 0 <= a < 4 for a in answers)
    ):
        raise ValidationError("Choose one valid answer for every question.")
    results = []
    for answer, question in zip(answers, quiz.questions):
        correct = answer == question["correct"]
        results.append(question | {"selected": answer, "is_correct": correct})
        record, _ = TopicMastery.objects.get_or_create(owner=owner, topic_id=question["topic_id"])
        TopicMastery.objects.filter(pk=record.pk).update(
            correct=F("correct") + int(correct), answered=F("answered") + 1
        )
    attempt = Attempt.objects.create(
        owner=owner,
        quiz=quiz,
        answers=answers,
        correct=sum(r["is_correct"] for r in results),
        total=len(results),
        results=results,
    )
    from courses.services.workload import estimate

    for topic in quiz.course.topics.filter(pk__in={q["topic_id"] for q in quiz.questions}):
        estimate(topic)
    from planning.services import propose_if_needed

    propose_if_needed(owner, "New quiz evidence changed topic priorities")
    return attempt
