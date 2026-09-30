import math
from django.db.models import Avg
from documents.models import TopicMapping
from planning.models import PlannedSession
from mastery.models import TopicMastery
from mastery.services import summary


def estimate(topic):
    if topic.estimate_override:
        return
    pages = TopicMapping.objects.filter(topic=topic, page__document__confirmed=True).values_list(
        "page__text", flat=True
    )
    words = " ".join(pages).split()
    # Heuristic only: reading at 100 words/minute plus worked examples and recall.
    # Unmapped topics retain an explicit conservative 90-minute estimate.
    long_ratio = sum(len(w) > 9 for w in words) / max(1, len(words))
    difficulty = min(5, max(1, math.ceil(2 + long_ratio * 6)))
    mastery = summary(TopicMastery.objects.filter(topic=topic).first())
    baseline = max(45, len(words) / 100 * 3 + 30) * difficulty / 3 if words else 90
    if mastery["answered"] >= 3:
        baseline *= 1.3 if mastery["score"] < 0.5 else 0.85 if mastery["score"] >= 0.8 else 1
    sessions = PlannedSession.objects.filter(
        topic=topic, status="completed", plan__status="accepted", actual_minutes__gt=0
    )
    ratios = [s.actual_minutes / max(1, (s.ends_at - s.starts_at).total_seconds() / 60) for s in sessions]
    if ratios:
        baseline *= max(0.5, min(2, sum(ratios) / len(ratios)))
    topic.estimated_minutes = max(30, min(3000, math.ceil(baseline / 15) * 15))
    topic.difficulty = difficulty
    topic.save(update_fields=["estimated_minutes", "difficulty"])
