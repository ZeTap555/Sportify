import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sportify_project.settings')
import django
django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS.append('testserver')
from django.test import Client
from django.urls import reverse
from usuarios.models import Usuario
from gestion.models import Clase, SuspensionClase, Reserva, Actividad, Profesor
from datetime import date, time, timedelta

admin = Usuario.objects.get(username='admin')

act = Actividad.objects.filter(nombre__startswith='TestSuspension').first()
clase = Clase.objects.filter(actividad=act).first()
fecha_str = (date.today() + timedelta(days=3)).strftime('%Y-%m-%d')
fecha_obj = (date.today() + timedelta(days=3))

# Check what's in the DB
print(f'Clase ID: {clase.id}')
print(f'Fecha str: {fecha_str}')
print(f'Fecha obj: {fecha_obj}')

# Check suspension
susp = SuspensionClase.objects.filter(clase=clase, fecha=fecha_obj).first()
print(f'Suspension exists: {susp is not None}')
if susp:
    print(f'  Suspension fecha: {susp.fecha}')
    print(f'  Suspension fecha type: {type(susp.fecha)}')
    print(f'  fecha_obj type: {type(fecha_obj)}')
    print(f'  Match: {susp.fecha == fecha_obj}')

# Now call the API
c = Client()
c.force_login(admin)
resp = c.get(f'/clase/{clase.id}/datos/?fecha={fecha_str}')
data = resp.json()
print(f'API response: suspendida={data["suspendida"]}, motivo={data["motivo_suspension"]}')
