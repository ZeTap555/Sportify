# Register your models here.
from django.contrib import admin
from .models import Profesor, Clase, Actividad, Reserva

admin.site.register(Profesor)
admin.site.register(Clase)
admin.site.register(Actividad)
admin.site.register(Reserva)