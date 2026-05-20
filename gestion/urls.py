# gestion/urls.py
from django.urls import path
from . import views


urlpatterns = [
    path('', views.grilla_actividades, name='grilla_actividades'), # <-- ¡AHORA ES EL HOME! (vacío)
    #path('actividad/nueva/', views.crear_actividad, name='crear_actividad'),
    #path('clase/nueva/', views.crear_clase, name='crear_clase'),
    path('panel-admin/', views.panel_admin, name='panel_admin'),
    path('historial-pagos/', views.historial_pagos, name='historial_pagos'),
    path('clase/<int:clase_id>/datos/', views.detalle_clase_api, name='detalle_clase_api'),
    path('clase/<int:clase_id>/inscribirse/', views.inscribirse_clase, name='inscribirse_clase'),
    path('pago/tarjeta/', views.pago_tarjeta, name='pago_tarjeta'),
    path('pago/mercadopago/', views.pago_mercadopago, name='pago_mercadopago'),
    path('pago/confirmacion/<int:reserva_id>/', views.pago_confirmacion, name='pago_confirmacion'),
]