from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .serializers import (
    EventDetailSerializer,
    EventFilterSerializer,
    EventListSerializer,
    TicketCreateSerializer,
)
from .tasks import trigger_sync


class EventPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class SyncTriggerView(APIView):
    def post(self, request):
        trigger_sync()
        return Response({"status": "started"})


class EventListView(ListAPIView):
    serializer_class = EventListSerializer
    pagination_class = EventPagination

    def get_queryset(self):
        filters = EventFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return services.list_events(date_from=filters.validated_data.get("date_from"))


class EventDetailView(APIView):
    def get(self, request, event_id):
        event = services.get_event(event_id)
        return Response(EventDetailSerializer(event).data)


class EventSeatsView(APIView):
    def get(self, request, event_id):
        seats = services.get_available_seats(event_id)
        return Response({"event_id": str(event_id), "available_seats": seats})


class TicketCreateView(APIView):
    def post(self, request):
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.register_ticket(**serializer.validated_data)
        return Response(
            {"ticket_id": str(ticket.ticket_id)}, status=status.HTTP_201_CREATED
        )


class TicketDetailView(APIView):
    def delete(self, request, ticket_id):
        services.cancel_ticket(ticket_id)
        return Response({"success": True})
