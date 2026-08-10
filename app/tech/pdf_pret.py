from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                 Paragraph, Spacer, HRFlowable, Image)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_JUSTIFY
from io import BytesIO
import os

# ── Couleurs ──────────────────────────────────────────────────────────
BLUE       = colors.HexColor('#003d80')
BLUE_LIGHT = colors.HexColor('#dce8ff')
GRAY       = colors.HexColor('#888888')
GRAY_LIGHT = colors.HexColor('#f5f5f5')
BLACK      = colors.black
WHITE      = colors.white

# ── Dimensions ────────────────────────────────────────────────────────
W       = 18.6 * cm          # largeur contenu (marges 1.2cm chaque côté)
IW      = W - (16 / 28.35 * cm)  # largeur interne section (padding G+D=8+8 pts)
LW      = 5.5 * cm           # largeur colonne label dans info-rows
VW      = IW - LW            # largeur colonne valeur
CHK_CM  = 12 / 28.35 * cm   # largeur checkbox = 12 pts ≈ 0.42 cm


# ── Styles de base ────────────────────────────────────────────────────
def _st(name, **kw):
    d = dict(fontName='Helvetica', fontSize=8.5, leading=11)
    d.update(kw)
    return ParagraphStyle(name, **d)

ST_TITLE  = _st('sec_title', fontName='Helvetica-Bold', fontSize=8.5,
                textColor=BLUE, leading=11)
ST_LABEL  = _st('label', fontName='Helvetica-Bold',
                textColor=colors.HexColor('#222222'))
ST_VALUE  = _st('value', fontName='Courier', fontSize=8.5)
ST_SMALL  = _st('small', fontSize=8, leading=10)
ST_COND   = _st('cond', fontSize=8, leading=12,
                alignment=TA_JUSTIFY, textColor=colors.HexColor('#333333'))


# ── Helpers ───────────────────────────────────────────────────────────

def _p(text, st=None, **kw):
    if st is None:
        st = _st('_', **kw)
    return Paragraph(text or '', st)


def _chkbox(checked: bool) -> Table:
    """Carré checkbox 12×12 pts, rempli en bleu si coché."""
    bg   = BLUE if checked else WHITE
    mark = _p('<b>&#215;</b>' if checked else ' ',
              _st('m', fontName='Helvetica-Bold', fontSize=8,
                  alignment=TA_CENTER, leading=9, textColor=WHITE))
    t = Table([[mark]], colWidths=[12], rowHeights=[12])
    t.setStyle(TableStyle([
        ('BOX',           (0,0), (0,0), 1,   BLACK),
        ('BACKGROUND',    (0,0), (0,0), bg),
        ('TOPPADDING',    (0,0), (0,0), 0),
        ('BOTTOMPADDING', (0,0), (0,0), 1),
        ('LEFTPADDING',   (0,0), (0,0), 0),
        ('RIGHTPADDING',  (0,0), (0,0), 0),
    ]))
    return t


def _chk_row(items: list) -> Table:
    """
    Rangée de checkboxes.
    items = [(label, checked, text_width_cm), ...]
    """
    GAP = 4
    cells, widths = [], []
    for label, checked, tw in items:
        cells  += [_chkbox(checked), '', _p(label, ST_SMALL)]
        widths += [CHK_CM,           GAP, tw * cm]
    total = sum(widths)
    if IW > total:
        cells.append('')
        widths.append(IW - total)
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING',   (0,0), (-1,-1), 1),
        ('RIGHTPADDING',  (0,0), (-1,-1), 1),
    ]))
    return t


def _info_table(rows: list) -> Table:
    """
    Tableau label | valeur soulignée.
    rows = [(label_str, value_str), ...]
    """
    data = [
        [_p(f'<b>{lbl}</b>', ST_LABEL), _p(val or '', ST_VALUE)]
        for lbl, val in rows
    ]
    t = Table(data, colWidths=[LW, VW])
    t.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'BOTTOM'),
        ('LINEBELOW',     (1,0), (1,-1),  0.5, BLACK),
        ('TOPPADDING',    (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (1,0), (1,-1),  4),
    ]))
    return t


def _section(title: str, inner_rows: list) -> Table:
    """
    Section avec bandeau bleu clair + titre + bordure grise.
    inner_rows = liste de flowables ou de listes (rows for inner Table)
    """
    data = [[_p(title, ST_TITLE)]] + [[row] for row in inner_rows]
    t = Table(data, colWidths=[W])
    cmds = [
        ('BOX',           (0,0), (-1,-1), 0.8, GRAY),
        ('BACKGROUND',    (0,0), (0,0),   BLUE_LIGHT),
        ('LINEBELOW',     (0,0), (0,0),   1,   BLUE),
        ('TOPPADDING',    (0,0), (0,0),   3),
        ('BOTTOMPADDING', (0,0), (0,0),   3),
        ('LEFTPADDING',   (0,0), (-1,-1), 7),
        ('RIGHTPADDING',  (0,0), (-1,-1), 7),
        ('TOPPADDING',    (0,1), (-1,-1), 2),
        ('BOTTOMPADDING', (-1,-1), (-1,-1), 3),
    ]
    t.setStyle(TableStyle(cmds))
    return t


def _sig_block(title: str, lines: list, width: float) -> Table:
    """Bloc de signature : titre + lignes avec espace de signature."""
    rows = [[_p(title, _st('st', fontName='Helvetica-Bold', fontSize=8,
                            textColor=BLUE))]]
    for lbl in lines:
        rows.append([_p(lbl, ST_SMALL)])
        rows.append([_p('')])          # ligne de signature
    t = Table(rows, colWidths=[width])
    cmds = [
        ('BOX',           (0,0), (-1,-1), 0.6, GRAY),
        ('BACKGROUND',    (0,0), (0,0),   BLUE_LIGHT),
        ('LINEBELOW',     (0,0), (0,0),   0.5, BLUE),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING',   (0,0), (-1,-1), 5),
        ('RIGHTPADDING',  (0,0), (-1,-1), 5),
    ]
    for i in range(2, len(rows), 2):
        cmds.append(('LINEBELOW',     (0,i), (0,i), 0.5, BLACK))
        cmds.append(('TOPPADDING',    (0,i), (0,i), 8))
        cmds.append(('BOTTOMPADDING', (0,i), (0,i), 2))
    t.setStyle(TableStyle(cmds))
    return t


def _pinpuk_row(pin: str, puk: str) -> Table:
    """PIN et PUK côte à côte sur une même ligne."""
    lw = 2.8 * cm
    vw = IW / 2 - lw
    t = Table([[
        _p('<b>Code PIN :</b>', ST_LABEL), _p(pin or '', ST_VALUE),
        _p('<b>Code PUK :</b>', ST_LABEL), _p(puk or '', ST_VALUE),
    ]], colWidths=[lw, vw, lw, vw])
    t.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'BOTTOM'),
        ('LINEBELOW',     (1,0), (1,0),   0.5, BLACK),
        ('LINEBELOW',     (3,0), (3,0),   0.5, BLACK),
        ('TOPPADDING',    (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (1,0), (1,0),   4),
        ('LEFTPADDING',   (2,0), (2,0),   8),
        ('RIGHTPADDING',  (3,0), (3,0),   4),
    ]))
    return t


# ── Générateur principal ──────────────────────────────────────────────

def generate_fiche_pret(data: dict, logo_path: str) -> bytes:
    """
    Génère la fiche de prêt en PDF avec ReportLab.
    data contient les champs du formulaire.
    Retourne les bytes du PDF.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.2*cm, rightMargin=1.2*cm,
        topMargin=0.4*cm, bottomMargin=0.3*cm
    )
    story = []

    # ── EN-TÊTE ──────────────────────────────────────────────────────
    try:
        logo_cell = Image(logo_path, width=4.5*cm, height=1.6*cm)
    except Exception:
        logo_cell = _p('<b>ILVM</b>', _st('logo', fontSize=14, textColor=BLUE))

    header = Table([[
        logo_cell,
        _p('<b>FICHE DE PRÊT DE MATÉRIEL INFORMATIQUE</b>',
           _st('ht', fontName='Helvetica-Bold', fontSize=13,
               textColor=BLUE, alignment=TA_RIGHT, leading=17))
    ]], colWidths=[5*cm, 12*cm])
    header.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('LINEBELOW',     (0,0), (-1,0),  2, BLUE),
        ('BOTTOMPADDING', (0,0), (-1,0),  6),
        ('TOPPADDING',    (0,0), (-1,0),  0),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
    ]))
    story += [header, Spacer(1, 8)]

    # ── EMPRUNTEUR ───────────────────────────────────────────────────
    story.append(_section('INFORMATIONS DE L\'EMPRUNTEUR', [
        _info_table([
            ('Nom et prénom :',        data.get('nom', '')),
            ('Service / Département :', data.get('service', '')),
            ('Fonction :',             data.get('fonction', '')),
            ('Téléphone :',            data.get('tel', '')),
            ('Email professionnel :',  data.get('mail', '')),
        ])
    ]))
    story.append(Spacer(1, 2))

    # ── MATÉRIEL ─────────────────────────────────────────────────────
    mat_type = data.get('type_mat', '')
    acc      = data.get('accessoires', [])

    mat_inner = [
        _p('<b>Type de matériel :</b>', ST_LABEL),
        _chk_row([
            ('Tablette',           mat_type == 'Tablette',           2.1),
            ('Ordinateur portable', mat_type == 'Ordinateur portable', 3.8),
            ('Téléphone portable',  mat_type == 'Téléphone portable',  3.7),
        ]),
        _info_table([
            ('Marque / Modèle :',  data.get('modele', '')),
            ('Numéro de série :',  data.get('sn', '')),
        ] + ([('IMEI :', data.get('imei', ''))] if data.get('imei') else [])),
        *([_pinpuk_row(data.get('pin', ''), data.get('puk', ''))]
          if mat_type == 'Téléphone portable' else []),
        _p('<b>Accessoires fournis :</b>', ST_LABEL),
        _chk_row([
            ('Chargeur',          'chargeur' in acc, 2.1),
            ('Câble USB',         'cable'    in acc, 2.1),
            ('Housse/Protection', 'housse'   in acc, 3.2),
            ('Souris',            'souris'   in acc, 1.7),
            ('Casque',            'casque'   in acc, 1.7),
        ]),
    ]
    story.append(_section('MATÉRIEL EMPRUNTÉ', mat_inner))
    story.append(Spacer(1, 2))

    # ── TYPE DE PRÊT ─────────────────────────────────────────────────
    pret_type = data.get('type_pret', '')
    story.append(_section('TYPE DE PRÊT', [
        _chk_row([
            ('Prêt longue durée',                        pret_type == 'longue', 3.5),
            ('Prêt à titre exceptionnel (- de 7 jours)', pret_type == 'court',  6.8),
        ])
    ]))
    story.append(Spacer(1, 2))

    # ── ÉTAT PHYSIQUE ─────────────────────────────────────────────────
    def etat_cell(current: str) -> Paragraph:
        parts = []
        for e in ['Bon', 'Acceptable', 'Dégradé']:
            parts.append(f'<b><u>{e}</u></b>' if e == current else e)
        return _p(' / '.join(parts),
                  _st('ec', fontSize=8, alignment=TA_CENTER, leading=11))

    col_w = [IW * p for p in (0.28, 0.36, 0.36)]
    etat_data = [
        [_p('<b>Élément</b>',       _st('eh', fontName='Helvetica-Bold', fontSize=8)),
         _p('<b>État au prêt</b>',  _st('eh', fontName='Helvetica-Bold', fontSize=8, alignment=TA_CENTER)),
         _p('<b>État au retour</b>', _st('eh', fontName='Helvetica-Bold', fontSize=8, alignment=TA_CENTER))],
        [_p('Écran',             ST_SMALL), etat_cell(data.get('etat_ecran',   'Bon')), _p('', ST_SMALL)],
        [_p('Clavier / Boutons', ST_SMALL), etat_cell(data.get('etat_clavier', 'Bon')), _p('', ST_SMALL)],
        [_p('Coque / Châssis',   ST_SMALL), etat_cell(data.get('etat_coque',   'Bon')), _p('', ST_SMALL)],
    ]
    etat_t = Table(etat_data, colWidths=col_w)
    etat_t.setStyle(TableStyle([
        ('GRID',         (0,0), (-1,-1), 0.5, GRAY),
        ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor('#e8e8e8')),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [WHITE, GRAY_LIGHT]),
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',   (0,0), (-1,-1), 2),
        ('BOTTOMPADDING',(0,0), (-1,-1), 2),
        ('LEFTPADDING',  (0,0), (0,-1),  5),
    ]))
    note = _p('<i>Veuillez indiquer l\'état du matériel au moment de l\'emprunt :</i>',
              _st('note', fontSize=7, textColor=GRAY, leading=10))
    story.append(_section('ÉTAT PHYSIQUE DU MATÉRIEL', [note, etat_t]))
    story.append(Spacer(1, 2))

    # ── CONDITIONS ───────────────────────────────────────────────────
    cond = (
        "L'emprunteur s'engage à utiliser ce matériel exclusivement dans le cadre de son activité "
        "professionnelle et à en assurer un usage responsable. Toute installation de logiciels non "
        "autorisés, modification ou réparation du matériel est strictement interdite. Il est tenu de "
        "protéger l'équipement contre toute détérioration, perte ou vol. En cas de problème, il devra "
        "informer immédiatement le service informatique."
    )
    story.append(_section('CONDITIONS D\'UTILISATION', [_p(cond, ST_COND)]))
    story.append(Spacer(1, 2))

    # ── DURÉE ────────────────────────────────────────────────────────
    d1 = data.get('date_depart', '')
    d2 = data.get('date_retour', '')
    duree_t = Table([[
        _p('<b>Date d\'emprunt :</b>', ST_LABEL),
        _p(d1, ST_VALUE),
        _p('<b>Date de restitution prévue :</b>', ST_LABEL),
        _p(d2, ST_VALUE),
    ]], colWidths=[4.5*cm, 3.3*cm, 5.2*cm, 3.4*cm])
    duree_t.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'BOTTOM'),
        ('LINEBELOW',     (1,0), (1,0),   0.5, BLACK),
        ('LINEBELOW',     (3,0), (3,0),   0.5, BLACK),
        ('TOPPADDING',    (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (1,0), (1,0),   4),
        ('RIGHTPADDING',  (3,0), (3,0),   4),
        ('LEFTPADDING',   (2,0), (2,0),   8),
    ]))
    story.append(_section('DURÉE DU PRÊT', [duree_t]))
    story.append(Spacer(1, 2))

    # ── ENGAGEMENT ───────────────────────────────────────────────────
    eng = (
        "Je reconnais avoir reçu le matériel mentionné ci-dessus en bon état de fonctionnement. "
        "J'accepte de le restituer dans les mêmes conditions et dans les délais impartis. En cas de "
        "perte, vol ou détérioration, je comprends que ma responsabilité pourra être engagée et que "
        "des mesures appropriées pourront être prises."
    )
    story.append(_section('ENGAGEMENT DE L\'EMPRUNTEUR', [_p(eng, ST_COND)]))
    story.append(Spacer(1, 2))

    # ── SIGNATURES (STRUCTURE CORRIGÉE À 3 COLONNES) ─────────────────
    # Largeur disponible W divisée par 3 (avec de légers ajustements de marge inter-colonnes)
    sw = (W / 3) - 4
    
    sig1 = _sig_block("L'Emprunteur",
                      ['Nom et prénom :', 'Signature :', 'Date :'], sw)
    sig2 = _sig_block("Le technicien qui s'en est occupé",
                      ['Nom et prénom :', 'Signature :', 'Date :'], sw)
    sig3 = _sig_block("Validation service informatique",
                      ['Nom du responsable :', 'Signature :', 'Date :'], sw)
                      
    sigs = Table([[sig1, sig2, sig3]], colWidths=[sw + 4, sw + 4, sw + 4])
    sigs.setStyle(TableStyle([
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('INNERGRID',     (0,0), (-1,-1), 0, WHITE),
    ]))
    story.append(sigs)

    # ── RETOUR ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 2))
    ret_t = Table([[
        _p('<b>Signature de l\'emprunteur :</b>', ST_LABEL),
        _p('', ST_VALUE),
        _p('<b>Date de restitution effective :</b>', ST_LABEL),
        _p('', ST_VALUE),
    ]], colWidths=[4.5*cm, 3.8*cm, 5.5*cm, 4.3*cm])
    ret_t.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'BOTTOM'),
        ('LINEBELOW',     (1,0), (1,0),   0.5, BLACK),
        ('LINEBELOW',     (3,0), (3,0),   0.5, BLACK),
        ('TOPPADDING',    (0,0), (-1,-1), 12),  # Légèrement réduit pour sécuriser la page unique
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (1,0), (1,0),   4),
        ('RIGHTPADDING',  (3,0), (3,0),   4),
        ('LEFTPADDING',   (2,0), (2,0),   8),
    ]))
    story.append(_section('RETOUR DU MATÉRIEL', [ret_t]))

    doc.build(story)
    return buf.getvalue()