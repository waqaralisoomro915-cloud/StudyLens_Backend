import re
from courses.models import Course


def suggest_courses(owner, text):
    def tokens(value):
        return set(re.findall(r"[^\W_]+", value.casefold())) - {
            "the",
            "and",
            "of",
            "to",
            "in",
            "a",
            "pdf",
            "notes",
            "lecture",
        }

    query = tokens(text)
    ranked = []
    for course in Course.objects.filter(owner=owner):
        matched = sorted(query & tokens(f"{course.code} {course.title}"))
        if matched:
            ranked.append({"course": course.pk, "title": course.title, "evidence": matched})
    return sorted(ranked, key=lambda item: (-len(item["evidence"]), item["course"]))[:5]
