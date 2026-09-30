from celery import shared_task
from .models import Quiz
from .services import generate_questions
from notifications.services import notify


@shared_task
def generate_quiz(pk, owner_id):
    if not Quiz.objects.filter(pk=pk, owner_id=owner_id, status="queued").update(status="processing"):
        return
    quiz = Quiz.objects.get(pk=pk, owner_id=owner_id)
    try:
        questions = generate_questions(quiz)
        if Quiz.objects.filter(pk=pk, owner_id=owner_id).update(questions=questions, status="ready", error=""):
            notify(owner_id, f"quiz:{pk}", "Your practice quiz is ready.")
    except Exception as e:
        Quiz.objects.filter(pk=pk, owner_id=owner_id).update(status="failed", error=str(e)[:500])
