
# Guide de Déploiement - Chat App avec PostgreSQL

## 🎯 Objectif
Configurer une base de données PostgreSQL persistante pour éviter la perte de données lors des redéploiements.

## 📋 Prérequis

### 1. Base de données PostgreSQL
Vous devez avoir accès à une base de données PostgreSQL. Options recommandées :

#### Option A: PostgreSQL sur Replit (Recommandé)
1. Dans votre Repl, ouvrez l'outil **Database**
2. Sélectionnez **PostgreSQL**
3. Copiez l'URL de connexion fournie

#### Option B: Service externe
- **Render PostgreSQL** (gratuit avec limitations)
- **Supabase** (gratuit avec limitations)
- **ElephantSQL** (gratuit avec limitations)
- **AWS RDS** (payant)

### 2. Variables d'environnement requises

```bash
DATABASE_URL=postgresql://username:password@hostname:port/database_name
GEMINI_API_KEY=votre_cle_api_gemini_ici
```

## 🚀 Déploiement sur Render

### 1. Configuration des variables d'environnement
Dans votre tableau de bord Render :
1. Allez dans **Environment**
2. Ajoutez les variables suivantes :
   ```
   DATABASE_URL = postgresql://votre_url_complete
   GEMINI_API_KEY = AIzaSyAIf2_X5oFQRD1RCJSH1OGRhZuiL0C5wo8
   FLASK_SECRET_KEY = votre_cle_secrete_unique
   ```

### 2. Build Command
```bash
pip install -r requirements.txt && python setup_database.py
```

### 3. Start Command
```bash
gunicorn -c gunicorn_config.py wsgi:app
```

## 🔍 Vérification

### Test de connexion local
```bash
python setup_database.py
```

### Vérification en production
L'application affichera des logs de connexion au démarrage :
```
🔧 Initialisation PostgreSQL...
✅ Schéma de la base de données vérifié/créé avec succès.
```

## 🛡️ Sécurité

1. **Ne jamais** commiter les clés API dans le code
2. Utiliser des variables d'environnement pour toutes les données sensibles
3. Utiliser des mots de passe forts pour PostgreSQL
4. Activer SSL pour les connexions PostgreSQL en production

## 📊 Avantages de PostgreSQL

✅ **Persistance totale** - Aucune perte de données lors des redéploiements
✅ **Performance** - Meilleure que SQLite pour les applications multi-utilisateurs
✅ **Scalabilité** - Support de milliers d'utilisateurs simultanés
✅ **Fiabilité** - Transactions ACID, sauvegardes automatiques
✅ **Fonctionnalités avancées** - Index, contraintes, procédures stockées

## 🔧 Dépannage

### Erreur de connexion PostgreSQL
1. Vérifiez que DATABASE_URL est correctement formatée
2. Testez la connexion avec `python setup_database.py`
3. Vérifiez que psycopg2-binary est installé

### Migration depuis SQLite
Si vous avez des données existantes en SQLite, contactez le support pour assistance.

## 📞 Support
En cas de problème, vérifiez les logs de déploiement et les variables d'environnement.
