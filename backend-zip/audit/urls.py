from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import JournalActionViewSet


app_name = "audit"

router = SimpleRouter()
router.register("journaux", JournalActionViewSet, basename="journaux-audit")

urlpatterns = [path("", include(router.urls))]
