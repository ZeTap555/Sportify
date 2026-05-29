from django.contrib import admin
from .models import Mensualidad

@admin.register(Mensualidad)
class MensualidadAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'actividad', 'mes', 'anio', 'estado', 'fecha_pago')
    list_filter = ('estado', 'mes', 'anio', 'actividad')
    search_fields = ('usuario__username', 'actividad__nombre')
    list_editable = ('estado',)  # Podés cambiar el estado directo desde la lista