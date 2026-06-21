import os

# Robust environment loader
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ[key.strip()] = val.strip()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'rhim_phc_secret_key_129381023')
    # Default to SQLite local database if DATABASE_URL is not set
    DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///rhim_phc.db')
    
    # Supabase Configuration
    SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://fhzicqsekyccqknjwmuc.supabase.co/rest/v1/')
    SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY', 'sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX')
    
    # MediReach Integration Configuration
    MEDIREACH_API_URL = os.environ.get('MEDIREACH_API_URL', 'https://medireach-v2.onrender.com')
    
    # Session Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    
    # Shortage Calculation Constants
    CRITICAL_DAYS_THRESHOLD = 10
    WARNING_DAYS_THRESHOLD = 30

