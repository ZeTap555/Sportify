from django.db import models
from usuarios.models import Usuario
from gestion.models import Actividad, Clase

class Mensualidad(models.Model):
    ESTADOS = [
        ('pagada', 'Pagada'),
        ('pendiente', 'Pendiente'),
        ('vencida', 'Vencida'),
    ]

    usuario   = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='mensualidades')
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE, related_name='mensualidades')
    clase     = models.ForeignKey(Clase, on_delete=models.CASCADE, null=True, blank=True, related_name='mensualidades')
    mes       = models.IntegerField()   # 1 = Enero, 12 = Diciembre
    anio      = models.IntegerField()
    fecha_pago = models.DateField(null=True, blank=True)  # null si no pagó todavía
    estado    = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')

    class Meta:
        # Un usuario no puede tener dos mensualidades de la misma clase en el mismo mes/año
        unique_together = ('usuario', 'clase', 'mes', 'anio')
        verbose_name = 'Mensualidad'
        verbose_name_plural = 'Mensualidades'

    def __str__(self):
        return f"{self.usuario} - {self.actividad} ({self.mes}/{self.anio}) - {self.estado}"