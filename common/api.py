from rest_framework import serializers, viewsets
from functools import lru_cache


class OwnedSerializer(serializers.ModelSerializer):
    def get_fields(self):
        fields = super().get_fields()
        fields["owner"].read_only = True
        fields["created_at"].read_only = True
        # Restrict writable relationships before validation, including nested references.
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            for field in fields.values():
                if isinstance(field, serializers.ManyRelatedField):
                    field = field.child_relation
                if isinstance(field, serializers.PrimaryKeyRelatedField) and field.queryset is not None:
                    names = {f.name for f in field.queryset.model._meta.fields}
                    if "owner" in names:
                        field.queryset = field.queryset.filter(owner=request.user)
                    elif "document" in names:
                        field.queryset = field.queryset.filter(document__owner=request.user)
        return fields


class OwnedViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset.none()
        return self.queryset.filter(owner=self.request.user).order_by("-id")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


@lru_cache(maxsize=None)
def serializer_for(model, readonly=()):
    class GeneratedSerializer(OwnedSerializer):
        class Meta:
            fields = "__all__"
            read_only_fields = readonly

    GeneratedSerializer.Meta.model = model
    GeneratedSerializer.__name__ = model.__name__ + "Serializer"
    return GeneratedSerializer
