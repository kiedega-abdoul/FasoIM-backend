from django.urls import path

from .views import (
    ProgressionNotificationsView,
    RelancerEmailView,
    StatistiquesNotificationsView,
    TestEmailView,
)


app_name = "notifications"

urlpatterns = [
    path("tester-email/", TestEmailView.as_view(), name="tester-email"),
    path("relancer-email/", RelancerEmailView.as_view(), name="relancer-email"),
    path("statistiques/", StatistiquesNotificationsView.as_view(), name="statistiques"),
    path("progression/<str:task_id>/", ProgressionNotificationsView.as_view(), name="progression"),
]
