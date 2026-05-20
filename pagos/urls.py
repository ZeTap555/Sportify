from django.urls import path
from . import views

urlpatterns = [
    # Ruta para el formulario interno de tarjeta
    path('tarjeta/', views.procesar_pago_tarjeta, name='pago_tarjeta'),
    
    # El disparador que te saca de la web hacia Mercado Pago
    path('iniciar-mp/<str:tipo>/<int:item_id>/', views.iniciar_pago_mercadopago, name='iniciar_mp'),
    
    # Retornos oficiales de Mercado Pago
    path('mp-exito/', views.mercado_pago_exito, name='mp_exito'),
    path('mp-fallo/', lambda r: redirect('grilla_actividades'), name='mp_fallo'), # Retorno simple si falla
]