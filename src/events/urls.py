from django.urls import re_path

from . import views

UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

# Every route works with and without trailing slash (spec uses no slash).
urlpatterns = [
    re_path(r"^health/?$", views.HealthView.as_view(), name="health"),
    re_path(r"^sync/trigger/?$", views.SyncTriggerView.as_view(), name="sync-trigger"),
    re_path(r"^events/?$", views.EventListView.as_view(), name="event-list"),
    re_path(
        rf"^events/(?P<event_id>{UUID})/?$",
        views.EventDetailView.as_view(),
        name="event-detail",
    ),
    re_path(
        rf"^events/(?P<event_id>{UUID})/seats/?$",
        views.EventSeatsView.as_view(),
        name="event-seats",
    ),
    re_path(r"^tickets/?$", views.TicketCreateView.as_view(), name="ticket-create"),
    re_path(
        rf"^tickets/(?P<ticket_id>{UUID})/?$",
        views.TicketDetailView.as_view(),
        name="ticket-detail",
    ),
]
