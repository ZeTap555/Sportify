import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sportify_project.settings')
import django
django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS.append('testserver')
from django.test import Client
from django.urls import reverse
from usuarios.models import Usuario
from gestion.models import Clase, SuspensionClase, Reserva, Notificacion, Voucher

admin = Usuario.objects.get(username='admin')

from gestion.models import Actividad, Profesor
from datetime import date, time, timedelta

# Clean previous test data
Actividad.objects.filter(nombre__startswith='TestSuspension').delete()

act = Actividad.objects.create(nombre='TestSuspensionYoga', precio_clase=3500, precio_mensualidad=15000)
prof_usuario = Usuario.objects.create_user(username='test_profe', dni='99999998', password='123', rol='profesor', email='profe_test@test.com')
prof = Profesor.objects.create(usuario=prof_usuario, nombre='Test', apellido='Prof', dni='99999998', correo='profe_test@test.com')
clase = Clase.objects.create(actividad=act, profesor=prof, fecha=date.today() + timedelta(days=3), horario=time(10, 0), cupo_maximo=30)

fecha_str = (date.today() + timedelta(days=3)).strftime('%Y-%m-%d')
fecha_obj = (date.today() + timedelta(days=3))

cliente1 = Usuario.objects.create_user(username='test_cli1', dni='11111110', password='123', rol='cliente', email='cli1_test@test.com')
cliente2 = Usuario.objects.create_user(username='test_cli2', dni='22222220', password='123', rol='cliente', email='cli2_test@test.com')

res1 = Reserva.objects.create(usuario=cliente1, clase=clase, fecha_clase=fecha_obj, modalidad='individual', monto_pagado=3500, estado_pago='total')
res2 = Reserva.objects.create(usuario=cliente2, clase=clase, fecha_clase=fecha_obj, modalidad='mensual', monto_pagado=15000, estado_pago='total')

c = Client()
c.force_login(admin)

# TEST 1: API before
print('=== TEST 1: API inicial ===')
resp = c.get(f'/clase/{clase.id}/datos/?fecha={fecha_str}')
data = resp.json()
print(f'  suspendida: {data["suspendida"]}, motivo_suspension: "{data["motivo_suspension"]}"')
assert data['suspendida'] == False
assert data['motivo_suspension'] == ''
print('  PASS')

# TEST 2: Suspend
print('\n=== TEST 2: Suspender ===')
url = reverse('suspender_clase', args=[clase.id])
resp = c.post(url, {'fecha': fecha_str, 'motivo': 'profesor_ausente', 'comentario': 'Se enfermo'})
assert resp.status_code == 302
assert resp.url == reverse('grilla_actividades')
susp = SuspensionClase.objects.filter(clase=clase, fecha=fecha_obj).first()
assert susp is not None
print(f'  Suspension creada: motivo={susp.motivo}')
print('  PASS')

# TEST 3: Reservas deleted, notifications sent
print('\n=== TEST 3: Reservas y notificaciones ===')
reservas_count = Reserva.objects.filter(clase=clase, fecha_clase=fecha_obj).count()
assert reservas_count == 0
print(f'  Reservas eliminadas: OK')

notifs = Notificacion.objects.filter(usuario__in=[cliente1, cliente2, prof_usuario])
assert notifs.count() == 3
print(f'  Notificaciones: {notifs.count()}')

vouchers = Voucher.objects.filter(cliente=cliente2)
assert vouchers.count() == 1
print(f'  Voucher mensual: {vouchers.count()}')
print('  PASS')

# TEST 4: API after suspension
print('\n=== TEST 4: API despues ===')
resp2 = c.get(f'/clase/{clase.id}/datos/?fecha={fecha_str}')
data2 = resp2.json()
print(f'  suspendida: {data2["suspendida"]}, motivo_suspension: "{data2["motivo_suspension"]}"')
assert data2['suspendida'] == True
assert 'Profesor ausente' in data2['motivo_suspension']
print('  PASS')

# TEST 5: Duplicate prevented
print('\n=== TEST 5: Duplicado ===')
resp3 = c.post(url, {'fecha': fecha_str, 'motivo': 'feriado'})
susp_count = SuspensionClase.objects.filter(clase=clase, fecha=fecha_obj).count()
assert susp_count == 1
print(f'  Duplicado prevenido: {susp_count}')
print('  PASS')

# TEST 6: Non-admin blocked
print('\n=== TEST 6: No-admin bloqueado ===')
c2 = Client()
c2.force_login(cliente1)
resp4 = c2.post(url, {'fecha': fecha_str, 'motivo': 'feriado'})
susp_count2 = SuspensionClase.objects.filter(clase=clase, fecha=fecha_obj, motivo='feriado').count()
assert susp_count2 == 0
print('  No-admin bloqueado: OK')
print('  PASS')

# Cleanup
SuspensionClase.objects.filter(clase=clase).delete()
Voucher.objects.filter(cliente=cliente2).delete()
Reserva.objects.filter(clase=clase).delete()
print('\nAll tests passed!')
