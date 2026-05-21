from django.db import models
from django.conf import settings
from django.utils import timezone

class Actividad(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

"""
    class Profesor(models.Model):
    nombre = models.CharField(max_length=50)
    apellido = models.CharField(max_length=50)
    especialidad = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.apellido}, {self.nombre}"
"""
        
class Profesor(models.Model):
    # Relación directa con el Usuario que creamos en la otra app
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    nombre = models.CharField(max_length=50)
    apellido = models.CharField(max_length=50)
    especialidad = models.CharField(max_length=100, blank=True)
    dni = models.CharField(max_length=20, unique=True, null=True, blank=True) # Agregamos el DNI
    telefono = models.CharField(max_length=30, blank=True, null=True)
    correo = models.EmailField(blank=True, null=True)
    fecha_nacimiento = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.apellido}, {self.nombre}"

class Clase(models.Model):
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE)
    profesor = models.ForeignKey(Profesor, on_delete=models.SET_NULL, null=True, blank=True)
    
    # 📆 Fecha en la que inicia la recurrencia de esta clase fija
    fecha = models.DateField(default=timezone.now) 
    horario = models.TimeField()

    # Corregido el formato para que no tire error en Python
    def __str__(self):
        return f"{self.actividad.nombre} - Desde el {self.fecha.strftime('%d/%m')} a las {self.horario.strftime('%H:%M')}"

    @property
    def dia_semana_nombre(self):
        dias = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
        return dias[self.fecha.weekday()]

    # 👇 NUEVA PROPIEDAD: Nos da el número de día de la semana (0=Lunes, 1=Martes...)
    @property
    def dia_semana_num(self):
        return self.fecha.weekday()

    @property
    def ya_paso(self):
        ahora = timezone.now()
        clase_datetime = timezone.make_aware(
            timezone.datetime.combine(self.fecha, self.horario)
        )
        return ahora > clase_datetime

    # 👥 Mantenemos tus cupos compartidos intactos por ahora
    @property
    def cupos_disponibles(self):
        CAPACIDAD_MAXIMA_GIMNASIO = 30
        total_reservas_franja = Reserva.objects.filter(
            clase__fecha=self.fecha,
            clase__horario=self.horario
        ).count()
        
        disponibles = CAPACIDAD_MAXIMA_GIMNASIO - total_reservas_franja
        return max(0, disponibles)

'''class Clase(models.Model):
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE)
    profesor = models.ForeignKey(Profesor, on_delete=models.SET_NULL, null=True, blank=True)
    
    # 📆 1. CAMBIO CLAVE: Cambiamos el CharField de texto por una fecha real de calendario
    fecha = models.DateField(default=timezone.now) 
    horario = models.TimeField()  # Mantiene HH:MM:00

    def __str__(self):
        return f"{self.actividad.nombre} - {self.fecha|date:'d/m'} a las {self.horario}"

    # 🔄 2. MÉTODO DINÁMICO: Obtiene el nombre del día traducido cuando lo necesites en el front
    @property
    def dia_semana_nombre(self):
        dias = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
        return dias[self.fecha.weekday()]

    # ⏳ 3. MÉTODO DE CONTROL: Evalúa si la clase ya expiró en base a la hora actual exacta
    @property
    def ya_paso(self):
        ahora = timezone.now()
        # Combinamos fecha y hora de la clase para comparar con el momento actual
        clase_datetime = timezone.make_aware(
            timezone.datetime.combine(self.fecha, self.horario)
        )
        return ahora > clase_datetime

    # 👥 4. LÓGICA DE CUPOS DINÁMICOS COMPARTIDOS (30 por franja horaria)
    @property
    def cupos_disponibles(self):
        CAPACIDAD_MAXIMA_GIMNASIO = 30
        
        # Contamos todas las reservas activas que existan para el MISMO DÍA y la MISMA HORA
        # sin importar si son de esta actividad o de otra que corra en simultáneo.
        total_reservas_franja = Reserva.objects.filter(
            clase__fecha=self.fecha,
            clase__horario=self.horario
        ).count()
        
        disponibles = CAPACIDAD_MAXIMA_GIMNASIO - total_reservas_franja
        return max(0, disponibles) # Evita números negativos por si acaso'''


class Reserva(models.Model):
    # Tabla intermedia para conectar los usuarios con las clases específicas
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    clase = models.ForeignKey(Clase, on_delete=models.CASCADE, related_name='reservas')
    fecha_reserva = models.DateTimeField(auto_now_add=True)
    
    # 📋 LISTA DE ESPERA INTERNA
    # Si al crearse la reserva los cupos de la clase eran 0, pasa automáticamente a True
    en_lista_de_espera = models.BooleanField(default=False)
    
    monto_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    estado_pago = models.CharField(max_length=20, default='pendiente') # 'seña', 'total', 'pendiente'
    medio_pago = models.CharField(max_length=30, blank=True, null=True)  # 'Tarjeta', 'Mercado Pago'

    class Meta:
        # Evita que un mismo usuario se anote dos veces a la misma clase exacta
        unique_together = ('usuario', 'clase')

    def __str__(self):
        estado = "Lista de Espera" if self.en_lista_de_espera else "Confirmado"
        return f"{self.usuario.first_name} en {self.clase.actividad.nombre} ({estado})"