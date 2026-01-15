from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.models import Notification, TeamMessage, ServiceType
from app import db
from datetime import datetime

api_bp = Blueprint('api', __name__)

# --- NOTIFICATIONS ---

# Route principale (Liste + Count)
@api_bp.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    try:
        notifs = current_user.notifications.filter_by(is_read=False).order_by(Notification.timestamp.desc()).limit(10).all()
        count = current_user.notifications.filter_by(is_read=False).count()
        return jsonify({'count': count, 'notifications': [n.to_dict() for n in notifs]})
    except Exception as e:
        print(f"API NOTIF ERROR: {e}")
        return jsonify({'count': 0, 'notifications': []})

# Route spécifique COUNT (Ajoutée pour corriger l'erreur 404)
@api_bp.route('/api/notifications/count', methods=['GET'])
@login_required
def get_notifications_count():
    try:
        count = current_user.notifications.filter_by(is_read=False).count()
        return jsonify({'count': count})
    except Exception as e:
        return jsonify({'count': 0})

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

# --- TEAM CHAT ---

@api_bp.route('/api/team_chat', methods=['GET'])
@login_required
def get_team_messages():
    try:
        # CORRECTION : Utilisation de get_allowed_services() au lieu de service_department
        my_services = current_user.get_allowed_services()
        
        if not my_services:
            return jsonify([]) # Pas de service technique = Pas de chat
            
        main_service_name = my_services[0]
        
        # Recherche de l'Enum
        svc_enum = None
        for s in ServiceType:
            if s.value == main_service_name or s.name == main_service_name:
                svc_enum = s
                break
        
        if not svc_enum: 
            return jsonify([])

        messages = TeamMessage.query.filter_by(service=svc_enum)\
            .order_by(TeamMessage.timestamp.desc())\
            .limit(50).all()
        
        msgs_data = []
        for m in reversed(messages):
            d = {
                'id': m.id,
                'content': m.content,
                'user': m.author.fullname,
                'is_me': (m.author_id == current_user.id),
                'time': m.timestamp.strftime('%H:%M')
            }
            msgs_data.append(d)
            
        return jsonify(msgs_data)

    except Exception as e:
        print(f"CHAT ERROR (GET): {e}")
        return jsonify([])

@api_bp.route('/api/team_chat', methods=['POST'])
@login_required
def post_team_message():
    try:
        my_services = current_user.get_allowed_services()
        if not my_services:
            return jsonify({'error': 'No service'}), 403
            
        main_service_name = my_services[0]
        data = request.get_json()
        content = data.get('content')
        
        if not content:
            return jsonify({'error': 'Empty content'}), 400

        svc_enum = None
        for s in ServiceType:
            if s.value == main_service_name or s.name == main_service_name:
                svc_enum = s
                break
        
        if svc_enum:
            msg = TeamMessage(service=svc_enum, content=content, author=current_user)
            db.session.add(msg)
            db.session.commit()
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Invalid Service'}), 400

    except Exception as e:
        print(f"CHAT ERROR (POST): {e}")
        return jsonify({'error': 'Internal Error'}), 500
