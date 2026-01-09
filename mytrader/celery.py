import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mytrader.settings')

app = Celery('mytrader')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
