
import os
import sys

def setup_postgresql():
    """Configure PostgreSQL pour une persistence des données"""
    
    print("🔧 Configuration de PostgreSQL Supabase pour la persistance des données...")
    
    # Variables d'environnement requises
    required_vars = {
        'DATABASE_URL': 'URL de connexion PostgreSQL Supabase',
        'GEMINI_API_KEY': 'Clé API Gemini pour l\'IA'
    }
    
    missing_vars = []
    for var, description in required_vars.items():
        if not os.environ.get(var):
            missing_vars.append(f"  - {var}: {description}")
    
    if missing_vars:
        print("❌ Variables d'environnement manquantes:")
        for var in missing_vars:
            print(var)
        print("\n📝 Configurez ces variables dans les Secrets Replit:")
        print("   DATABASE_URL=postgresql://postgres:password@db.xxx.supabase.co:5432/postgres")
        print("   GEMINI_API_KEY=votre_cle_api_gemini")
        return False
    
    # Test de connexion PostgreSQL
    try:
        try:
            import psycopg2
        except ImportError:
            print("📦 Installation de psycopg2-binary...")
            import subprocess
            subprocess.check_call(['pip', 'install', 'psycopg2-binary'])
            import psycopg2
            
        database_url = os.environ.get('DATABASE_URL')
        
        print(f"🔍 Test de connexion à Supabase PostgreSQL...")
        conn = psycopg2.connect(database_url)
        conn.close()
        print("✅ Connexion Supabase PostgreSQL réussie!")
        
        # Initialiser le schéma
        import init_and_migrate
        init_and_migrate.init_db_schema()
        
        print("🎉 Configuration Supabase PostgreSQL terminée avec succès!")
        print("📊 Vos données seront maintenant persistantes après redéploiement.")
        print("🚀 Supabase offre 500MB gratuits et haute disponibilité!")
        return True
        
    except Exception as e:
        print(f"❌ Erreur de connexion Supabase: {e}")
        print("🔧 Vérifiez votre DATABASE_URL Supabase")
        return False

if __name__ == "__main__":
    if setup_postgresql():
        print("\n🚀 Votre application est maintenant configurée pour la persistance des données!")
    else:
        print("\n⚠️ Configuration incomplète. Vérifiez les variables d'environnement.")
        sys.exit(1)
