from .access_context import (
    definir_affectation_courante_id,
    restaurer_affectation_courante_id,
)


class AffectationCouranteMiddleware:
    HEADER = "HTTP_X_FASOIM_AFFECTATION"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        affectation_id = request.META.get(self.HEADER) or None
        token = definir_affectation_courante_id(affectation_id)

        try:
            return self.get_response(request)
        finally:
            restaurer_affectation_courante_id(token)
