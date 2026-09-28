"""Délais cibles (SLA) par service et catégorie de ticket.

Règles stockées dans la table sla_rules (page /admin/sla) : une règle
(service, catégorie) prime sur (service, toute catégorie), qui prime sur le
défaut DEFAULT_SLA_HOURS. Le délai sert au badge « échéance » des cartes de
l'Espace Tech, à Ticket.is_stale (relance quotidienne, bannière manager) et
au récap hebdomadaire.
"""
DEFAULT_SLA_HOURS = 24

# Profil de départ validé par l'utilisateur le 2026-09-28 (modifiable dans l'admin).
SLA_DEFAULTS = [
    ('IMAGO', None, 4),
    ('INFORMATIQUE', 'Incident Standard', 8),
    ('INFORMATIQUE', 'Demande Matériel', 120),
    ('DAF', None, 72),
    ('DRH', None, 48),
    ('TECHNIQUE', None, 48),
    ('GENERAUX', None, 48),
]


def _service_value(service):
    return service.value if hasattr(service, 'value') else (str(service) if service else '')


def sla_hours_for(service, category=None):
    from app.models import SlaRule
    svc = _service_value(service)
    rules = SlaRule.query.filter(SlaRule.service == svc, SlaRule.is_active == True).all()
    if category:
        for r in rules:
            if r.category and r.category.strip().lower() == category.strip().lower():
                return r.hours
    for r in rules:
        if not r.category:
            return r.hours
    return DEFAULT_SLA_HOURS


def format_remaining(hours):
    """« dans 3 h » / « dans 2 j » / « dépassé de 5 h » / « dépassé de 3 j »."""
    def unit(h):
        h = abs(h)
        if h < 1: return "moins d'1 h"
        if h < 48: return f"{int(round(h))} h"
        return f"{int(h // 24)} j"
    return f"dans {unit(hours)}" if hours >= 0 else f"dépassé de {unit(hours)}"


def seed_default_rules():
    """Insère le profil de départ si la table est vide (idempotent)."""
    from app import db
    from app.models import SlaRule
    if SlaRule.query.count():
        return 0
    for svc, cat, hours in SLA_DEFAULTS:
        db.session.add(SlaRule(service=svc, category=cat, hours=hours))
    db.session.commit()
    return len(SLA_DEFAULTS)
