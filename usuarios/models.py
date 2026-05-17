from django.db import models
from django.contrib.auth.models import AbstractUser

def apto_medico_path(instance, filename):
    ext = filename.split('.')[-1]
    return f'aptos_medicos/{instance.dni}_apto_medico.{ext}'

class Usuario(AbstractUser):
    # Campos adicionales para el perfil
    dni = models.CharField(unique=True, max_length=10, verbose_name="DNI")
    rol = models.CharField(max_length=20, default='cliente') # admin, profesor, cliente
    telefono = models.CharField(max_length=20, null=True, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    apta_medica = models.FileField(upload_to=apto_medico_path, null=True, blank=True)

    # Esto le dice a Django que use el DNI para loguearse en lugar del username
    USERNAME_FIELD = 'dni'
    REQUIRED_FIELDS = ['email', 'username']

    def __str__(self):
        return f"{self.dni} - {self.first_name} {self.last_name}"