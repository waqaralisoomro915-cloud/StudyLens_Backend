from django.contrib import admin
from .models import Document, DocumentPage, TopicMapping

admin.site.register(Document)
admin.site.register(DocumentPage)
admin.site.register(TopicMapping)
