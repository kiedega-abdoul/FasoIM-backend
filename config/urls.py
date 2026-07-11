from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


def health_check(request):
    return JsonResponse({
        "status": "ok",
        "project": "FasoIM",
        "message": "Backend Django opérationnel"
    })


urlpatterns = [
    path("", health_check, name="health-check"),
    path("admin/", admin.site.urls),

    # Module sessions
    path("api/sessions/", include("sessions_app.urls")),
    path("api/accounts/", include("accounts.urls")),
    path("api/imports/", include("imports_app.urls")),
    path("api/immerges/", include("immerges.urls")),
    path("api/affectations/", include("affectations.urls")),
    path("api/organisation/", include("organisation.urls")),
    path("api/sante/", include("sante.urls")),

    # Auth JWT
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Documentation API
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
