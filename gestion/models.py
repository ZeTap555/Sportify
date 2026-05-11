from django.db import models
from django.conf import settings

class Actividad(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)

    def __str__(self):
        return self.nombre

class Clase(models.Model):
    DIAS_SEMANA = [
        ('LU', 'Lunes'), ('MA', 'Martes'), ('MI', 'Miércoles'),
        ('JU', 'Jueves'), ('VI', 'Viernes'), ('SA', 'Sábado'),
    ]

    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE, related_name='clases')
    profesor = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        limit_choices_to={'rol': 'profe'}
    )
    dia = models.CharField(max_length=2, choices=DIAS_SEMANA)
    hora = models.TimeField()
    cupo_maximo = models.PositiveIntegerField(default=15)

    def __str__(self):
        return f"{self.actividad.nombre} - {self.get_dia_display()} {self.hora}"