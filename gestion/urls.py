from django.urls import path
from . import views

urlpatterns = [
    path('', views.grilla_actividades, name='grilla_actividades'), # <-- ¡AHORA ES EL HOME! (vacío)
    
    # Panel Admin y Configuraciones
    path('panel-admin/', views.panel_admin, name='panel_admin'),
    path('panel-admin/guardar-precios/', views.guardar_precios_admin, name='guardar_precios_admin'),
    path('validar-baja/', views.validar_baja, name='validar_baja'),
    
    # Historiales y Reservas
    path('historial-pagos/', views.historial_pagos, name='historial_pagos'),
    path('mis-reservas/', views.mis_reservas, name='mis_reservas'),
    path('mis-clases/', views.mis_clases, name='mis_clases'),
    path("mis-vouchers/",views.mis_vouchers,name="mis_vouchers"),
    
    # Lógica de Clases
    path('clase/<int:clase_id>/datos/', views.detalle_clase_api, name='detalle_clase_api'),
    path('clase/<int:clase_id>/detalle/', views.detalle_clase_fecha, name='detalle_clase_fecha'),
    path('clase/<int:clase_id>/inscribirse/', views.inscribirse_clase, name='inscribirse_clase'),
    path('clase/<int:clase_id>/asignar-profesor/', views.asignar_profesor_clase, name='asignar_profesor_clase'),
    path('clase/<int:clase_id>/suspender/', views.suspender_clase, name='suspender_clase'),
    path('clase/<int:clase_id>/eliminar/', views.eliminar_clase, name='eliminar_clase'),
    path('ver-inscriptos/<int:clase_id>/<str:fecha>/',views.ver_inscriptos,name='ver_inscriptos'),
    path('generar-qr/<int:clase_id>/<str:fecha>/', views.generar_qr, name='generar_qr'),
    path('registrar-asistencia/<int:clase_id>/<str:fecha>/', views.registrar_asistencia, name='registrar_asistencia'),
    path('estado-qr/<int:clase_id>/<str:fecha>/',views.estado_qr,name='estado_qr'),
    path('validar-horario-qr/<int:clase_id>/<str:fecha>/',views.validar_horario_qr,name='validar_horario_qr'),
    path("cancelar-reserva/<int:reserva_id>/",views.cancelar_reserva,name="cancelar_reserva"),
    path("cancelar-clase-individual/<int:reserva_id>/",views.cancelar_clase_individual,name="cancelar_clase_individual"),
    path("salir-lista-espera/<int:reserva_id>/",views.salir_lista_espera,name="salir_lista_espera"),
    
    # Pasarela de Pagos
    path('pago/tarjeta/', views.pago_tarjeta, name='pago_tarjeta'),
    path('pago/mercadopago/', views.pago_mercadopago, name='pago_mercadopago'),
    path('pago/exito/', views.pago_exito, name='pago_exito'),
    path('pago/error/', views.pago_error, name='pago_error'),
    path('pago/pendiente/', views.pago_pendiente, name='pago_pendiente'),
    path('pago/completar-senia/<int:reserva_id>/', views.completar_pago_senia, name='completar_pago_senia'),
    path('pago/renovar-mensualidad/<int:clase_id>/', views.renovar_mensualidad, name='renovar_mensualidad'),
    path('pago/confirmacion/<int:reserva_id>/', views.pago_confirmacion, name='pago_confirmacion'),
    
    # Notificaciones
    path('notificaciones/', views.ver_notificaciones, name='ver_notificaciones'),
    path('notificaciones/marcar/<int:notificacion_id>/', views.marcar_leida, name='marcar_leida'),
    path('notificaciones/borrar/<int:notificacion_id>/', views.borrar_notificacion, name='borrar_notificacion'),
    path('notificaciones/borrar-todas/', views.borrar_todas_notificaciones, name='borrar_todas_notificaciones'),
    
    # Reportes
    path('comprobante/pdf/<int:reserva_id>', views.comprobante_pdf, name='comprobante_pdf'),

    # Admin: actividad de usuario
    path('usuario/<int:user_id>/actividad/', views.actividad_usuario, name='actividad_usuario'),
    path('modificar-clase/<int:clase_id>/', views.vista_modificar_clase, name='modificar_clase'),
]