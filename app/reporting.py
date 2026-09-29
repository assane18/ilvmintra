"""Rapport mensuel d'activité (lot 8) : HTML imprimable -> PDF (WeasyPrint).

- build_monthly_report(year, month) -> HTML (gabarit templates/reports/monthly.html)
- render_monthly_pdf(year, month)   -> bytes PDF
- generate_and_store(year, month)   -> génère, enregistre dans REPORTS_DIR,
                                       copie sur le partage réseau si monté
- send_monthly_report(...)          -> e-mail (kind='digest') aux DIRECTEUR/ADMIN
- list_reports()                    -> rapports déjà générés (page /admin/rapports)

Les chiffres viennent de tickets._compute_stats (même calcul que la page
Statistiques) : reçus, clôturés, délais moyens, taux de refus, satisfaction,
top catégories, évolution mensuelle sur 12 mois (graphique SVG, pas de JS).
"""
import base64
import calendar
import os
import re
import shutil
import sys
from datetime import datetime

from dateutil.relativedelta import relativedelta
from flask import current_app, render_template

from app.models import User, UserRole

# Dossiers par défaut ; surchargeables via app.config['REPORTS_DIR'] /
# app.config['REPORTS_SHARE_DIR'] (les tests pointent vers un dossier temporaire).
REPORTS_DIR = '/var/www/intranet/backups/rapports'
SHARE_DIR = '/mnt/ilvmfap1_info/Backups_Intranet/Rapports/'

MONTHS_FR = ['', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
             'août', 'septembre', 'octobre', 'novembre', 'décembre']

_REPORT_RE = re.compile(r'^rapport_(\d{4})-(\d{2})\.pdf$')


def reports_dir():
    return current_app.config.get('REPORTS_DIR') or REPORTS_DIR


def share_dir():
    return current_app.config.get('REPORTS_SHARE_DIR') or SHARE_DIR


def report_filename(year, month):
    return f"rapport_{year:04d}-{month:02d}.pdf"


def report_path(year, month):
    return os.path.join(reports_dir(), report_filename(year, month))


def previous_month(now=None):
    now = now or datetime.now()
    prev = now.replace(day=1) - relativedelta(months=1)
    return prev.year, prev.month


def month_bounds(year, month):
    start = datetime(year, month, 1)
    end = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59)
    return start, end


def _logo_data_uri():
    """Logo embarqué en data URI : le PDF ne dépend d'aucun chemin/URL."""
    for name in ('logo-pdf.png', 'logo.png'):
        path = os.path.join(current_app.root_path, 'static', 'img', name)
        if os.path.exists(path):
            with open(path, 'rb') as fp:
                return 'data:image/png;base64,' + base64.b64encode(fp.read()).decode('ascii')
    return None


def _monthly_series(stats, monthly_start, months=12):
    """Agrège l'évolution mensuelle de tous les services -> liste de dicts
    {key:'AAAA-MM', label:'sept. 26', received, closed} sur `months` mois."""
    series = []
    cursor = monthly_start
    for _ in range(months):
        key = cursor.strftime('%Y-%m')
        received = sum(s['monthly'].get(key, {}).get('received', 0) for s in stats.values())
        closed = sum(s['monthly'].get(key, {}).get('closed', 0) for s in stats.values())
        series.append({'key': key, 'label': f"{MONTHS_FR[cursor.month][:4]}. {cursor.strftime('%y')}",
                       'received': received, 'closed': closed})
        cursor = cursor + relativedelta(months=1)
    return series


def _svg_bar_chart(series, width=700, height=220):
    """Histogramme groupé (reçus / clôturés) en SVG statique, lisible à
    l'impression noir et blanc (hachure de gris + contour)."""
    if not series:
        return ''
    left, right, top, bottom = 36, 10, 14, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    max_val = max([1] + [max(p['received'], p['closed']) for p in series])
    # Graduation "ronde"
    step = max(1, int(max_val / 4) if max_val >= 4 else 1)
    max_axis = step * 4 if max_val <= step * 4 else max_val
    group_w = plot_w / len(series)
    bar_w = group_w * 0.34
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif" font-size="9">']
    for i in range(5):
        val = round(max_axis * i / 4)
        y = top + plot_h - plot_h * i / 4
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#d9dee5" stroke-width="0.6"/>')
        out.append(f'<text x="{left - 5}" y="{y + 3:.1f}" text-anchor="end" fill="#64748b">{val}</text>')
    for idx, p in enumerate(series):
        gx = left + idx * group_w
        for j, (key, fill, stroke) in enumerate((('received', '#2563eb', '#1d4ed8'), ('closed', '#10b981', '#047857'))):
            h = plot_h * p[key] / max_axis if max_axis else 0
            x = gx + group_w * 0.16 + j * bar_w
            y = top + plot_h - h
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>')
            if p[key]:
                out.append(f'<text x="{x + bar_w / 2:.1f}" y="{y - 2:.1f}" text-anchor="middle" fill="#334155" font-size="8">{p[key]}</text>')
        out.append(f'<text x="{gx + group_w / 2:.1f}" y="{height - bottom + 14}" text-anchor="middle" fill="#475569">{p["label"]}</text>')
    out.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}" stroke="#94a3b8" stroke-width="0.8"/>')
    # Légende
    lx = left
    ly = height - 6
    out.append(f'<rect x="{lx}" y="{ly - 8}" width="10" height="8" fill="#2563eb"/><text x="{lx + 14}" y="{ly - 1}" fill="#334155">Reçus</text>')
    out.append(f'<rect x="{lx + 60}" y="{ly - 8}" width="10" height="8" fill="#10b981"/><text x="{lx + 74}" y="{ly - 1}" fill="#334155">Clôturés</text>')
    out.append('</svg>')
    return ''.join(out)


def monthly_report_data(year, month):
    """Toutes les données du rapport (réutilisées par le HTML et les tests)."""
    from app.routes.tickets import _compute_stats  # import tardif : module lourd
    period_start, period_end = month_bounds(year, month)
    monthly_start = period_start - relativedelta(months=11)
    stats = _compute_stats(None, period_start, period_end, monthly_start, period_end)
    services = sorted(stats.keys(), key=lambda s: (-stats[s]['received'], s))
    totals = {
        'received': sum(s['received'] for s in stats.values()),
        'closed': sum(s['closed'] for s in stats.values()),
        'refused': sum(s['status_counts'].get('REFUSE', 0) for s in stats.values()),
        'rated': sum(s['satisfaction_count'] for s in stats.values()),
    }
    rated_total = totals['rated']
    if rated_total:
        totals['satisfaction_pct'] = round(sum((s['satisfaction_pct'] or 0) * s['satisfaction_count']
                                               for s in stats.values()) / rated_total)
    else:
        totals['satisfaction_pct'] = None
    series = _monthly_series(stats, monthly_start)
    return {
        'year': year, 'month': month,
        'month_label': f"{MONTHS_FR[month]} {year}",
        'period_start': period_start, 'period_end': period_end,
        'stats': stats, 'services': services, 'totals': totals,
        'series': series, 'chart_svg': _svg_bar_chart(series),
        'generated_at': datetime.now(),
        'logo': _logo_data_uri(),
    }


def build_monthly_report(year, month):
    """HTML autonome (CSS inline, logo embarqué) du rapport du mois."""
    data = monthly_report_data(year, month)
    return render_template('reports/monthly.html', **data)


def _import_weasyprint():
    """WeasyPrint peut être installé hors du venv (ex. `pip install --user`) :
    on ajoute le site utilisateur et les paquets système en repli avant
    d'abandonner avec un message explicite."""
    try:
        import weasyprint
        return weasyprint
    except ImportError:
        pass
    import site
    for extra in (site.getusersitepackages(), '/usr/lib/python3/dist-packages'):
        if extra and os.path.isdir(extra) and extra not in sys.path:
            sys.path.append(extra)
    try:
        import weasyprint
        return weasyprint
    except ImportError as e:
        raise RuntimeError("WeasyPrint indisponible : installez-le dans le venv "
                           "(pip install weasyprint) pour générer les rapports PDF.") from e


def html_to_pdf(html):
    weasyprint = _import_weasyprint()
    base_url = os.path.join(current_app.root_path, 'static') + os.sep
    return weasyprint.HTML(string=html, base_url=base_url).write_pdf()


def render_monthly_pdf(year, month):
    return html_to_pdf(build_monthly_report(year, month))


def generate_and_store(year, month, copy_to_share=True):
    """Génère le PDF, l'écrit dans REPORTS_DIR (écrase la version précédente)
    et le copie sur le partage réseau s'il est monté. Retourne
    (chemin_local, octets, chemin_partage_ou_None)."""
    pdf = render_monthly_pdf(year, month)
    os.makedirs(reports_dir(), exist_ok=True)
    path = report_path(year, month)
    with open(path, 'wb') as fp:
        fp.write(pdf)
    shared = None
    if copy_to_share:
        shared = copy_to_share_dir(path)
    return path, pdf, shared


def copy_to_share_dir(path):
    """Copie sur le partage SMB uniquement si son point de montage parent
    existe et est monté (jamais de création de dossier sur un montage absent)."""
    target_dir = share_dir()
    mount_root = os.path.dirname(target_dir.rstrip('/'))
    try:
        if not (os.path.isdir(mount_root) and os.path.ismount(_mount_point(mount_root))):
            return None
        os.makedirs(target_dir, exist_ok=True)
        dest = os.path.join(target_dir, os.path.basename(path))
        shutil.copy2(path, dest)
        return dest
    except Exception as e:
        current_app.logger.warning(f"Rapport : copie sur le partage impossible ({e})")
        return None


def _mount_point(path):
    path = os.path.abspath(path)
    while not os.path.ismount(path) and path != '/':
        path = os.path.dirname(path)
    return path


def report_recipients():
    """Adresses des comptes DIRECTEUR et ADMIN (dédoublonnées)."""
    users = User.query.filter(User.role.in_([UserRole.DIRECTEUR, UserRole.ADMIN])).all()
    seen, out = set(), []
    for u in users:
        if u.email and u.email.lower() not in seen:
            seen.add(u.email.lower())
            out.append(u.email)
    return out


def send_monthly_report(year, month, pdf_bytes, recipients=None):
    """E-mail (kind='digest' : toujours envoyé quel que soit le mode e-mail du
    destinataire) avec le PDF en pièce jointe. Retourne les destinataires."""
    from app.emails import send_email, get_outlook_friendly_html
    recipients = recipients if recipients is not None else report_recipients()
    if not recipients:
        return []
    label = f"{MONTHS_FR[month]} {year}"
    base_url = current_app.config.get('BASE_URL', '').rstrip('/')
    content = (f"<p>Bonjour,</p><p>Veuillez trouver en pièce jointe le rapport d'activité de l'intranet "
               f"pour <strong>{label}</strong> : demandes reçues et clôturées par service, délais moyens, "
               f"taux de refus, satisfaction des demandeurs et évolution sur 12 mois.</p>"
               f"<p style=\"font-size:12px;color:#718096;\">Les rapports précédents restent téléchargeables "
               f"dans Administration &gt; Rapports mensuels.</p>")
    html = get_outlook_friendly_html(f"Rapport mensuel — {label}", content,
                                     f"{base_url}/admin/rapports", "Voir les rapports")
    send_email(f"[Intranet] Rapport d'activité — {label}", recipients,
               f"Rapport d'activité {label} en pièce jointe.", html, kind='digest',
               attachments=[(report_filename(year, month), 'application/pdf', pdf_bytes)])
    return recipients


def list_reports():
    """Rapports présents dans REPORTS_DIR, du plus récent au plus ancien :
    [{filename, year, month, label, size, modified}]."""
    out = []
    directory = reports_dir()
    if not os.path.isdir(directory):
        return out
    for name in os.listdir(directory):
        m = _REPORT_RE.match(name)
        if not m:
            continue
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            continue
        full = os.path.join(directory, name)
        st = os.stat(full)
        out.append({'filename': name, 'year': year, 'month': month,
                    'label': f"{MONTHS_FR[month].capitalize()} {year}",
                    'size_kb': round(st.st_size / 1024, 1),
                    'modified': datetime.fromtimestamp(st.st_mtime)})
    out.sort(key=lambda r: (r['year'], r['month']), reverse=True)
    return out
