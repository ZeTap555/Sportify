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
    path('pago/exito/', views.pago_exito, name='pago_exito'),
    path('pago/error/', views.pago_error, name='pago_error'),
    path('pago/pendiente/', views.pago_pendiente, name='pago_pendiente'),
    path('pago/confirmacion/<int:reserva_id>/', views.pago_confirmacion, name='pago_confirmacion'),
    path('clase/<int:clase_id>/asignar-profesor/', views.asignar_profesor_clase, name='asignar_profesor_clase'),
    path('notificaciones/',views.ver_notificaciones,name='ver_notificaciones'),
    path('notificaciones/marcar/<int:notificacion_id>/',views.marcar_leida,name='marcar_leida'),
    path('notificaciones/borrar/<int:notificacion_id>/',views.borrar_notificacion,name='borrar_notificacion'),
    path('notificaciones/borrar-todas/',views.borrar_todas_notificaciones,name='borrar_todas_notificaciones'),
    path('panel-admin/guardar-precios/', views.guardar_precios_admin, name='guardar_precios_admin'),

    path('comprobante/pdf/<int:reserva_id>',views.comprobante_pdf,name='comprobante_pdf')
]