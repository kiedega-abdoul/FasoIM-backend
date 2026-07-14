from contextvars import ContextVar

_affectation_courante_id = ContextVar(
    "affectation_courante_id",
    default=None,
)


def definir_affectation_courante_id(affectation_id):
    return _affectation_courante_id.set(affectation_id)


def obtenir_affectation_courante_id():
    return _affectation_courante_id.get()


def restaurer_affectation_courante_id(token):
    _affectation_courante_id.reset(token)
