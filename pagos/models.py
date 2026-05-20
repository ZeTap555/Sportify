from django.db import models
from usuarios.models import Usuario
from gestion.models import Clase, Actividad

class Pago(models.Model):
    METODOS = [
        ('tarjeta', 'Tarjeta de Crédito/Débito'),
        ('mercadopago', 'Mercado Pago'),
    ]
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('aprobado', 'Aprobado'),
        ('fallido', 'Fallido'),
    ]
    TIPO_PAGO = [
        ('clase', 'Inscripción a Clase Única'),
        ('mensualidad', 'Mensualidad de Actividad'),
    ]

    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    metodo = models.CharField(max_length=20, choices=METODOS)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')
    tipo = models.CharField(max_length=20, choices=TIPO_PAGO)
    
    # Pueden ser nulos dependiendo de qué estén pagando
    clase = models.ForeignKey(Clase, on_delete=models.SET_NULL, null=True, blank=True)
    actividad = models.ForeignKey(Actividad, on_delete=models.SET_NULL, null=True, blank=True)
    
    fecha_pago = models.DateTimeField(auto_now_add=True)
    # Para guardar el ID que te devuelve Mercado Pago para rastreo
    mp_preference_id = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"Pago #{self.id} - {self.usuario.username} - ${self.monto} ({self.estado})"