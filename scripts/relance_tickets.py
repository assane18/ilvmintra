#!/var/www/intranet/venv/bin/python3
"""Relance quotidienne des tickets PENDING/IN_PROGRESS dont le délai cible (SLA,
voir app/sla.py) est dépassé et toujours ouverts (Ticket.is_stale).

- Un ticket assigné (IN_PROGRESS) -> un email groupé à son solver.
- Un ticket non pris en charge (PENDING) -> un email groupé à tous les
  solvers/managers/directeurs du service cible (même logique que
  get_service_emails côté création de ticket).

Se répète chaque jour tant que le ticket reste ouvert (pas de mécanisme
anti-doublon volontairement — c'est le comportement demandé).

Usage cron (une fois par jour, ex. 8h) :
  0 8 * * * /var/www/intranet/scripts/relance_tickets.py >> /var/www/intranet/backups/relance.log 2>&1
"""
import sys
from collections import defaultdict

sys.path.insert(0, '/var/www/intranet')

from app import create_app, db  # noqa: E402
from app.models import Ticket, TicketStatus, User, UserRole  # noqa: E402
from app.emails import send_stale_tickets_reminder  # noqa: E402


def get_service_recipients(service_enum):
    """Reproduit app/routes/tickets.py::get_service_emails (solvers +
    managers/directeurs/admin dont le service cible fait partie des services
    gérés) — dupliqué ici pour ne pas dépendre d'un import de tickets.py
    (module volumineux, non pensé pour être importé depuis un script)."""
    staff = User.query.filter(User.role.in_(
        [UserRole.SOLVER, UserRole.MANAGER, UserRole.DIRECTEUR, UserRole.ADMIN]
    )).all()
    target_val = service_enum.value if hasattr(service_enum, 'value') else str(service_enum)
    target_name = service_enum.name if hasattr(service_enum, 'name') else str(service_enum)
    emails = []
    for u in staff:
        if not u.email:
            continue
        allowed = u.get_allowed_services()
        if target_val in allowed or target_name in allowed or 'ADMIN' in str(u.role.value).upper():
            emails.append(u.email)
    return emails


def main():
    app = create_app('production')
    with app.app_context():
        stale = Ticket.query.filter(
            Ticket.status.in_([TicketStatus.PENDING, TicketStatus.IN_PROGRESS])
        ).all()
        stale = [t for t in stale if t.is_stale]

        if not stale:
            print("Aucun ticket en retard.")
            return

        assigned = defaultdict(list)   # solver_id -> [tickets]
        unassigned_by_service = defaultdict(list)  # target_service -> [tickets]

        for t in stale:
            if t.solver_id:
                assigned[t.solver_id].append(t)
            else:
                unassigned_by_service[t.target_service].append(t)

        sent = 0

        for solver_id, tickets in assigned.items():
            solver = db.session.get(User, solver_id)
            if solver and solver.email:
                send_stale_tickets_reminder(solver.email, tickets, assigned_to_me=True)
                sent += 1
                print(f"Relance envoyée à {solver.username} ({len(tickets)} ticket(s) assignés).")

        for service_enum, tickets in unassigned_by_service.items():
            recipients = get_service_recipients(service_enum)
            for email in recipients:
                send_stale_tickets_reminder(email, tickets, assigned_to_me=False)
                sent += 1
            print(f"Relance envoyée à {len(recipients)} destinataire(s) pour {service_enum} ({len(tickets)} ticket(s) non pris en charge).")

        print(f"Terminé : {sent} email(s) de relance envoyé(s) pour {len(stale)} ticket(s) en retard.")


if __name__ == '__main__':
    main()
