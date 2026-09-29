#!/var/www/intranet/venv/bin/python3
"""Archivage et purge RGPD (lot 8) — voir app/rgpd.py pour les règles.

SIMULATION PAR DÉFAUT : sans option, le script affiche le plan (ce qui SERAIT
anonymisé / supprimé) et ne modifie rien. Seul `--apply` exécute la purge ;
chaque exécution réelle écrit une entrée d'audit (rgpd.purge) et un journal
/var/www/intranet/backups/rgpd_AAAA-MM-JJ.log (références, pas de données
personnelles).

Usage cron mensuel (le 2 du mois à 3h, après la sauvegarde nocturne) —
À INSTALLER MANUELLEMENT après validation des règles, NON installé :
  0 3 2 * * /var/www/intranet/scripts/purge_rgpd.py --apply >> /var/www/intranet/backups/purge_rgpd.log 2>&1

Options :
  --dry-run   (défaut) affiche le plan sans rien modifier
  --apply     exécute le plan
  --verbose   liste chaque opération (le dry-run l'est toujours)
"""
import argparse
import sys
from datetime import datetime

sys.path.insert(0, '/var/www/intranet')

from app import create_app  # noqa: E402


def print_plan(plan, verbose=True):
    print(f"Plan RGPD au {plan['now']:%d/%m/%Y %H:%M} — {len(plan['operations'])} opération(s)")
    for rule in plan['rules']:
        n = plan['counts'].get(rule['code'], 0)
        print(f"  {rule['code']:22s} {n:5d}   {rule['label']} ({rule['delay']})")
    if verbose and plan['operations']:
        print("\nDétail :")
        for op in plan['operations']:
            files = f" ; {len(op['files'])} fichier(s)" if op.get('files') else ''
            print(f"  {op['rule']:22s} {op['target_type'] or '':16s} {op['target_ref'] or '':30s} {op['detail']}{files}")


def main():
    parser = argparse.ArgumentParser(description="Purge RGPD de l'intranet (simulation par défaut)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='affiche le plan sans rien modifier (défaut)')
    mode.add_argument('--apply', action='store_true', help='EXÉCUTE le plan')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    app = create_app('production')
    with app.app_context():
        from app import rgpd
        plan = rgpd.plan_purge(datetime.now())
        if not args.apply:
            print("MODE SIMULATION (--dry-run) : aucune modification.\n")
            print_plan(plan, verbose=True)
            return
        print_plan(plan, verbose=args.verbose)
        if not plan['operations']:
            print("\nRien à purger.")
            return
        result = rgpd.apply_purge(plan, actor=None)
        print(f"\nPurge exécutée : {result['summary']}")
        print(f"Journal : {result['log_path'] or 'non écrit'}")


if __name__ == '__main__':
    main()
