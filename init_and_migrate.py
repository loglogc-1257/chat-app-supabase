import sqlite3
import os

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///users.db')

def get_db_connection():
    if DATABASE_URL.startswith('postgresql://') or DATABASE_URL.startswith('postgres://'):
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = True
            return conn
        except psycopg2.Error as e:
            print(f"❌ Erreur de connexion PostgreSQL: {e}")
            print("📝 Vérifiez que DATABASE_URL est correctement configuré")
            raise
    else:
        print("⚠️ Utilisation de SQLite - données non persistantes en production!")
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        return conn

def init_db_schema():
    conn = get_db_connection()
    cursor = conn.cursor()

    is_postgres = DATABASE_URL.startswith('postgresql://') or DATABASE_URL.startswith('postgres://')

    if is_postgres:
        # Schémas PostgreSQL
        print("🔧 Initialisation PostgreSQL...")

        # Table USERS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                username VARCHAR(255) NOT NULL,
                profile_picture_url VARCHAR(255),
                bio TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                theme_preference VARCHAR(10) DEFAULT 'light',
                notification_sound BOOLEAN DEFAULT TRUE
            )
        """)

        # Table ROOMS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                is_private BOOLEAN DEFAULT FALSE,
                creator_id INTEGER REFERENCES users(id),
                room_code VARCHAR(50) UNIQUE,
                max_members INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table ROOM_MEMBERS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_members (
                id SERIAL PRIMARY KEY,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (room_id, user_id)
            )
        """)

        # Table MESSAGES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                sender_id INTEGER NOT NULL REFERENCES users(id),
                content TEXT,
                media_url VARCHAR(500),
                voice_message_url VARCHAR(500),
                file_type VARCHAR(100),
                parent_message_id INTEGER REFERENCES messages(id),
                is_pinned BOOLEAN DEFAULT FALSE,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table PRIVATE_MESSAGES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS private_messages (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER NOT NULL REFERENCES users(id),
                receiver_id INTEGER NOT NULL REFERENCES users(id),
                content TEXT,
                media_url VARCHAR(500),
                voice_message_url VARCHAR(500),
                file_type VARCHAR(100),
                parent_message_id INTEGER REFERENCES private_messages(id),
                is_read BOOLEAN DEFAULT FALSE,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table REACTIONS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reactions (
                id SERIAL PRIMARY KEY,
                message_id INTEGER REFERENCES messages(id),
                private_message_id INTEGER REFERENCES private_messages(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                emoji VARCHAR(10) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table FRIEND_REQUESTS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS friend_requests (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER NOT NULL REFERENCES users(id),
                receiver_id INTEGER NOT NULL REFERENCES users(id),
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (sender_id, receiver_id)
            )
        """)

        # Table FRIENDS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                friend_id INTEGER NOT NULL REFERENCES users(id),
                established_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, friend_id)
            )
        """)

        # Table USER_PROFILE_LIKES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile_likes (
                id SERIAL PRIMARY KEY,
                liker_user_id INTEGER NOT NULL REFERENCES users(id),
                liked_user_id INTEGER NOT NULL REFERENCES users(id),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (liker_user_id, liked_user_id)
            )
        """)

        # Table USER_ACTIVITY
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                user_id INTEGER PRIMARY KEY REFERENCES users(id),
                last_active TIMESTAMP,
                is_online BOOLEAN DEFAULT FALSE,
                current_room_id INTEGER,
                status_message TEXT DEFAULT ''
            )
        """)

        # Index PostgreSQL
        indexes_postgres = [
            "CREATE INDEX IF NOT EXISTS idx_messages_room_timestamp ON messages(room_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_private_messages_users ON private_messages(sender_id, receiver_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_reactions_message ON reactions(message_id)",
            "CREATE INDEX IF NOT EXISTS idx_reactions_private ON reactions(private_message_id)",
            "CREATE INDEX IF NOT EXISTS idx_room_members ON room_members(room_id, user_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_activity ON user_activity(user_id, is_online)"
        ]

        for index_sql in indexes_postgres:
            try:
                cursor.execute(index_sql)
                print(f"  ✅ Index PostgreSQL créé")
            except Exception as e:
                print(f"  ⚠️ Index déjà existant: {e}")

    else:
        # Schémas SQLite (code existant)
        print("🔧 Initialisation SQLite...")

        # Créer/Mettre à jour la table USERS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                username TEXT NOT NULL,
                profile_picture_url TEXT DEFAULT NULL,
                bio TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                theme_preference TEXT DEFAULT 'light',
                notification_sound BOOLEAN DEFAULT 1
            )
        """)

        # Créer/Mettre à jour la table ROOMS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                is_private BOOLEAN DEFAULT 0,
                creator_id INTEGER,
                room_code TEXT UNIQUE,
                max_members INTEGER DEFAULT 100,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (creator_id) REFERENCES users (id)
            )
        """)

        # Créer/Mettre à jour la table ROOM_MEMBERS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES rooms (id),
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE (room_id, user_id)
            )
        """)

        # Créer/Mettre à jour la table MESSAGES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                content TEXT,
                media_url TEXT DEFAULT NULL,
                voice_message_url TEXT DEFAULT NULL,
                file_type TEXT DEFAULT NULL,
                parent_message_id INTEGER,
                is_pinned BOOLEAN DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES rooms (id),
                FOREIGN KEY (sender_id) REFERENCES users (id)
            )
        """)

        # Créer/Mettre à jour la table PRIVATE_MESSAGES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS private_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT,
                media_url TEXT DEFAULT NULL,
                voice_message_url TEXT DEFAULT NULL,
                file_type TEXT DEFAULT NULL,
                parent_message_id INTEGER,
                is_read BOOLEAN DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users (id),
                FOREIGN KEY (receiver_id) REFERENCES users (id)
            )
        """)

        # Créer/Mettre à jour la table REACTIONS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                private_message_id INTEGER,
                user_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (message_id) REFERENCES messages (id),
                FOREIGN KEY (private_message_id) REFERENCES private_messages (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Créer/Mettre à jour la table FRIEND_REQUESTS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS friend_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users (id),
                FOREIGN KEY (receiver_id) REFERENCES users (id),
                UNIQUE (sender_id, receiver_id)
            )
        """)

        # Créer/Mettre à jour la table FRIENDS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                friend_id INTEGER NOT NULL,
                established_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (friend_id) REFERENCES users (id),
                UNIQUE (user_id, friend_id)
            )
        """)

        # Créer/Mettre à jour la table USER_PROFILE_LIKES
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile_likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                liker_user_id INTEGER NOT NULL,
                liked_user_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (liker_user_id) REFERENCES users (id),
                FOREIGN KEY (liked_user_id) REFERENCES users (id),
                UNIQUE (liker_user_id, liked_user_id)
            )
        """)

        # Créer/Mettre à jour la table USER_ACTIVITY
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                user_id INTEGER PRIMARY KEY,
                last_active DATETIME,
                is_online BOOLEAN DEFAULT 0,
                current_room_id INTEGER,
                status_message TEXT DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Migration des colonnes SQLite
        print("🔧 Vérification et migration des colonnes existantes...")

        # Migration pour la table USERS
        cursor.execute("PRAGMA table_info(users);")
        user_columns = [col[1] for col in cursor.fetchall()]

        if 'profile_picture_url' not in user_columns:
            print("  ➕ Ajout de 'profile_picture_url' à la table users")
            cursor.execute("ALTER TABLE users ADD COLUMN profile_picture_url TEXT DEFAULT NULL;")
        if 'bio' not in user_columns:
            print("  ➕ Ajout de 'bio' à la table users")
            cursor.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT '';")
        if 'theme_preference' not in user_columns:
            print("  ➕ Ajout de 'theme_preference' à la table users")
            cursor.execute("ALTER TABLE users ADD COLUMN theme_preference TEXT DEFAULT 'light';")
        if 'notification_sound' not in user_columns:
            print("  ➕ Ajout de 'notification_sound' à la table users")
            cursor.execute("ALTER TABLE users ADD COLUMN notification_sound BOOLEAN DEFAULT 1;")

        # Migration pour les autres tables...
        # (Code de migration existant...)

        # Index SQLite
        indexes_sqlite = [
            "CREATE INDEX IF NOT EXISTS idx_messages_room_timestamp ON messages(room_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_private_messages_users ON private_messages(sender_id, receiver_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_reactions_message ON reactions(message_id)",
            "CREATE INDEX IF NOT EXISTS idx_reactions_private ON reactions(private_message_id)",
            "CREATE INDEX IF NOT EXISTS idx_room_members ON room_members(room_id, user_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_activity ON user_activity(user_id, is_online)"
        ]

        for index_sql in indexes_sqlite:
            try:
                cursor.execute(index_sql)
                print(f"  ✅ Index SQLite créé")
            except Exception as e:
                print(f"  ⚠️ Index déjà existant: {e}")

    conn.commit()
    conn.close()
    print("✅ Schéma de la base de données vérifié/créé avec succès.")

if __name__ == "__main__":
    # Assurez-vous que les dossiers d'uploads existent également
    UPLOAD_FOLDER = 'static/uploads'
    PROFILE_PICS_FOLDER = 'static/profile_pictures'
    VOICE_FOLDER = 'static/voice_messages'

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(PROFILE_PICS_FOLDER, exist_ok=True)
    os.makedirs(VOICE_FOLDER, exist_ok=True)
    print("📁 Dossiers d'uploads vérifiés/créés.")

    init_db_schema()
    print("🚀 Initialisation et migration de la base de données terminées.")
