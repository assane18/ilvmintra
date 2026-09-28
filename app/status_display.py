"""Libellés humains des statuts et frise de suivi d'un ticket.

Les statuts stockés (TicketStatus / FormSubmissionStatus) sont des codes
techniques ("VALIDATION_HIERARCHIQUE", "EN_ATTENTE_TRAITEMENT"…). Ce module
centralise leur traduction pour l'affichage utilisateur — un seul endroit à
modifier, exposé aux templates via le filtre Jinja `status_label` et la
fonction `ticket_timeline` (voir app/__init__.py).
"""

# Libellé long (phrase, pour le détail d'une demande) et court (badge de liste).
STATUS_LABELS = {
    'VALIDATION_HIERARCHIQUE': ('En attente de validation par votre manager', 'Validation manager'),
    'VALIDATION_TECHNIQUE':    ('En attente de validation par le service', 'Validation service'),
    'VALIDATION_DAF_MANAGER':  ('En attente de validation par la DAF', 'Validation DAF'),
    'SIGNATURE_DIRECTEUR':     ('En attente de signature du directeur', 'Signature directeur'),
    'EN_ATTENTE_TRAITEMENT':   ('En attente de prise en charge', 'À prendre en charge'),
    'EN_COURS':                ('En cours de traitement', 'En cours'),
    'EN_ATTENTE_USER':         ('En attente de votre réponse', 'Réponse attendue'),
    'REFUSE':                  ('Refusée', 'Refusée'),
    'TERMINE':                 ('Terminée', 'Terminée'),
}

# Statuts considérés "ouverts" du point de vue de l'utilisateur (demande pas
# encore aboutie) — sert au bloc "Mes demandes en cours" du portail.
OPEN_STATUS_VALUES = {
    'VALIDATION_HIERARCHIQUE', 'VALIDATION_TECHNIQUE', 'VALIDATION_DAF_MANAGER',
    'SIGNATURE_DIRECTEUR', 'EN_ATTENTE_TRAITEMENT', 'EN_COURS', 'EN_ATTENTE_USER',
}


def _value(status):
    return status.value if hasattr(status, 'value') else str(status)


def status_label(status, short=False):
    """Filtre Jinja : {{ ticket.status|status_label }} ou |status_label(true)."""
    value = _value(status)
    entry = STATUS_LABELS.get(value)
    if not entry:
        return value.replace('_', ' ').capitalize()
    return entry[1] if short else entry[0]


def is_open_status(status):
    return _value(status) in OPEN_STATUS_VALUES


def ticket_timeline(ticket):
    """Étapes de la frise "façon colis" d'un ticket.

    Retourne une liste de dicts {label, state, date, hint} avec state parmi
    done / current / failed / todo. Le ticket ne conserve pas l'historique de
    ses changements de statut : on n'affiche donc une étape de validation que
    lorsqu'elle est en cours ou a échoué (refus) — jamais comme "passée" par
    supposition — et les dates viennent des seules colonnes horodatées
    (created_at, assigned_at, closed_at)."""
    value = _value(ticket.status)
    validating = value in ('VALIDATION_HIERARCHIQUE', 'VALIDATION_TECHNIQUE',
                           'VALIDATION_DAF_MANAGER', 'SIGNATURE_DIRECTEUR')
    refused = value == 'REFUSE'
    assigned = bool(ticket.solver_id) or value in ('EN_COURS', 'EN_ATTENTE_USER', 'TERMINE')
    in_treatment = value in ('EN_COURS', 'EN_ATTENTE_USER')
    done = value == 'TERMINE'

    steps = [{'label': 'Envoyée', 'state': 'done', 'date': ticket.created_at, 'hint': None}]

    if validating or refused:
        steps.append({
            'label': STATUS_LABELS[value][1] if validating else 'Validation',
            'state': 'failed' if refused else 'current',
            'date': None,
            'hint': 'Demande refusée' if refused else STATUS_LABELS[value][0],
        })
        rest_state = 'todo'
    else:
        rest_state = None  # calculé étape par étape ci-dessous

    def st(done_cond, current_cond):
        # Un fait acquis (ex: technicien déjà affecté sur un bon de commande DAF
        # encore en validation) reste "done" même pendant une validation ;
        # seules les étapes "en cours" sont neutralisées tant qu'on valide.
        if done_cond: return 'done'
        if rest_state == 'todo': return 'todo'
        if current_cond: return 'current'
        return 'todo'

    steps.append({
        'label': 'Prise en charge',
        'state': st(assigned, value == 'EN_ATTENTE_TRAITEMENT'),
        'date': getattr(ticket, 'assigned_at', None) if assigned else None,
        'hint': (f"par {ticket.solver.fullname}" if assigned and ticket.solver else
                 ('Un technicien va se l’attribuer' if value == 'EN_ATTENTE_TRAITEMENT' else None)),
    })
    steps.append({
        'label': 'Traitement',
        'state': st(done, in_treatment),
        'date': None,
        'hint': 'Le technicien attend votre réponse' if value == 'EN_ATTENTE_USER' else None,
    })
    steps.append({
        'label': 'Résolue',
        'state': st(done, False),
        'date': ticket.closed_at if done else None,
        'hint': None,
    })
    return steps
