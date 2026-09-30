from .models import Notification


def notify(owner_id, key, text):
    Notification.objects.get_or_create(owner_id=owner_id, key=key, defaults={"text": text[:500]})
