"""Plain serializers: only shape and validate data, no business logic."""

from rest_framework import serializers

from .models import Event, Place


class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = ["id", "name", "city", "address"]


class PlaceDetailSerializer(PlaceSerializer):
    class Meta(PlaceSerializer.Meta):
        fields = [*PlaceSerializer.Meta.fields, "seats_pattern"]


class EventListSerializer(serializers.ModelSerializer):
    place = PlaceSerializer()

    class Meta:
        model = Event
        fields = [
            "id",
            "name",
            "place",
            "event_time",
            "registration_deadline",
            "status",
            "number_of_visitors",
        ]


class EventDetailSerializer(EventListSerializer):
    place = PlaceDetailSerializer()


class EventFilterSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)


class TicketCreateSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    seat = serializers.RegexField(
        r"^[A-Z][1-9][0-9]*$",
        max_length=16,
        error_messages={"invalid": "Seat must look like A15."},
    )
