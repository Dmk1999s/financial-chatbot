# Add these to your Django settings.py for better performance

# Cache Configuration
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            }
        },
        'TIMEOUT': 300,  # 5 minutes
    }
}

# Celery Configuration
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_ROUTES = {
    'chat.tasks.process_chat_async': {'queue': 'chat_queue'},
}

# Database Connection Pooling
DATABASES = {
    'default': {
        # ... your existing database config
        'CONN_MAX_AGE': 600,  # 10 minutes
        'OPTIONS': {
            'MAX_CONNS': 20,
            'MIN_CONNS': 5,
        }
    }
}

# Session Configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# Logging for Performance Monitoring
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'performance': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'performance.log',
        },
    },
    'loggers': {
        'chat.performance': {
            'handlers': ['performance'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}