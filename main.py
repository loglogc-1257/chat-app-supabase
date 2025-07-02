import sqlite3
import os
import uuid
import json
from datetime import datetime, timedelta
from functools import wraps
import time

from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "vraiment-secret-pour-dev")
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
UPLOAD_FOLDER = 'static/uploads'
PROFILE_PICS_FOLDER = 'static/profile_pictures'
VOICE_FOLDER = 'static/voice_messages'
ALLOWED_CHAT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'ogg', 'pdf', 'doc', 'docx', 'txt', 'zip', 'rar', 'mp3', 'wav'}
ALLOWED_PROFILE_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_FILE_SIZE = 50 * 1024 * 1024

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROFILE_PICS_FOLDER'] = PROFILE_PICS_FOLDER
app.config['VOICE_FOLDER'] = VOICE_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///users.db')

def get_db_connection():
    if DATABASE_URL.startswith('postgresql://') or DATABASE_URL.startswith('postgres://'):
        # PostgreSQL pour la production (Supabase)
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = True
            return conn
        except psycopg2.Error as e:
            print(f"❌ Erreur de connexion PostgreSQL: {e}")
            raise
    else:
        # SQLite pour le développement local uniquement
        print("⚠️ Utilisation de SQLite - données non persistantes en production!")
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        conn.row_factory = sqlite3.Row
        return conn

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vous devez être connecté pour accéder à cette page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def format_datetime(timestamp_str):
    if not timestamp_str:
        return ""
    try:
        dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        return timestamp_str

def allowed_chat_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_CHAT_EXTENSIONS

def allowed_profile_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_PROFILE_EXTENSIONS

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('rooms_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('rooms_dashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']

        if not username or not email or not password:
            flash('Tous les champs sont requis.', 'error')
            return render_template('register.html')

        hashed_password = generate_password_hash(password)
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                         (username, email, hashed_password))
            conn.commit()
            flash('Inscription réussie ! Vous pouvez maintenant vous connecter.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Cet email est déjà utilisé.', 'error')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('rooms_dashboard'))

    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            # Mettre à jour le statut en ligne
            conn = get_db_connection()
            conn.execute("INSERT OR REPLACE INTO user_activity (user_id, last_active, is_online) VALUES (?, CURRENT_TIMESTAMP, 1)", (user['id'],))
            conn.commit()
            conn.close()
            flash(f'Bienvenue, {user["username"]} !', 'success')
            return redirect(url_for('rooms_dashboard'))
        else:
            flash('Email ou mot de passe incorrect.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    user_id = session.pop('user_id', None)
    if user_id:
        conn = get_db_connection()
        conn.execute("UPDATE user_activity SET is_online = 0, last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        socketio.emit('user_status_changed', {'user_id': user_id, 'is_online': False})
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('login'))

@app.route('/rooms_dashboard')
@login_required
def rooms_dashboard():
    user_id = session['user_id']
    conn = get_db_connection()

    # Salons publics
    public_rooms = conn.execute("""
        SELECT r.id, r.name, r.description, u.username AS creator_username,
               (SELECT COUNT(*) FROM room_members rm WHERE rm.room_id = r.id) AS member_count
        FROM rooms r
        JOIN users u ON r.creator_id = u.id
        WHERE r.is_private = 0
        ORDER BY r.created_at DESC
    """).fetchall()

    # Salons privés créés par l'utilisateur
    private_rooms_created = conn.execute("""
        SELECT r.id, r.name, r.description, r.room_code, u.username AS creator_username,
               (SELECT COUNT(*) FROM room_members rm WHERE rm.room_id = r.id) AS member_count
        FROM rooms r
        JOIN users u ON r.creator_id = u.id
        WHERE r.creator_id = ? AND r.is_private = 1
        ORDER BY r.created_at DESC
    """, (user_id,)).fetchall()

    # Salons privés rejoints
    private_rooms_joined = conn.execute("""
        SELECT r.id, r.name, r.description, u.username AS creator_username,
               (SELECT COUNT(*) FROM room_members rm WHERE rm.room_id = r.id) AS member_count
        FROM rooms r
        JOIN users u ON r.creator_id = u.id
        JOIN room_members rm ON r.id = rm.room_id
        WHERE rm.user_id = ? AND r.is_private = 1 AND r.creator_id != ?
        ORDER BY r.created_at DESC
    """, (user_id, user_id)).fetchall()

    conn.close()
    return render_template('rooms_dashboard.html', 
                         public_rooms=public_rooms, 
                         private_rooms_created=private_rooms_created,
                         private_rooms_joined=private_rooms_joined)

@app.route('/create_room', methods=['POST'])
@login_required
def create_room():
    user_id = session['user_id']
    room_name = request.form['room_name'].strip()
    room_description = request.form.get('room_description', '').strip()
    is_private = 'is_private' in request.form

    if not room_name:
        flash('Le nom du salon ne peut pas être vide.', 'error')
        return redirect(url_for('rooms_dashboard'))

    conn = get_db_connection()
    try:
        room_code = None
        if is_private:
            room_code = str(uuid.uuid4())[:8].upper()

        cursor = conn.execute("INSERT INTO rooms (name, description, is_private, creator_id, room_code) VALUES (?, ?, ?, ?, ?)",
                             (room_name, room_description, is_private, user_id, room_code))
        room_id = cursor.lastrowid

        conn.execute("INSERT INTO room_members (room_id, user_id) VALUES (?, ?)", (room_id, user_id))
        conn.commit()
        flash(f'Salon "{room_name}" créé avec succès !', 'success')
        return redirect(url_for('chat', room_id=room_id))
    except sqlite3.IntegrityError:
        flash('Un salon avec ce nom existe déjà.', 'error')
    finally:
        conn.close()
    return redirect(url_for('rooms_dashboard'))

@app.route('/join_room/<int:room_id>')
@login_required
def join_room_direct(room_id):
    user_id = session['user_id']
    conn = get_db_connection()

    try:
        conn.execute("INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?)", (room_id, user_id))
        conn.commit()
        return redirect(url_for('chat', room_id=room_id))
    except Exception as e:
        flash(f'Erreur: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('rooms_dashboard'))

@app.route('/join_private_room', methods=['POST'])
@login_required
def join_private_room():
    user_id = session['user_id']
    room_code = request.form['room_code'].strip().upper()

    conn = get_db_connection()
    room = conn.execute("SELECT id, name FROM rooms WHERE room_code = ? AND is_private = 1", (room_code,)).fetchone()

    if not room:
        flash('Code de salon invalide.', 'error')
        conn.close()
        return redirect(url_for('rooms_dashboard'))

    try:
        conn.execute("INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?)", (room['id'], user_id))
        conn.commit()
        flash(f'Vous avez rejoint le salon "{room["name"]}" !', 'success')
        return redirect(url_for('chat', room_id=room['id']))
    except Exception as e:
        flash(f'Erreur: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('rooms_dashboard'))

@app.route('/chat/<int:room_id>')
@login_required
def chat(room_id):
    user_id = session['user_id']
    conn = get_db_connection()

    room = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        flash('Salon introuvable.', 'error')
        conn.close()
        return redirect(url_for('rooms_dashboard'))

    # Vérifier si l'utilisateur est membre
    is_member = conn.execute("SELECT 1 FROM room_members WHERE user_id = ? AND room_id = ?", (user_id, room_id)).fetchone()
    if not is_member:
        flash('Vous n\'êtes pas membre de ce salon.', 'error')
        conn.close()
        return redirect(url_for('rooms_dashboard'))

    # Déterminer le rôle de l'utilisateur
    user_role = 'member'
    if room['creator_id'] == user_id:
        user_role = 'creator'

    conn.close()
    return render_template('chat.html', room=room, current_user_id=user_id, user_role=user_role)

@app.route('/inbox')
@login_required
def inbox():
    user_id = session['user_id']
    conn = get_db_connection()

    conversations = conn.execute("""
        SELECT 
            CASE
                WHEN pm.sender_id = ? THEN pm.receiver_id
                ELSE pm.sender_id
            END AS other_user_id,
            u.username AS other_username,
            u.profile_picture_url AS other_profile_pic,
            pm.content AS last_message,
            pm.timestamp AS last_timestamp,
            (SELECT COUNT(*) FROM private_messages 
             WHERE receiver_id = ? AND sender_id = (CASE WHEN pm.sender_id = ? THEN pm.receiver_id ELSE pm.sender_id END) 
             AND is_read = 0) AS unread_count
        FROM private_messages pm
        JOIN users u ON u.id = CASE
                                    WHEN pm.sender_id = ? THEN pm.receiver_id
                                    ELSE pm.sender_id
                                END
        WHERE pm.sender_id = ? OR pm.receiver_id = ?
        GROUP BY other_user_id
        ORDER BY pm.timestamp DESC
    """, (user_id, user_id, user_id, user_id, user_id, user_id)).fetchall()

    conn.close()
    return render_template('inbox.html', conversations=conversations)

@app.route('/conversation/<int:other_user_id>')
@login_required
def conversation(other_user_id):
    user_id = session['user_id']
    conn = get_db_connection()

    other_user = conn.execute("SELECT username, profile_picture_url FROM users WHERE id = ?", (other_user_id,)).fetchone()
    if not other_user:
        flash('Utilisateur introuvable.', 'error')
        conn.close()
        return redirect(url_for('inbox'))

    # Marquer les messages comme lus
    conn.execute("UPDATE private_messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ?", (other_user_id, user_id))
    conn.commit()
    conn.close()

    return render_template('conversation.html', 
                         current_user_id=user_id,
                         other_user_id=other_user_id,
                         other_username=other_user['username'],
                         other_profile_pic=other_user['profile_picture_url'] or 'default_profile.png')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = session['user_id']
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    if request.method == 'POST':
        username = request.form['username'].strip()
        bio = request.form.get('bio', '').strip()
        theme_preference = request.form.get('theme_preference', 'light')
        notification_sound = 'notification_sound' in request.form

        profile_picture_url = user['profile_picture_url']

        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename and allowed_profile_file(file.filename):
                filename = secure_filename(str(uuid.uuid4()) + os.path.splitext(file.filename)[1])
                file_path = os.path.join(app.config['PROFILE_PICS_FOLDER'], filename)
                file.save(file_path)
                profile_picture_url = filename

        try:
            conn.execute("""UPDATE users SET username = ?, bio = ?, profile_picture_url = ?, 
                           theme_preference = ?, notification_sound = ? WHERE id = ?""",
                         (username, bio, profile_picture_url, theme_preference, notification_sound, user_id))
            conn.commit()
            flash('Profil mis à jour avec succès !', 'success')
        except sqlite3.IntegrityError:
            flash('Ce nom d\'utilisateur est déjà pris.', 'error')
        finally:
            conn.close()
        return redirect(url_for('profile'))

    conn.close()
    return render_template('profile.html', user=user)

@app.route('/user_profile/<int:user_id_param>')
@login_required
def user_profile(user_id_param):
    current_user_id = session['user_id']
    conn = get_db_connection()

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id_param,)).fetchone()
    if not user:
        flash('Utilisateur introuvable.', 'error')
        conn.close()
        return redirect(url_for('rooms_dashboard'))

    likes_count = conn.execute("SELECT COUNT(*) FROM user_profile_likes WHERE liked_user_id = ?", (user_id_param,)).fetchone()[0]
    is_liked = conn.execute("SELECT 1 FROM user_profile_likes WHERE liker_user_id = ? AND liked_user_id = ?", (current_user_id, user_id_param)).fetchone() is not None

    conn.close()
    return render_template('user_profile.html', 
                         user=user, 
                         likes_count=likes_count,
                         is_liked=is_liked,
                         is_own_profile=(current_user_id == user_id_param))

@app.route('/like_profile/<int:user_id_to_like>', methods=['POST'])
@login_required
def like_profile(user_id_to_like):
    current_user_id = session['user_id']

    if current_user_id == user_id_to_like:
        return jsonify({'success': False, 'error': 'Vous ne pouvez pas liker votre propre profil.'})

    conn = get_db_connection()
    existing_like = conn.execute("SELECT 1 FROM user_profile_likes WHERE liker_user_id = ? AND liked_user_id = ?", (current_user_id, user_id_to_like)).fetchone()

    if existing_like:
        conn.execute("DELETE FROM user_profile_likes WHERE liker_user_id = ? AND liked_user_id = ?", (current_user_id, user_id_to_like))
        action = 'unliked'
    else:
        conn.execute("INSERT INTO user_profile_likes (liker_user_id, liked_user_id) VALUES (?, ?)", (current_user_id, user_id_to_like))
        action = 'liked'

    conn.commit()
    likes_count = conn.execute("SELECT COUNT(*) FROM user_profile_likes WHERE liked_user_id = ?", (user_id_to_like,)).fetchone()[0]
    conn.close()

    return jsonify({'success': True, 'action': action, 'likes_count': likes_count})

@app.route('/api/ai_chat', methods=['POST'])
@login_required
def ai_chat():
    """Route pour l'IA chat avec Gemini"""
    data = request.get_json()
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'success': False, 'error': 'Message vide'})

    try:
        import requests

        gemini_api_key = os.environ.get('GEMINI_API_KEY', 'AIzaSyAIf2_X5oFQRD1RCJSH1OGRhZuiL0C5wo8')

        api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

        headers = {
            'Content-Type': 'application/json',
            'X-goog-api-key': gemini_api_key
        }

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": user_message
                        }
                    ]
                }
            ]
        }

        response = requests.post(api_url, json=payload, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            candidates = data.get('candidates', [])
            if candidates and candidates[0].get('content', {}).get('parts'):
                ai_response = candidates[0]['content']['parts'][0].get('text', '')
                if ai_response:
                    return jsonify({
                        'success': True, 
                        'response': ai_response.strip(),
                        'source': 'Gemini'
                    })

        return jsonify({'success': False, 'error': 'Erreur API Gemini'})

    except Exception as e:
        print(f"Erreur Gemini: {e}")
        return jsonify({'success': False, 'error': 'Erreur de connexion à Gemini'})

@app.route('/api/user_search', methods=['GET'])
@login_required
def user_search():
    """Recherche d'utilisateurs"""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])

    conn = get_db_connection()
    users = conn.execute("""
        SELECT id, username, profile_picture_url, bio
        FROM users 
        WHERE username LIKE ? AND id != ?
        LIMIT 10
    """, (f'%{query}%', session['user_id'])).fetchall()

    users_list = []
    for user in users:
        users_list.append({
            'id': user['id'],
            'username': user['username'],
            'profile_picture_url': user['profile_picture_url'] or 'default_profile.png',
            'bio': user['bio'] or ''
        })

    conn.close()
    return jsonify(users_list)

@app.route('/api/send_friend_request/<int:user_id>', methods=['POST'])
@login_required
def send_friend_request(user_id):
    """Envoyer une demande d'ami"""
    current_user_id = session['user_id']

    if current_user_id == user_id:
        return jsonify({'success': False, 'error': 'Vous ne pouvez pas vous envoyer une demande d\'ami'})

    conn = get_db_connection()

    # Vérifier si une demande existe déjà
    existing = conn.execute("""
        SELECT status FROM friend_requests 
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
    """, (current_user_id, user_id, user_id, current_user_id)).fetchone()

    if existing:
        if existing['status'] == 'pending':
            return jsonify({'success': False, 'error': 'Demande déjà envoyée'})
        elif existing['status'] == 'accepted':
            return jsonify({'success': False, 'error': 'Vous êtes déjà amis'})

    # Créer nouvelle demande
    conn.execute("""
        INSERT OR REPLACE INTO friend_requests (sender_id, receiver_id, status)
        VALUES (?, ?, 'pending')
    """, (current_user_id, user_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Demande d\'ami envoyée'})

@app.route('/api/friend_requests', methods=['GET'])
@login_required
def get_friend_requests():
    """Récupérer les demandes d'amis"""
    user_id = session['user_id']
    conn = get_db_connection()

    requests_list = conn.execute("""
        SELECT fr.id, fr.sender_id, u.username as sender_username, 
               u.profile_picture_url as sender_pic, fr.created_at
        FROM friend_requests fr
        JOIN users u ON fr.sender_id = u.id
        WHERE fr.receiver_id = ? AND fr.status = 'pending'
        ORDER BY fr.created_at DESC
    """, (user_id,)).fetchall()

    requests_data = []
    for req in requests_list:
        requests_data.append({
            'id': req['id'],
            'sender_id': req['sender_id'],
            'sender_username': req['sender_username'],
            'sender_pic': req['sender_pic'] or 'default_profile.png',
            'created_at': format_datetime(req['created_at'])
        })

    conn.close()
    return jsonify(requests_data)

@app.route('/api/respond_friend_request/<int:request_id>', methods=['POST'])
@login_required
def respond_friend_request(request_id):
    """Répondre à une demande d'ami"""
    data = request.get_json()
    action = data.get('action')  # 'accept' ou 'decline'

    if action not in ['accept', 'decline']:
        return jsonify({'success': False, 'error': 'Action invalide'})

    conn = get_db_connection()

    # Récupérer la demande
    friend_request = conn.execute("""
        SELECT sender_id, receiver_id FROM friend_requests 
        WHERE id = ? AND receiver_id = ? AND status = 'pending'
    """, (request_id, session['user_id'])).fetchone()

    if not friend_request:
        return jsonify({'success': False, 'error': 'Demande introuvable'})

    if action == 'accept':
        # Mettre à jour le statut
        conn.execute("UPDATE friend_requests SET status = 'accepted' WHERE id = ?", (request_id,))

        # Ajouter dans la table friends (relation bidirectionnelle)
        conn.execute("""
            INSERT OR IGNORE INTO friends (user_id, friend_id) VALUES (?, ?)
        """, (friend_request['sender_id'], friend_request['receiver_id']))

        conn.execute("""
            INSERT OR IGNORE INTO friends (user_id, friend_id) VALUES (?, ?)
        """, (friend_request['receiver_id'], friend_request['sender_id']))

        message = 'Demande acceptée'
    else:
        conn.execute("UPDATE friend_requests SET status = 'declined' WHERE id = ?", (request_id,))
        message = 'Demande refusée'

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': message})

@app.route('/api/friends', methods=['GET'])
@login_required
def get_friends():
    """Récupérer la liste des amis"""
    user_id = session['user_id']
    conn = get_db_connection()

    friends = conn.execute("""
        SELECT u.id, u.username, u.profile_picture_url, ua.is_online
        FROM friends f
        JOIN users u ON f.friend_id = u.id
        LEFT JOIN user_activity ua ON u.id = ua.user_id
        WHERE f.user_id = ?
        ORDER BY ua.is_online DESC, u.username ASC
    """, (user_id,)).fetchall()

    friends_list = []
    for friend in friends:
        friends_list.append({
            'id': friend['id'],
            'username': friend['username'],
            'profile_picture_url': friend['profile_picture_url'] or 'default_profile.png',
            'is_online': bool(friend['is_online'])
        })

    conn.close()
    return jsonify(friends_list)

@app.route('/upload_file', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Aucun fichier'})

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nom de fichier vide'})

    if file and allowed_chat_file(file.filename):
        filename = secure_filename(str(uuid.uuid4()) + os.path.splitext(file.filename)[1])
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        return jsonify({'success': True, 'file_url': url_for('static', filename='uploads/' + filename), 'file_type': file.mimetype})
    else:
        return jsonify({'success': False, 'error': 'Type de fichier non autorisé'})

@app.route('/upload_voice', methods=['POST'])
@login_required
def upload_voice():
    if 'audio' not in request.files:
        return jsonify({'success': False, 'error': 'Aucun audio'})

    audio_file = request.files['audio']
    if audio_file.filename == '':
        return jsonify({'success': False, 'error': 'Nom de fichier vide'})

    filename = secure_filename(f"{uuid.uuid4()}.wav")
    file_path = os.path.join(app.config['VOICE_FOLDER'], filename)
    audio_file.save(file_path)

    return jsonify({'success': True, 'voice_url': url_for('static', filename='voice_messages/' + filename)})

# API Routes
@app.route('/api/messages/<int:room_id>')
@login_required
def api_messages(room_id):
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)  # Limite plus petite par défaut
    limit = min(limit, 50)  # Maximum 50 messages par requête
    offset = (page - 1) * limit

    conn = get_db_connection()

    try:
        # Requête ultra optimisée - ne récupérer que l'essentiel
        messages = conn.execute("""
            SELECT m.id, m.sender_id, m.content, m.media_url, m.file_type,
                   m.voice_message_url, m.parent_message_id, 
                   strftime('%d/%m/%Y %H:%M', m.timestamp) as timestamp,
                   u.username AS sender_username, u.profile_picture_url AS sender_profile_pic
            FROM messages m
            INDEXED BY idx_messages_room_timestamp
            JOIN users u ON m.sender_id = u.id
            WHERE m.room_id = ?
            ORDER BY m.timestamp DESC
            LIMIT ? OFFSET ?
        """, (room_id, limit, offset)).fetchall()

        if not messages:
            conn.close()
            return jsonify([])

        message_ids = [msg['id'] for msg in messages]

        # Récupérer les messages parents en une requête
        parent_data = {}
        if any(msg['parent_message_id'] for msg in messages):
            parent_ids = [msg['parent_message_id'] for msg in messages if msg['parent_message_id']]
            if parent_ids:
                parents = conn.execute(f"""
                    SELECT m.id, m.content, u.username
                    FROM messages m
                    JOIN users u ON m.sender_id = u.id
                    WHERE m.id IN ({','.join(['?'] * len(parent_ids))})
                """, parent_ids).fetchall()

                for parent in parents:
                    parent_data[parent['id']] = {
                        'content': parent['content'],
                        'username': parent['username']
                    }

        # Récupérer les réactions de façon optimisée
        reactions_data = {}
        if message_ids and page == 1:  # Seulement pour la première page
            reactions = conn.execute(f"""
                SELECT r.message_id, r.emoji, COUNT(*) AS count,
                       GROUP_CONCAT(u.username, ', ') AS usernames
                FROM reactions r
                JOIN users u ON r.user_id = u.id
                WHERE r.message_id IN ({','.join(['?'] * len(message_ids))})
                GROUP BY r.message_id, r.emoji
                LIMIT 100
            """, message_ids).fetchall()

            for reaction in reactions:
                msg_id = reaction['message_id']
                if msg_id not in reactions_data:
                    reactions_data[msg_id] = []
                reactions_data[msg_id].append({
                    'emoji': reaction['emoji'],
                    'count': reaction['count'],
                    'usernames': reaction['usernames']
                })

        # Construire la réponse optimisée
        messages_list = []
        for msg in messages:
            msg_dict = {
                'id': msg['id'],
                'sender_id': msg['sender_id'],
                'content': msg['content'] or '',
                'media_url': msg['media_url'],
                'file_type': msg['file_type'],
                'voice_message_url': msg['voice_message_url'],
                'timestamp': msg['timestamp'],
                'sender_username': msg['sender_username'],
                'sender_profile_pic': msg['sender_profile_pic'],
                'reactions': reactions_data.get(msg['id'], [])
            }

            # Ajouter les données parent si disponibles
            if msg['parent_message_id'] and msg['parent_message_id'] in parent_data:
                parent = parent_data[msg['parent_message_id']]
                msg_dict['parent_content'] = parent['content']
                msg_dict['parent_username'] = parent['username']

            messages_list.append(msg_dict)

        conn.close()
        return jsonify(messages_list)

    except Exception as e:
        conn.close()
        print(f"Erreur API messages: {e}")
        return jsonify([]), 500

@app.route('/api/ping')
@login_required
def api_ping():
    """Endpoint simple pour tester la latence"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.route('/api/offline_mode')
@login_required
def offline_mode():
    """Mode hors ligne - données essentielles uniquement"""
    user_id = session['user_id']
    conn = get_db_connection()

    # Données ultra-compactes
    data = {
        'user': {
            'id': user_id,
            'username': conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()['username']
        },
        'unread_count': conn.execute(
            "SELECT COUNT(*) FROM private_messages WHERE receiver_id = ? AND is_read = 0", 
            (user_id,)
        ).fetchone()[0],
        'rooms': []
    }

    # Salons actifs seulement
    rooms = conn.execute("""
        SELECT r.id, r.name, COUNT(m.id) as msg_count
        FROM rooms r
        JOIN room_members rm ON r.id = rm.room_id
        LEFT JOIN messages m ON r.id = m.room_id AND m.timestamp >= datetime('now', '-1 day')
        WHERE rm.user_id = ?
        GROUP BY r.id, r.name
        ORDER BY msg_count DESC
        LIMIT 3
    """, (user_id,)).fetchall()

    for room in rooms:
        data['rooms'].append({
            'id': room['id'],
            'name': room['name'][:20],  # Limiter la longueur
            'activity': 'high' if room['msg_count'] > 10 else 'low'
        })

    conn.close()
    return jsonify(data)

@app.route('/api/conversations_light')
@login_required
def conversations_light():
    """Version ultra-légère des conversations"""
    user_id = session['user_id']
    conn = get_db_connection()

    conversations = conn.execute("""
        SELECT 
            CASE WHEN pm.sender_id = ? THEN pm.receiver_id ELSE pm.sender_id END as other_user_id,
            u.username,
            CASE 
                WHEN LENGTH(pm.content) > 30 THEN SUBSTR(pm.content, 1, 30) || '...'
                ELSE COALESCE(pm.content, '[Fichier]')
            END as preview,
            pm.timestamp,
            (SELECT COUNT(*) FROM private_messages 
             WHERE receiver_id = ? AND sender_id = (CASE WHEN pm.sender_id = ? THEN pm.receiver_id ELSE pm.sender_id END) 
             AND is_read = 0) as unread
        FROM private_messages pm
        JOIN users u ON u.id = CASE WHEN pm.sender_id = ? THEN pm.receiver_id ELSE pm.sender_id END
        WHERE pm.sender_id = ? OR pm.receiver_id = ?
        GROUP BY other_user_id
        ORDER BY pm.timestamp DESC
        LIMIT 10
    """, (user_id, user_id, user_id, user_id, user_id, user_id)).fetchall()

    result = []
    for conv in conversations:
        result.append({
            'id': conv['other_user_id'],
            'name': conv['username'][:15],  # Tronquer les noms longs
            'preview': conv['preview'],
            'time': conv['timestamp'][-5:] if conv['timestamp'] else '',  # Heure seulement
            'unread': min(conv['unread'], 99)  # Limiter à 99+
        })

    conn.close()
    return jsonify(result)

@app.route('/api/rooms_light')
@login_required
def rooms_light():
    """Version légère des salons"""
    user_id = session['user_id']
    conn = get_db_connection()

    rooms = conn.execute("""
        SELECT r.id, r.name, r.is_private,
               COUNT(rm.user_id) as members,
               COUNT(m.id) as recent_msgs
        FROM rooms r
        JOIN room_members rm_user ON r.id = rm_user.room_id AND rm_user.user_id = ?
        LEFT JOIN room_members rm ON r.id = rm.room_id
        LEFT JOIN messages m ON r.id = m.room_id AND m.timestamp >= datetime('now', '-6 hours')
        GROUP BY r.id, r.name, r.is_private
        ORDER BY recent_msgs DESC, r.created_at DESC
        LIMIT 15
    """, (user_id,)).fetchall()

    result = []
    for room in rooms:
        result.append({
            'id': room['id'],
            'name': room['name'][:20],
            'type': 'private' if room['is_private'] else 'public',
            'members': room['members'],
            'activity': 'high' if room['recent_msgs'] > 5 else 'normal'
        })

    conn.close()
    return jsonify(result)

@app.route('/api/private_messages/<int:other_user_id>')
@login_required
def api_private_messages(other_user_id):
    user_id = session['user_id']
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    limit = min(limit, 50)  # Maximum 50 messages par requête
    offset = (page - 1) * limit

    conn = get_db_connection()

    try:
        # Requête optimisée similaire aux messages de salon
        messages = conn.execute("""
            SELECT pm.id, pm.sender_id, pm.content, pm.media_url, pm.file_type,
                   pm.voice_message_url, pm.parent_message_id, 
                   strftime('%d/%m/%Y %H:%M', pm.timestamp) as timestamp,
                   u.username AS sender_username, u.profile_picture_url AS sender_profile_pic
            FROM private_messages pm
            JOIN users u ON pm.sender_id = u.id
            WHERE (pm.sender_id = ? AND pm.receiver_id = ?) OR (pm.sender_id = ? AND pm.receiver_id = ?)
            ORDER BY pm.timestamp DESC
            LIMIT ? OFFSET ?
        """, (user_id, other_user_id, other_user_id, user_id, limit, offset)).fetchall()

        if not messages:
            conn.close()
            return jsonify([])

        message_ids = [msg['id'] for msg in messages]

        # Récupérer les messages parents en une requête
        parent_data = {}
        if any(msg['parent_message_id'] for msg in messages):
            parent_ids = [msg['parent_message_id'] for msg in messages if msg['parent_message_id']]
            if parent_ids:
                parents = conn.execute(f"""
                    SELECT pm.id, pm.content, u.username
                    FROM private_messages pm
                    JOIN users u ON pm.sender_id = u.id
                    WHERE pm.id IN ({','.join(['?'] * len(parent_ids))})
                """, parent_ids).fetchall()

                for parent in parents:
                    parent_data[parent['id']] = {
                        'content': parent['content'],
                        'username': parent['username']
                    }

        # Récupérer les réactions de façon optimisée
        reactions_data = {}
        if message_ids and page == 1:  # Seulement pour la première page
            reactions = conn.execute(f"""
                SELECT r.private_message_id, r.emoji, COUNT(*) AS count,
                       GROUP_CONCAT(u.username, ', ') AS usernames
                FROM reactions r
                JOIN users u ON r.user_id = u.id
                WHERE r.private_message_id IN ({','.join(['?'] * len(message_ids))})
                GROUP BY r.private_message_id, r.emoji
                LIMIT 100
            """, message_ids).fetchall()

            for reaction in reactions:
                msg_id = reaction['private_message_id']
                if msg_id not in reactions_data:
                    reactions_data[msg_id] = []
                reactions_data[msg_id].append({
                    'emoji': reaction['emoji'],
                    'count': reaction['count'],
                    'usernames': reaction['usernames']
                })

        # Construire la réponse optimisée
        messages_list = []
        for msg in messages:
            msg_dict = {
                'id': msg['id'],
                'sender_id': msg['sender_id'],
                'receiver_id': other_user_id if msg['sender_id'] == user_id else user_id,
                'content': msg['content'] or '',
                'media_url': msg['media_url'],
                'file_type': msg['file_type'],
                'voice_message_url': msg['voice_message_url'],
                'timestamp': msg['timestamp'],
                'sender_username': msg['sender_username'],
                'sender_profile_pic': msg['sender_profile_pic'] or 'default_profile.png',
                'reactions': reactions_data.get(msg['id'], [])
            }

            # Ajouter les données parent si disponibles
            if msg['parent_message_id'] and msg['parent_message_id'] in parent_data:
                parent = parent_data[msg['parent_message_id']]
                msg_dict['parent_content'] = parent['content']
                msg_dict['parent_username'] = parent['username']

            messages_list.append(msg_dict)

        conn.close()
        return jsonify(messages_list)

    except Exception as e:
        conn.close()
        print(f"Erreur API messages privés: {e}")
        return jsonify([]), 500

@app.route('/api/room_members/<int:room_id>')
@login_required
def api_room_members(room_id):
    conn = get_db_connection()
    members = conn.execute("""
        SELECT u.id, u.username, u.profile_picture_url, ua.is_online, ua.last_active
        FROM room_members rm
        JOIN users u ON rm.user_id = u.id
        LEFT JOIN user_activity ua ON u.id = ua.user_id
        WHERE rm.room_id = ?
        ORDER BY ua.is_online DESC, u.username ASC
    """, (room_id,)).fetchall()

    members_list = []
    for member in members:
        member_dict = dict(member)
        member_dict['profile_picture_url'] = member_dict['profile_picture_url'] or 'default_profile.png'
        members_list.append(member_dict)

    conn.close()
    return jsonify(members_list)

@app.route('/api/delete_room/<int:room_id>', methods=['DELETE'])
@login_required
def api_delete_room(room_id):
    user_id = session['user_id']
    conn = get_db_connection()

    # Vérifier que l'utilisateur est le créateur
    room = conn.execute("SELECT creator_id FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room or room['creator_id'] != user_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Vous n\'êtes pas autorisé à supprimer ce salon'})

    try:
        # Supprimer toutes les données associées
        conn.execute("DELETE FROM reactions WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)", (room_id,))
        conn.execute("DELETE FROM messages WHERE room_id = ?", (room_id,))
        conn.execute("DELETE FROM room_members WHERE room_id = ?", (room_id,))
        conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/kick_member/<int:room_id>/<int:member_id>', methods=['POST'])
@login_required
def api_kick_member(room_id, member_id):
    user_id = session['user_id']
    conn = get_db_connection()

    # Vérifier que l'utilisateur est le créateur
    room = conn.execute("SELECT creator_id FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room or room['creator_id'] != user_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Vous n\'êtes pas autorisé à expulser des membres'})

    # Ne pas permettre de s'auto-expulser
    if member_id == user_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Vous ne pouvez pas vous expulser vous-même'})

    try:
        conn.execute("DELETE FROM room_members WHERE room_id = ? AND user_id = ?", (room_id, member_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear_room_messages/<int:room_id>', methods=['DELETE'])
@login_required
def api_clear_room_messages(room_id):
    user_id = session['user_id']
    conn = get_db_connection()

    # Vérifier que l'utilisateur est le créateur
    room = conn.execute("SELECT creator_id FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room or room['creator_id'] != user_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Vous n\'êtes pas autorisé à nettoyer ce salon'})

    try:
        # Supprimer les réactions puis les messages
        conn.execute("DELETE FROM reactions WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)", (room_id,))
        conn.execute("DELETE FROM messages WHERE room_id = ?", (room_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/toggle_pin_message/<int:message_id>', methods=['POST'])
@login_required
def api_toggle_pin_message(message_id):
    user_id = session['user_id']
    data = request.get_json()
    is_pinned = data.get('is_pinned', False)

    conn = get_db_connection()

    # Vérifier que l'utilisateur est créateur du salon
    message = conn.execute("""
        SELECT m.room_id, r.creator_id 
        FROM messages m 
        JOIN rooms r ON m.room_id = r.id 
        WHERE m.id = ?
    """, (message_id,)).fetchone()

    if not message or message['creator_id'] != user_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Vous n\'êtes pas autorisé à épingler des messages'})

    try:
        conn.execute("UPDATE messages SET is_pinned = ? WHERE id = ?", (is_pinned, message_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/pinned_messages/<int:room_id>')
@login_required
def api_pinned_messages(room_id):
    conn = get_db_connection()
    messages = conn.execute("""
        SELECT m.id, m.content, m.timestamp, u.username as sender_username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.room_id = ? AND m.is_pinned = 1
        ORDER BY m.timestamp DESC
    """, (room_id,)).fetchall()

    messages_list = [dict(msg) for msg in messages]
    conn.close()
    return jsonify(messages_list)

@app.route('/api/delete_message/<int:message_id>', methods=['DELETE'])
@login_required
def api_delete_message(message_id):
    user_id = session['user_id']
    conn = get_db_connection()

    # Vérifier les permissions (créateur du message ou créateur du salon)
    message = conn.execute("""
        SELECT m.sender_id, m.room_id, r.creator_id 
        FROM messages m 
        JOIN rooms r ON m.room_id = r.id 
        WHERE m.id = ?
    """, (message_id,)).fetchone()

    if not message:
        conn.close()
        return jsonify({'success': False, 'error': 'Message introuvable'})

    if message['sender_id'] != user_id and message['creator_id'] != user_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Vous n\'êtes pas autorisé à supprimer ce message'})

    try:
        # Supprimer les réactions puis le message
        conn.execute("DELETE FROM reactions WHERE message_id = ?", (message_id,))
        conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_private_message/<int:message_id>', methods=['DELETE'])
@login_required
def api_delete_private_message(message_id):
    user_id = session['user_id']
    conn = get_db_connection()

    # Vérifier que l'utilisateur est l'expéditeur du message
    message = conn.execute("""
        SELECT sender_id FROM private_messages WHERE id = ?
    """, (message_id,)).fetchone()

    if not message:
        conn.close()
        return jsonify({'success': False, 'error': 'Message introuvable'})

    if message['sender_id'] != user_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Vous ne pouvez supprimer que vos propres messages'})

    try:
        # Supprimer les réactions puis le message privé
        conn.execute("DELETE FROM reactions WHERE private_message_id = ?", (message_id,))
        conn.execute("DELETE FROM private_messages WHERE id = ?", (message_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user_id = session['user_id']
        join_room(f'user_{user_id}')
        conn = get_db_connection()
        conn.execute("INSERT OR REPLACE INTO user_activity (user_id, last_active, is_online) VALUES (?, CURRENT_TIMESTAMP, 1)", (user_id,))
        conn.commit()
        conn.close()
        emit('user_status_changed', {'user_id': user_id, 'is_online': True}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        user_id = session['user_id']
        conn = get_db_connection()
        conn.execute("UPDATE user_activity SET is_online = 0, last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        emit('user_status_changed', {'user_id': user_id, 'is_online': False}, broadcast=True)

@socketio.on('join_room')
def on_join(data):
    user_id = session.get('user_id')
    room_id = data.get('room_id')
    if user_id and room_id:
        join_room(f'room_{room_id}')
        emit('members_updated', room=f'room_{room_id}')

@socketio.on('leave_room')
def on_leave(data):
    user_id = session.get('user_id')
    room_id = data.get('room_id')
    if user_id and room_id:
        leave_room(f'room_{room_id}')
        emit('members_updated', room=f'room_{room_id}')

@socketio.on('send_message')
def handle_send_message(data):
    user_id = session.get('user_id')
    if not user_id:
        return

    room_id = data.get('room_id')
    content = data.get('content')
    media_url = data.get('media_url')
    file_type = data.get('file_type')
    voice_url = data.get('voice_url')
    parent_id = data.get('parent_id')

    if not (content or media_url or voice_url):
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (room_id, sender_id, content, media_url, file_type, voice_message_url, parent_message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (room_id, user_id, content, media_url, file_type, voice_url, parent_id))
    message_id = cursor.lastrowid
    conn.commit()

    sender = conn.execute("SELECT username, profile_picture_url FROM users WHERE id = ?", (user_id,)).fetchone()

    message_data = {
        'id': message_id,
        'room_id': room_id,
        'sender_id': user_id,
        'content': content,
        'media_url': media_url,
        'file_type': file_type,
        'voice_message_url': voice_url,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sender_username': sender['username'],
        'sender_profile_pic': sender['profile_picture_url'] or 'default_profile.png',
        'parent_message_id': parent_id,
        'reactions': []
    }

    conn.close()
    emit('new_message', message_data, room=f'room_{room_id}')

@socketio.on('send_private_message')
def handle_send_private_message(data):
    user_id = session.get('user_id')
    if not user_id:
        return

    receiver_id = data.get('receiver_id')
    content = data.get('content')
    media_url = data.get('media_url')
    file_type = data.get('file_type')
    voice_url = data.get('voice_url')
    parent_id = data.get('parent_id')

    if not (content or media_url or voice_url):
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO private_messages (sender_id, receiver_id, content, media_url, file_type, voice_message_url, parent_message_id, is_read)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    """, (user_id, receiver_id, content, media_url, file_type, voice_url, parent_id))
    message_id = cursor.lastrowid
    conn.commit()

    sender = conn.execute("SELECT username, profile_picture_url FROM users WHERE id = ?", (user_id,)).fetchone()

    message_data = {
        'id': message_id,
        'sender_id': user_id,
        'receiver_id': receiver_id,
        'content': content,
        'media_url': media_url,
        'file_type': file_type,
        'voice_message_url': voice_url,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sender_username': sender['username'],
        'sender_profile_pic': sender['profile_picture_url'] or 'default_profile.png',
        'parent_message_id': parent_id,
        'reactions': []
    }

    conn.close()
    emit('new_private_message', message_data, room=f'user_{user_id}')
    emit('new_private_message', message_data, room=f'user_{receiver_id}')

@socketio.on('add_reaction')
def handle_add_reaction(data):
    user_id = session.get('user_id')
    message_id = data.get('message_id')
    room_id = data.get('room_id')
    emoji = data.get('emoji')
    is_private = data.get('is_private', False)

    conn = get_db_connection()

    if is_private:
        existing = conn.execute("SELECT id FROM reactions WHERE user_id = ? AND private_message_id = ? AND emoji = ?", 
                               (user_id, message_id, emoji)).fetchone()
        if existing:
            conn.execute("DELETE FROM reactions WHERE id = ?", (existing['id'],))
        else:
            conn.execute("INSERT INTO reactions (user_id, private_message_id, emoji) VALUES (?, ?, ?)", 
                        (user_id, message_id, emoji))
    else:
        existing = conn.execute("SELECT id FROM reactions WHERE user_id = ? AND message_id = ? AND emoji = ?", 
                               (user_id, message_id, emoji)).fetchone()
        if existing:
            conn.execute("DELETE FROM reactions WHERE id = ?", (existing['id'],))
        else:
            conn.execute("INSERT INTO reactions (user_id, message_id, emoji) VALUES (?, ?, ?)", 
                        (user_id, message_id, emoji))

    conn.commit()

    # Récupérer les réactions mises à jour
    if is_private:
        reactions = conn.execute("""
            SELECT r.emoji, GROUP_CONCAT(u.username) AS usernames, COUNT(*) AS count
            FROM reactions r
            JOIN users u ON r.user_id = u.id
            WHERE r.private_message_id = ?
            GROUP BY r.emoji
        """, (message_id,)).fetchall()
        emit('private_message_reacted', {'message_id': message_id, 'reactions': [dict(r) for r in reactions]}, 
             room=f'user_{user_id}')
        emit('private_message_reacted', {'message_id': message_id, 'reactions': [dict(r) for r in reactions]}, 
             room=f'user_{data.get("receiver_id")}')
    else:
        reactions = conn.execute("""
            SELECT r.emoji, GROUP_CONCAT(u.username) AS usernames, COUNT(*) AS count
            FROM reactions r
            JOIN users u ON r.user_id = u.id
            WHERE r.message_id = ?
            GROUP BY r.emoji
        """, (message_id,)).fetchall()
        emit('message_reacted', {'message_id': message_id, 'reactions': [dict(r) for r in reactions]}, 
             room=f'room_{room_id}')

    conn.close()

@socketio.on('typing')
def handle_typing(data):
    user_id = session.get('user_id')
    room_id = data.get('room_id')
    is_typing = data.get('is_typing')

    if user_id and room_id:
        conn = get_db_connection()
        username = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()['username']
        conn.close()
        emit('typing_status', {'user_id': user_id, 'username': username, 'is_typing': is_typing}, 
             room=f'room_{room_id}', skip_sid=request.sid)

@socketio.on('private_typing')
def handle_private_typing(data):
    user_id = session.get('user_id')
    receiver_id = data.get('receiver_id')
    is_typing = data.get('is_typing')

    if user_id and receiver_id:
        conn = get_db_connection()
        username = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()['username']
        conn.close()
        emit('private_typing_status', {'user_id': user_id, 'username': username, 'is_typing': is_typing}, 
             room=f'user_{receiver_id}')

@app.route('/friends')
@login_required
def friends():
    return render_template('friends.html')

@app.route('/api/room_stats/<int:room_id>')
@login_required
def room_stats(room_id):
    """Statistiques d'un salon"""
    conn = get_db_connection()

    # Vérifier l'accès au salon
    is_member = conn.execute("SELECT 1 FROM room_members WHERE user_id = ? AND room_id = ?", 
                             (session['user_id'], room_id)).fetchone()
    if not is_member:
        return jsonify({'error': 'Accès refusé'}), 403

    stats = {}

    # Messages par jour (7 derniers jours)
    stats['messages_per_day'] = conn.execute("""
        SELECT DATE(timestamp) as date, COUNT(*) as count
        FROM messages 
        WHERE room_id = ? AND timestamp >= datetime('now', '-7 days')
        GROUP BY DATE(timestamp)
        ORDER BY date
    """, (room_id,)).fetchall()

    # Top utilisateurs actifs
    stats['top_users'] = conn.execute("""
        SELECT u.username, COUNT(*) as message_count
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.room_id = ? AND m.timestamp >= datetime('now', '-30 days')
        GROUP BY u.username
        ORDER BY message_count DESC
        LIMIT 5
    """, (room_id,)).fetchall()

    # Total messages
    stats['total_messages'] = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE room_id = ?", (room_id,)
    ).fetchone()[0]

    # Membres actifs aujourd'hui
    stats['active_today'] = conn.execute("""
        SELECT COUNT(DISTINCT sender_id) 
        FROM messages 
        WHERE room_id = ? AND DATE(timestamp) = DATE('now')
    """, (room_id,)).fetchone()[0]

    conn.close()
    return jsonify(stats)

@app.route('/api/user_activity')
@login_required
def user_activity():
    """Activité de l'utilisateur connecté"""
    user_id = session['user_id']
    conn = get_db_connection()

    activity = {}

    # Messages envoyés (7 derniers jours)
    activity['messages_sent'] = conn.execute("""
        SELECT COUNT(*) FROM messages 
        WHERE sender_id = ? AND timestamp >= datetime('now', '-7 days')
    """, (user_id,)).fetchone()[0]

    # Messages privés (7 derniers jours)
    activity['private_messages'] = conn.execute("""
        SELECT COUNT(*) FROM private_messages 
        WHERE sender_id = ? AND timestamp >= datetime('now', '-7 days')
    """, (user_id,)).fetchone()[0]

    # Salons rejoints
    activity['rooms_joined'] = conn.execute("""
        SELECT COUNT(*) FROM room_members WHERE user_id = ?
    """, (user_id,)).fetchone()[0]

    # Amis
    activity['friends_count'] = conn.execute("""
        SELECT COUNT(*) FROM friends WHERE user_id = ?
    """, (user_id,)).fetchone()[0]

    conn.close()
    return jsonify(activity)

@app.route('/api/global_stats')
@login_required
def global_stats():
    """Statistiques globales de la plateforme"""
    conn = get_db_connection()

    stats = {}

    # Total utilisateurs
    stats['total_users'] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # Utilisateurs en ligne
    stats['online_users'] = conn.execute(
        "SELECT COUNT(*) FROM user_activity WHERE is_online = 1"
    ).fetchone()[0]

    # Total salons
    stats['total_rooms'] = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]

    # Messages aujourd'hui
    stats['messages_today'] = conn.execute("""
        SELECT COUNT(*) FROM messages 
        WHERE DATE(timestamp) = DATE('now')
    """).fetchone()[0]

    # Top salon le plus actif
    top_room = conn.execute("""
        SELECT r.name, COUNT(*) as msg_count
        FROM messages m
        JOIN rooms r ON m.room_id = r.id
        WHERE m.timestamp >= datetime('now', '-7 days')
        GROUP BY r.id, r.name
        ORDER BY msg_count DESC
        LIMIT 1
    """).fetchone()

    stats['top_room'] = dict(top_room) if top_room else None

    conn.close()
    return jsonify(stats)

@app.route('/api/quick_actions', methods=['POST'])
@login_required
def quick_actions():
    """Actions rapides (statut, thème, etc.)"""
    data = request.get_json()
    action = data.get('action')
    user_id = session['user_id']

    conn = get_db_connection()

    if action == 'toggle_status':
        # Basculer le statut en ligne/hors ligne
        current = conn.execute(
            "SELECT is_online FROM user_activity WHERE user_id = ?", (user_id,)
        ).fetchone()

        new_status = not bool(current['is_online']) if current else True
        conn.execute("""
            INSERT OR REPLACE INTO user_activity (user_id, is_online, last_active)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (user_id, new_status))

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'new_status': new_status})

    elif action == 'set_status_message':
        # Définir un message de statut
        message = data.get('message', '')
        conn.execute("""
            UPDATE user_activity SET status_message = ? WHERE user_id = ?
        """, (message, user_id))

        conn.commit()
        conn.close()
        return jsonify({'success': True})

    elif action == 'toggle_theme':
        # Basculer le thème
        current_theme = conn.execute(
            "SELECT theme_preference FROM users WHERE id = ?", (user_id,)
        ).fetchone()['theme_preference']

        new_theme = 'dark' if current_theme == 'light' else 'light'
        conn.execute("UPDATE users SET theme_preference = ? WHERE id = ?", (new_theme, user_id))

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'new_theme': new_theme})

    conn.close()
    return jsonify({'success': False, 'error': 'Action inconnue'})

@app.route('/api/notifications')
@login_required
def get_notifications():
    """Récupérer les notifications"""
    user_id = session['user_id']
    conn = get_db_connection()

    notifications = []

    # Demandes d'amis en attente
    friend_requests = conn.execute("""
        SELECT fr.id, u.username, fr.created_at
        FROM friend_requests fr
        JOIN users u ON fr.sender_id = u.id
        WHERE fr.receiver_id = ? AND fr.status = 'pending'
        ORDER BY fr.created_at DESC
        LIMIT 5
    """, (user_id,)).fetchall()

    for req in friend_requests:
        notifications.append({
            'type': 'friend_request',
            'id': req['id'],
            'title': 'Nouvelle demande d\'ami',
            'message': f'{req["username"]} vous a envoyé une demande d\'ami',
            'time': format_datetime(req['created_at']),
            'icon': 'fa-user-plus'
        })

    # Messages non lus
    unread_count = conn.execute("""
        SELECT COUNT(*) FROM private_messages 
        WHERE receiver_id = ? AND is_read = 0
    """, (user_id,)).fetchone()[0]

    if unread_count > 0:
        notifications.append({
            'type': 'messages',
            'title': 'Messages non lus',
            'message': f'Vous avez {unread_count} message(s) non lu(s)',
            'time': 'Maintenant',
            'icon': 'fa-envelope'
        })

    conn.close()
    return jsonify(notifications)

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(PROFILE_PICS_FOLDER, exist_ok=True)
    os.makedirs(VOICE_FOLDER, exist_ok=True)

    # Initialiser la base de données
    import init_and_migrate
    init_and_migrate.init_db_schema()

    # Configuration pour déploiement
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('REPLIT_DEPLOYMENT') != '1'

    socketio.run(app, host='0.0.0.0', port=port, debug=debug_mode)
