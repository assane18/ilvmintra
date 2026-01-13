import os
from app import create_app, db
from app.models import User, Ticket, UserRole, ServiceType

app = create_app(os.getenv('FLASK_CONFIG') or 'default')

# Context Processor pour le shell flask
@app.shell_context_processor
def make_shell_context():
    return dict(db=db, User=User, Ticket=Ticket, UserRole=UserRole, ServiceType=ServiceType)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
