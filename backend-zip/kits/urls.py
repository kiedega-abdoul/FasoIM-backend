from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ArticleKitViewSet,
    OperationKitsViewSet,
    RemiseKitViewSet,
)


app_name = "kits"

router = DefaultRouter()
router.register(
    "articles",
    ArticleKitViewSet,
    basename="articles-kit",
)
router.register(
    "remises",
    RemiseKitViewSet,
    basename="remises-kit",
)
router.register(
    "operations",
    OperationKitsViewSet,
    basename="operations-kit",
)


urlpatterns = [
    path("", include(router.urls)),
]
