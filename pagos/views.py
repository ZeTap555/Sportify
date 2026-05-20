from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Pago
from gestion.models import Clase, Actividad
import mercadopago

# 💳 VISTA 1: El formulario interno para Tarjeta (Simulado)
def procesar_pago_tarjeta(request):
    if request.method == 'POST':
        # Capturás los datos del formulario maqueteado
        tipo = request.POST.get('tipo')
        monto = request.POST.get('monto')
        item_id = request.POST.get('item_id') # Puede ser ID de clase o de actividad

        # Pasarela Simulada: Validamos que no venga vacío y aprobamos de una
        nuevo_pago = Pago.objects.create(
            usuario=request.user,
            monto=monto,
            metodo='tarjeta',
            estado='aprobado', # Lo aprobamos directo
            tipo=tipo
        )
        if tipo == 'clase':
            nuevo_pago.clase_id = item_id
            # ACÁ: Ejecutar tu lógica para crear la fila en la tabla Reserva
        else:
            nuevo_pago.actividad_id = item_id
            # ACÁ: Ejecutar tu lógica para activar la mensualidad al usuario

        nuevo_pago.save()
        messages.success(request, "¡Pago con tarjeta procesado con éxito! Lugar asegurado.")
        return redirect('grilla_actividades')

    return render(request, 'formulario_tarjeta.html')


# 🟨 VISTA 2: El conector que te redirige a Mercado Pago
def iniciar_pago_mercadopago(request, tipo, item_id):
    # 1. Configurar tus credenciales de prueba (Se consiguen en Mercado Pago Developers)
    sdk = mercadopago.SDK("PROD_ACCESS_TOKEN_O_TEST_ACCESS_TOKEN")

    title = "Inscripción a Clase" if tipo == "clase" else "Mensualidad"
    monto = 1500.00 if tipo == "clase" else 12000.00 # Valores de prueba hardcodeados o de DB

    # 2. Crear el paquete de Preferencia para enviarle a la API
    preference_data = {
        "items": [
            {
                "title": title,
                "quantity": 1,
                "unit_price": monto,
                "currency_id": "ARS"
            }
        ],
        # A dónde te devuelve MP según cómo salga la transacción
        "back_urls": {
            "success": "http://localhost:8000/pagos/mp-exito/",
            "failure": "http://localhost:8000/pagos/mp-fallo/",
            "pending": "http://localhost:8000/pagos/mp-pendiente/"
        },
        "auto_return": "approved", # Vuelve solo al terminar si se aprueba
    }

    preference_response = sdk.preference().create(preference_data)
    preference = preference_response["response"]
    
    # 3. Guardamos el pago en la DB local como "pendiente"
    pago = Pago.objects.create(
        usuario=request.user,
        monto=monto,
        metodo='mercadopago',
        estado='pendiente',
        tipo=tipo,
        mp_preference_id=preference["id"]
    )
    if tipo == 'clase': pago.clase_id = item_id
    else: pago.actividad_id = item_id
    pago.save()

    # 4. Redireccionamos los ojos del usuario directo a la pasarela de Mercado Pago
    return redirect(preference["init_point"])


# 🟩 VISTA 3: La URL de retorno exitoso (A donde te devuelve MP)
def mercado_pago_exito(request):
    # MP te devuelve por GET datos del pago en la URL (ej: ?preference_id=xxx)
    pref_id = request.GET.get('preference_id')
    
    # Buscamos el pago pendiente que teníamos registrado con ese ID
    pago = get_object_or_404(Pago, mp_preference_id=pref_id)
    pago.estado = 'aprobado'
    pago.save()

    # ACÁ: Duplicás la lógica de impacto según el tipo
    if pago.tipo == 'clase':
        pass # Alta en tabla Reserva para el usuario
    else:
        pass # Alta de mensualidad activa

    messages.success(request, "¡Mercado Pago confirmó tu transacción con éxito!")
    return redirect('grilla_actividades')