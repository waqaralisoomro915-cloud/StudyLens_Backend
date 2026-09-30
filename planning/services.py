from datetime import datetime, timedelta, time, timezone as dt_timezone
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from accounts.models import Profile
from courses.models import Topic
from exams.services import next_exam, topic_deadlines
from mastery.models import TopicMastery
from mastery.services import summary
from .models import Plan, PlannedSession


def overlaps(start, end, sessions, gap):
    return any(start < s.ends_at + gap and end + gap > s.starts_at for s in sessions)


def in_window(start, end, profile):
    zone = ZoneInfo(profile.timezone)
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    return local_start.date() == local_end.date() and any(
        w["day"] == local_start.weekday()
        and time.fromisoformat(w["start"]) <= local_start.time().replace(tzinfo=None)
        and local_end.time().replace(tzinfo=None) <= time.fromisoformat(w["end"])
        for w in profile.availability
    )


@transaction.atomic
def generate_plan(owner, reason="Initial plan"):
    profile, _ = Profile.objects.get_or_create(user=owner)
    profile = Profile.objects.select_for_update().get(pk=profile.pk)
    previous = Plan.objects.filter(owner=owner, status="accepted").first()
    plan = Plan.objects.create(owner=owner, previous=previous, reason=reason)
    now = timezone.now()
    zone = ZoneInfo(profile.timezone)
    gap = timedelta(minutes=profile.break_minutes)
    sessions = []
    usage = {}
    preserved = {}
    deadlines = topic_deadlines(owner, now)
    if previous:
        for old in previous.sessions.filter(status="completed") | previous.sessions.filter(locked=True):
            copy = PlannedSession.objects.create(
                owner=owner,
                plan=plan,
                topic=old.topic,
                starts_at=old.starts_at,
                ends_at=old.ends_at,
                kind=old.kind,
                status=old.status,
                locked=old.locked,
                actual_minutes=old.actual_minutes,
            )
            minutes = int((copy.ends_at - copy.starts_at).total_seconds() / 60)
            key = copy.starts_at.astimezone(zone).date()
            usage[key] = usage.get(key, 0) + minutes
            preserved[copy.topic_id] = preserved.get(copy.topic_id, 0) + minutes
            deadline = deadlines.get(copy.topic_id)
            if copy.status != "completed" and (
                copy.starts_at < now
                or not in_window(copy.starts_at, copy.ends_at, profile)
                or (not deadline or copy.ends_at > deadline)
                or overlaps(copy.starts_at, copy.ends_at, sessions, gap)
                or usage[key] > profile.daily_limit
            ):
                plan.conflicts.append(
                    f"Locked session {old.pk} conflicts with current constraints. Unlock it in the accepted plan and regenerate."
                )
            sessions.append(copy)
    records = {m.topic_id: m for m in TopicMastery.objects.filter(owner=owner)}
    topics = list(Topic.objects.filter(owner=owner))
    topics.sort(
        key=lambda t: (
            deadlines.get(t.pk, now + timedelta(days=366)),
            summary(records.get(t.pk))["score"],
            -t.difficulty,
        )
    )
    for topic in topics:
        deadline = deadlines.get(topic.pk)
        if not deadline:
            plan.unscheduled.append(
                {
                    "topic": topic.pk,
                    "title": topic.title,
                    "minutes": topic.estimated_minutes,
                    "reason": "No future confirmed exam covers this topic.",
                }
            )
            continue
        remaining = max(0, topic.estimated_minutes - preserved.get(topic.pk, 0))
        index = sum(s.topic_id == topic.pk for s in sessions)
        date = now.astimezone(zone).date()
        last = min(deadline.astimezone(zone).date(), date + timedelta(days=180))
        while remaining > 0 and date <= last:
            for w in sorted(profile.availability, key=lambda w: w["start"]):
                if w["day"] != date.weekday():
                    continue
                cursor = datetime.combine(date, time.fromisoformat(w["start"]), zone).astimezone(dt_timezone.utc)
                window_end = datetime.combine(date, time.fromisoformat(w["end"]), zone).astimezone(dt_timezone.utc)
                while cursor < window_end and remaining > 0:
                    minutes = min(profile.session_minutes, remaining)
                    end = cursor + timedelta(minutes=minutes)
                    if end > window_end or end > deadline or usage.get(date, 0) + minutes > profile.daily_limit:
                        break
                    if cursor < now or not in_window(cursor, end, profile) or overlaps(cursor, end, sessions, gap):
                        cursor += timedelta(minutes=5)
                        continue
                    kind = ["learn", "practice", "revision"][min(index, 2)]
                    session = PlannedSession.objects.create(
                        owner=owner, plan=plan, topic=topic, starts_at=cursor, ends_at=end, kind=kind
                    )
                    sessions.append(session)
                    remaining -= minutes
                    usage[date] = usage.get(date, 0) + minutes
                    cursor = end + gap
                    index += 1
            date += timedelta(days=1)
        if remaining:
            plan.unscheduled.append(
                {
                    "topic": topic.pk,
                    "title": topic.title,
                    "minutes": remaining,
                    "reason": "Insufficient available capacity before the exam (180-day planning horizon).",
                }
            )
    plan.save(update_fields=["unscheduled", "conflicts"])
    return plan


def propose_if_needed(owner, reason):
    if Plan.objects.filter(owner=owner, status="accepted").exists():
        plan = generate_plan(owner, reason)
        from notifications.services import notify

        notify(owner.pk, f"plan:{plan.pk}", f"A revised plan is ready to review: {reason}")
        return plan


@transaction.atomic
def accept(plan):
    Profile.objects.select_for_update().get(user=plan.owner)
    plan = Plan.objects.select_for_update().get(pk=plan.pk)
    current = Plan.objects.filter(owner=plan.owner, status="accepted").first()
    if plan.status != "draft" or plan.conflicts:
        raise ValidationError("Only a draft without locked-session conflicts can be accepted.")
    if (current.pk if current else None) != plan.previous_id:
        raise ValidationError("This draft is stale. Generate a new revision.")
    if current:
        for original in current.sessions.filter(status="completed") | current.sessions.filter(locked=True):
            if not plan.sessions.filter(
                topic=original.topic,
                starts_at=original.starts_at,
                ends_at=original.ends_at,
                status=original.status,
                locked=original.locked,
                actual_minutes=original.actual_minutes,
            ).exists():
                raise ValidationError("Completed or locked sessions changed since this draft. Generate a new revision.")
    # Revalidate against current constraints so stale drafts cannot bypass changed settings.
    profile = Profile.objects.get(user=plan.owner)
    scheduled = []
    usage = {}
    for s in plan.sessions.order_by("starts_at"):
        if s.status == "completed":
            continue
        exam = next_exam(plan.owner, s.topic)
        day = s.starts_at.astimezone(ZoneInfo(profile.timezone)).date()
        usage[day] = usage.get(day, 0) + int((s.ends_at - s.starts_at).total_seconds() / 60)
        if (
            not exam
            or s.ends_at > exam.starts_at
            or s.starts_at < timezone.now()
            or not in_window(s.starts_at, s.ends_at, profile)
            or overlaps(s.starts_at, s.ends_at, scheduled, timedelta(minutes=profile.break_minutes))
            or usage[day] > profile.daily_limit
        ):
            raise ValidationError("Constraints changed or sessions are now in the past. Generate a new draft.")
        scheduled.append(s)
    Plan.objects.filter(owner=plan.owner, status="accepted").update(status="superseded")
    plan.status = "accepted"
    plan.save(update_fields=["status"])
    return plan
