from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError


class Actividad(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    precio_clase = models.DecimalField(max_digits=10, decimal_places=2, default=3500.00)
    precio_mensualidad = models.DecimalField(max_digits=10, decimal_places=2, default=15000.00)

    def clean(self):
        super().clean()

        # REGLA 1: La clase suelta debe ser como mínimo 1
        if self.precio_clase is not None and self.precio_clase < 1:
            raise ValidationError({
                'precio_clase': 'El precio de la clase debe ser de al menos $1.'
            })
        # REGLA 2: La mensualidad debe ser de al menos $1
        if self.precio_mensualidad is not None and self.precio_mensualidad < 1:
            raise ValidationError({
                'precio_mensualidad': 'El precio de la mensualidad debe ser de al menos $1.'
            })

        # REGLA 3: La mensualidad debe ser estricamente menor a 5 clases sueltas
        if self.precio_clase is not None and self.precio_mensualidad is not None:
            tope_mensualidad = self.precio_clase * 5  + 1  # Agregamos un pequeño margen para evitar igualdad exacta
            
            if self.precio_mensualidad >= tope_mensualidad:
                raise ValidationError({
                    'precio_mensualidad': f'La mensualidad no puede ser mayor a 5 clases sueltas. El tope actual es ${tope_mensualidad - 1}.'
                })

    def save(self, *args, **kwargs):
        # Valida las reglas de negocio antes de guardar en la base de datos
        self.full_clean()
        super().save(*args, **kwargs)
    def __str__(self):
        return self.nombre

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
    
    # 📆 Fecha en la que inicia o se dicta la clase fija de la serie
    fecha = models.DateField(default=timezone.now) 
    horario = models.TimeField()

    # 🔢 Cupo máximo configurable a mano por el administrador (pedido por Lucho)
    cupo_maximo = models.PositiveIntegerField(default=30)

    # Formato de representación en consola/admin
    def __str__(self):
        return f"{self.actividad.nombre} - Desde el {self.fecha.strftime('%d/%m')} a las {self.horario.strftime('%H:%M')}"

    # 👇 Propiedad que da el nombre del día en español
    @property
    def dia_semana_nombre(self):
        dias = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
        return dias[self.fecha.weekday()]

    # 👇 Propiedad clave para la grilla (0=Lunes, 1=Martes, etc.)
    @property
    def dia_semana_num(self):
        return self.fecha.weekday()

    # 👇 Valida si la clase ya expiró en base al tiempo real actual
    @property
    def ya_paso(self):
        ahora = timezone.now()
        clase_datetime = timezone.make_aware(
            timezone.datetime.combine(self.fecha, self.horario)
        )
        return ahora > clase_datetime

    # 👇 Calcula cuántas vacantes quedan disponibles REALES para reservar en una fecha
    def cupos_para_fecha(self, fecha):
        # Cuenta las reservas de alumnos hechas específicamente para esta clase en la fecha dada
        total_reservas_clase = Reserva.objects.filter(
            fecha_clase=fecha,
            clase=self
        ).count()
        
        # Restamos de su propio cupo configurado a mano (15, 19, 30, etc.)
        disponibles = self.cupo_maximo - total_reservas_clase
        return max(0, disponibles)


class Reserva(models.Model):
    # Tabla intermedia para conectar los usuarios con las clases específicas
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    clase = models.ForeignKey(Clase, on_delete=models.CASCADE, related_name='reservas')
    fecha_clase = models.DateField(null=True, blank=True)
    fecha_reserva = models.DateTimeField(auto_now_add=True)
    asistio=models.BooleanField(default=False)
    
    # 📋 LISTA DE ESPERA INTERNA
    # Si al crearse la reserva los cupos de la clase eran 0, pasa automáticamente a True
    en_lista_de_espera = models.BooleanField(default=False)
    
    monto_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    estado_pago = models.CharField(max_length=20, default='pendiente') # 'seña', 'total', 'pendiente'
    medio_pago = models.CharField(max_length=30, blank=True, null=True)  # 'Tarjeta', 'Mercado Pago'
    #--------------------------------------------------------------
    MODALIDAD_CHOICES = [
        ('individual', 'Individual'),
        ('mensual', 'Mensual'),
    ]
    modalidad = models.CharField(max_length=10, choices=MODALIDAD_CHOICES, default='individual')
    #---------------------------------------------------------------------------------------------------------
    class Meta:
        # Evita que un mismo usuario se anote dos veces a la misma clase exacta
        unique_together = ('usuario', 'clase', 'fecha_clase')

    def __str__(self):
        estado = "Lista de Espera" if self.en_lista_de_espera else "Confirmado"
        return f"{self.usuario.first_name} en {self.clase.actividad.nombre} ({estado})"
    
class Notificacion(models.Model):
    usuario=models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mensaje=models.TextField()
    leida=models.BooleanField(default=False)
    fecha=models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Notificación para {self.usuario.username} - {self.mensaje[:50]}..."