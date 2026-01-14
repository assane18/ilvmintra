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

# --- TEAM CHAT (CORRIGÉ) ---

@api_bp.route('/api/team_chat', methods=['GET'])
@login_required
def get_team_messages():
    # CORRECTION : Utilisation de get_allowed_services() au lieu de service_department
    my_services = current_user.get_allowed_services()
    
    if not my_services:
        # Pas de service technique = Pas de chat d'équipe
        return jsonify([])
        
    # On prend le premier service autorisé comme canal principal pour le chat
    # (Pour l'instant, un user ne voit que le chat de son premier service technique)
    main_service_name = my_services[0]
    
    try:
        # On cherche l'Enum correspondant au nom du service (ex: "INFORMATIQUE")
        svc_enum = None
        for s in ServiceType:
            # On compare la valeur (value) de l'Enum avec le nom stocké dans la liste JSON
            if s.value == main_service_name:
                svc_enum = s
                break
        
        if not svc_enum: 
            return jsonify([])

        # Récupération des messages pour ce service
        messages = TeamMessage.query.filter_by(service=svc_enum)\
            .order_by(TeamMessage.timestamp.desc())\
            .limit(50).all()
        
        # Formatage pour le JSON
        msgs_data = []
        for m in reversed(messages):
            d = m.to_dict()
            d['is_me'] = (m.author_id == current_user.id)
            d['time'] = m.timestamp.strftime('%H:%M')
            msgs_data.append(d)
            
        return jsonify(msgs_data)
        
    except Exception as e:
        print(f"Chat Error: {e}")
        return jsonify([])

@api_bp.route('/api/team_chat', methods=['POST'])
@login_required
def post_team_message():
    my_services = current_user.get_allowed_services()
    if not my_services:
        return jsonify({'error': 'No service'}), 400
        
    main_service_name = my_services[0]
    data = request.get_json()
    content = data.get('content')
    
    if content:
        try:
            svc_enum = None
            for s in ServiceType:
                if s.value == main_service_name:
                    svc_enum = s
                    break
            
            if svc_enum:
                msg = TeamMessage(service=svc_enum, content=content, author=current_user)
                db.session.add(msg)
                db.session.commit()
                return jsonify({'success': True})
        except Exception as e:
            print(f"Chat Post Error: {e}")
            return jsonify({'error': 'Internal Error'}), 500
            
    return jsonify({'error': 'Empty content'}), 400
