from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.models import Notification, TeamMessage, ServiceType
from app import db
from datetime import datetime

api_bp = Blueprint('api', __name__)

# --- NOTIFICATIONS (Déjà existant) ---
@api_bp.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    notifs = current_user.notifications.filter_by(is_read=False).order_by(Notification.timestamp.desc()).limit(10).all()
    count = current_user.notifications.filter_by(is_read=False).count()
    return jsonify({'count': count, 'notifications': [n.to_dict() for n in notifs]})

@api_bp.route('/api/notifications/read/<int:id>', methods=['POST'])
@login_required
def mark_read(id):
    notif = Notification.query.get_or_404(id)
    if notif.user_id != current_user.id: return jsonify({'error': 'Unauthorized'}), 403
    notif.is_read = True
    db.session.commit()
    return jsonify({'success': True})

@api_bp.route('/api/notifications/read_all', methods=['POST'])
@login_required
def mark_all_read():
    current_user.notifications.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})

# --- TEAM CHAT (NOUVEAU) ---

@api_bp.route('/api/team_chat', methods=['GET'])
@login_required
def get_team_messages():
    # On récupère les messages du service de l'utilisateur
    if not current_user.service_department:
        return jsonify([]) # Pas de service, pas de chat
        
    messages = TeamMessage.query.filter_by(service=current_user.service_department)\
        .order_by(TeamMessage.timestamp.desc())\
        .limit(50).all()
    
    # On inverse pour avoir l'ordre chronologique (le plus vieux en haut pour le chat)
    msgs_data = []
    for m in reversed(messages):
        d = m.to_dict()
        d['is_me'] = (m.author_id == current_user.id)
        # Formatage heure
        d['time'] = m.timestamp.strftime('%H:%M')
        msgs_data.append(d)
        
    return jsonify(msgs_data)

@api_bp.route('/api/team_chat', methods=['POST'])
@login_required
def post_team_message():
    if not current_user.service_department:
        return jsonify({'error': 'No service'}), 400
        
    data = request.get_json()
    content = data.get('content')
    
    if content:
        msg = TeamMessage(
            service=current_user.service_department,
            content=content,
            author=current_user
        )
        db.session.add(msg)
        db.session.commit()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Empty content'}), 400
