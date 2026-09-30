from .models import TopicMastery


def summary(record):
    count = record.answered if record else 0
    score = ((record.correct if record else 0) + 1) / (count + 2)
    state = (
        "insufficient evidence" if count < 3 else "strong" if score >= 0.8 else "developing" if score >= 0.5 else "weak"
    )
    return {
        "score": round(score, 3),
        "answered": count,
        "state": state,
        "method": "Beta(1,1): (correct + 1) / (answered + 2). At least 3 answers required.",
    }


def recompute(owner_id):
    from quizzes.models import Attempt
    from courses.models import Topic

    counts = {}
    for attempt in Attempt.objects.filter(owner_id=owner_id):
        for result in attempt.results:
            value = counts.setdefault(result["topic_id"], [0, 0])
            value[0] += int(result["is_correct"])
            value[1] += 1
    for topic in Topic.objects.filter(owner_id=owner_id):
        correct, answered = counts.get(topic.pk, [0, 0])
        if answered:
            TopicMastery.objects.update_or_create(
                owner_id=owner_id, topic=topic, defaults={"correct": correct, "answered": answered}
            )
        else:
            TopicMastery.objects.filter(topic=topic).delete()
