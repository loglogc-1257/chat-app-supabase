
import os
from main import app, socketio

# Initialiser les dossiers nécessaires
UPLOAD_FOLDER = 'static/uploads'
PROFILE_PICS_FOLDER = 'static/profile_pictures'
VOICE_FOLDER = 'static/voice_messages'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PICS_FOLDER, exist_ok=True)
os.makedirs(VOICE_FOLDER, exist_ok=True)

# Initialiser la base de données
import init_and_migrate
init_and_migrate.init_db_schema()

# Point d'entrée pour les serveurs WSGI
application = socketio
"""
Point d'entrée WSGI pour le déploiement en production
"""

# Point d'entrée pour les serveurs WSGI (Render, Heroku, etc.)
application = socketio

if __name__ == "__main__":
    # Pour le développement local
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)=False)
