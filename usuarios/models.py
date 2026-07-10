from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import timedelta

# Validez del apto médico: 1 año desde la fecha de carga.
DIAS_VALIDEZ_APTO_MEDICO = 365
# A partir de cuántos días antes del vencimiento se considera "próximo a vencer".
DIAS_AVISO_PROXIMO_VENCIMIENTO = 30


def apto_medico_path(instance, filename):
 ext = filename.split('.')[-1]
 return f'aptos_medicos/{instance.dni}_apto_medico.{ext}'

class Strike(models.Model):
    TIPO_CHOICES = (
        ('individual', 'Clase Individual'),
        ('mensual', 'Clase Mensual'),
    )
    usuario = models.ForeignKey('usuarios.Usuario', on_delete=models.CASCADE, related_name='strikes')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    fecha_falta = models.DateField(default=timezone.now)

    class Meta:
        verbose_name = "Strike"
        verbose_name_plural = "Strikes"
        
class Usuario(AbstractUser):
# Campos adicionales para el perfil
 penalizacion_pendiente_individual = models.BooleanField(default=False)
 penalizacion_pendiente_mensual = models.BooleanField(default=False)
 
 dni = models.CharField(
    unique=True,
    max_length=10,
    verbose_name="DNI"
 )
 rol = models.CharField(
    max_length=20,
    default='cliente'
 ) # admin, profesor, cliente
 telefono = models.CharField(
    max_length=20,
    null=True,
    blank=True
 )
 fecha_nacimiento = models.DateField(
    null=True,
    blank=True
 )
 apta_medica = models.FileField(
    upload_to=apto_medico_path,
    null=True,
    blank=True
 )

 # =========================
 # APTO MÉDICO: control de vigencia y declaración de responsabilidad
 # =========================

 fecha_carga_apto = models.DateTimeField(
    null=True,
    blank=True,
    verbose_name="Fecha de carga del apto médico"
 )

 acepto_declaracion_apto = models.BooleanField(
    default=False,
    verbose_name="Aceptó la declaración de responsabilidad del apto médico"
 )

 fecha_aceptacion_declaracion = models.DateTimeField(
    null=True,
    blank=True,
    verbose_name="Fecha de aceptación de la declaración"
 )

 # =========================
 # RECUPERAR CONTRASEÑA
 # =========================
 reset_token = models.CharField(
    max_length=200,
    null=True,
    blank=True
 )

 # Esto le dice a Django que use el DNI para loguearse en lugar del username
 USERNAME_FIELD = 'dni'
 REQUIRED_FIELDS = ['email', 'username']

 def __str__(self):

    return f"{self.dni} - {self.first_name} {self.last_name}"

 # =========================
 # LÓGICA CENTRALIZADA DE VIGENCIA DEL APTO MÉDICO
 # =========================
 # Toda la app (templates, views, decoradores, API) debe consultar estos
 # métodos en lugar de reimplementar la cuenta de días en cada lugar.

 def fecha_vencimiento_apto(self):
    """
    Devuelve la fecha (date) en la que vence el apto médico, o None
    si el usuario nunca cargó uno.
    """
    if not self.fecha_carga_apto:
        return None
    return (self.fecha_carga_apto + timedelta(days=DIAS_VALIDEZ_APTO_MEDICO)).date()

 def tiene_apto_vigente(self):
    """
    Único punto de verdad sobre si el usuario puede usar funcionalidades
    que requieren apto médico vigente (inscripción a clases, reservas, etc).

    Requiere:
      - Tener un archivo de apto médico cargado.
      - Haber aceptado la declaración de responsabilidad.
      - Que no hayan pasado más de DIAS_VALIDEZ_APTO_MEDICO desde la carga.
    """
    if not self.apta_medica:
        return False
    if not self.acepto_declaracion_apto:
        return False
    vencimiento = self.fecha_vencimiento_apto()
    if vencimiento is None:
        return False
    return timezone.now().date() <= vencimiento

 def apto_vencido(self):
    """Inverso semántico de tiene_apto_vigente(), pensado para usar en templates."""
    return not self.tiene_apto_vigente()

 def dias_restantes_apto(self):
    """
    Días que faltan para que venza el apto médico. Puede ser negativo
    si ya está vencido. Devuelve None si no hay apto cargado.
    """
    vencimiento = self.fecha_vencimiento_apto()
    if vencimiento is None:
        return None
    return (vencimiento - timezone.now().date()).days

 def apto_proximo_a_vencer(self):
    """
    True si el apto está vigente pero vence dentro de los próximos
    DIAS_AVISO_PROXIMO_VENCIMIENTO días.
    """
    if not self.tiene_apto_vigente():
        return False
    dias = self.dias_restantes_apto()
    return dias is not None and dias <= DIAS_AVISO_PROXIMO_VENCIMIENTO

 def estado_apto_medico(self):
    """
    Devuelve un string con el estado actual del apto, pensado para
    mostrar directamente en templates: 'sin_cargar', 'vencido',
    'proximo_a_vencer' o 'vigente'.
    """
    if not self.apta_medica or not self.acepto_declaracion_apto:
        return 'sin_cargar'
    if not self.tiene_apto_vigente():
        return 'vencido'
    if self.apto_proximo_a_vencer():
        return 'proximo_a_vencer'
    return 'vigente'
 
 def obtener_strikes_mes_actual(self, tipo):
    """Cuenta cuántos strikes de cierto tipo tiene el usuario en el mes en curso."""
    ahora = timezone.now()
    return self.strikes.filter(
        tipo=tipo,
        fecha_falta__year=ahora.year,
        fecha_falta__month=ahora.month
    ).count()

 def tiene_sancion_activa(self, tipo):
    """Retorna True si llega a 3 strikes."""
    return self.obtener_strikes_mes_actual(tipo) >= 3
   

