
# Déploiement sur Render

## Étapes de déploiement :

1. **Fork/Clone votre repo** sur GitHub

2. **Connectez Render à GitHub** :
   - Allez sur [render.com](https://render.com)
   - Connectez votre compte GitHub

3. **Créez un nouveau Web Service** :
   - Sélectionnez votre repository
   - Configurez les paramètres :

### Configuration Render :
```
Name: chat-app
Environment: Python 3
Build Command: pip install -r requirements.txt && python setup_database.py
Start Command: gunicorn -c gunicorn_config.py wsgi:application
```

### Variables d'environnement :
```
DATABASE_URL = postgresql://postgres:votre_mot_de_passe@db.xxx.supabase.co:5432/postgres
GEMINI_API_KEY = votre_cle_gemini
FLASK_SECRET_KEY = [généré automatiquement par Render]
```

4. **Déployez** en cliquant sur "Create Web Service"

## ✅ Avantages de cette configuration :

- **Persistance totale** : Données Supabase PostgreSQL
- **Performance** : Gunicorn + Gevent pour WebSockets
- **Scalabilité** : Support multi-utilisateurs
- **Sécurité** : Variables d'environnement sécurisées

Votre application sera accessible à l'URL fournie par Render après déploiement.
