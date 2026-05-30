from pathlib import Path
import os

# Directorio Base de Django
BASE_DIR = Path(__file__).resolve().parent.parent

# CONFIGURACIÓN DE SEGURIDAD PARA NGROK (DIRECTA Y FIJA)
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '.ngrok-free.app']

CSRF_TRUSTED_ORIGINS = [
    'https://5ca0-89-187-170-169.ngrok-free.app',
]

SECRET_KEY = 'django-insecure-!f*mkadok9skd&xtb1zgi=#+4q5)$0$0hns3mpl0h^qwb%w@g)'
DEBUG = True

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'gestion',
    'pagos',
    'reservas',
    'usuarios',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sportify_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')], 
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sportify_project.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Argentina/Buenos_Aires'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Configuración de tu modelo personalizado de usuario (CRUCIAL)
AUTH_USER_MODEL = 'usuarios.Usuario'

# Configuración de Emails
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'sportifygymapp@gmail.com'
EMAIL_HOST_PASSWORD = 'tzld pnbu rime agqp'

# Mercado Pago Credenciales
MERCADO_PAGO_ACCESS_TOKEN = 'APP_USR-1191378015015096-052421-decb977a309fc71a0e6f82bd01bb20a5-3423210053'
MERCADO_PAGO_PUBLIC_KEY = 'APP_USR-b4c892d6-5b01-4645-948a-e20b484f8f62'