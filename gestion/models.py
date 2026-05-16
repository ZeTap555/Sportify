from django.db import models

class Actividad(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

class Clase(models.Model):
    DIAS_OPCIONES = [
        ('Lunes', 'Lunes'),
        ('Martes', 'Martes'),
        ('Miércoles', 'Miércoles'),
        ('Jueves', 'Jueves'),
        ('Viernes', 'Viernes'),
    ]
    
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE)
    horario = models.TimeField()  # Guardará HH:MM:00
    dia_semana = models.CharField(max_length=15, choices=DIAS_OPCIONES)

    def __str__(self):
        return f"{self.actividad.nombre} - {self.dia_semana} a las {self.horario}"