# =========================================================================
# LIBRERÍAS ESTÁNDAR DE PYTHON
# =========================================================================
import os
import re
import uuid
import calendar
from calendar import monthrange
from datetime import datetime, date
from decimal import Decimal
from multiprocessing import context

# =========================================================================
# LIBRERÍAS DE TERCEROS
# =========================================================================
import mercadopago
from dateutil.relativedelta import relativedelta
from requests import request
from urllib3 import request as urllib3_request
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import Color, black, grey
from reportlab.pdfbase.pdfmetrics import stringWidth

# =========================================================================
# DJANGO IMPORTS
# =========================================================================
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.utils.timezone import localtime
from django.db import transaction
from django.db.models import Sum
from django.core.mail import send_mail, EmailMultiAlternatives
from django.utils import translation
from django.core.exceptions import ValidationError

# =========================================================================
# MODELOS LOCALES
# =========================================================================
from .models import Clase, Actividad, Profesor, Reserva, Notificacion
from reservas.models import Mensualidad
from usuarios.models import Usuario

# Trae tu modelo personalizado
Usuario = get_user_model()


# =========================================================================
# 1. GRILLA PRINCIPAL Y DETALLES
# =========================================================================

def grilla_actividades(request):
    ahora = timezone.now().date()
    translation.activate('es')
    # 1. Capturar mes y año seleccionados (por defecto el mes actual)
    año = int(request.GET.get('anio', ahora.year))
    mes = int(request.GET.get('mes', ahora.month))
    dia_seleccionado_str = request.GET.get('dia_sel', str(ahora.day))
    actividad_id = request.GET.get('actividad')
    if actividad_id and not actividad_id.isdigit():
     actividad_id = None

    
    fecha_seleccionada = date(año, mes, int(dia_seleccionado_str))

    # 2. Generar la lista de los próximos 6 meses para el panel superior derecho
    proximos_meses = []
    meses_nombres = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    for i in range(6):
        futuro = ahora + relativedelta(months=i)
        proximos_meses.append({
            'anio': futuro.year,
            'mes': futuro.month,
            'nombre': f"{meses_nombres[futuro.month]} {futuro.year}",
            'activo': futuro.year == año and futuro.month == mes
        })

    # 3. Traemos todas las clases del sistema para evaluar en qué casilleros se repiten
    todas_las_clases = Clase.objects.all()
    if actividad_id:
        todas_las_clases=todas_las_clases.filter(
            actividad_id=actividad_id
        )
    
    # 4. Construir las semanas del calendario usando el módulo de Python
    cal = calendar.Calendar(firstweekday=0) # 0 = Lunes
    semanas_matriz = cal.monthdayscalendar(año, mes)

    # Mapeamos qué clases se repiten en cada casillero numérico del mes
    clases_por_dia = {}
    for semana in semanas_matriz:
        for dia in semana:
            if dia != 0:
                fecha_casillero = date(año, mes, dia)
                dia_semana_casillero = fecha_casillero.weekday() # 0 = Lunes, 1 = Martes, etc.
                
                clases_por_dia[dia] = []
                for clase in todas_las_clases:
                    # Se repite si coincide el día de la semana Y el casillero es posterior o igual al inicio
                    if clase.dia_semana_num == dia_semana_casillero and fecha_casillero >= clase.fecha:
                        clase.cupos_mostrar = clase.cupos_para_fecha(fecha_casillero)
                        clases_por_dia[dia].append(clase)

    # 5. Lógica para el detalle del día seleccionado (Abajo a la derecha)
    clases_detalle_dia = []
    if fecha_seleccionada >= ahora:
        dia_semana_sel = fecha_seleccionada.weekday()
        for clase in todas_las_clases:
            if clase.dia_semana_num == dia_semana_sel and fecha_seleccionada >= clase.fecha:
                clase.cupos_mostrar = clase.cupos_para_fecha(fecha_seleccionada)
                # No mostrar clases que ya pasaron en el detalle del día
                if fecha_seleccionada == ahora:
                    fecha_hora_clase = timezone.make_aware(
                        datetime.combine(fecha_seleccionada, clase.horario)
                    )
                    if fecha_hora_clase < timezone.now():
                        continue
                clases_detalle_dia.append(clase)
        
        # Las ordenamos por horario para que no queden mezcladas
        clases_detalle_dia.sort(key=lambda x: x.horario)
    hay_clases_mes=False
    for semana in semanas_matriz:
        for dia in semana:
            if dia !=0:
                fecha_casillero=date(año,mes,dia)
                for clase in todas_las_clases:
                    if(
                        clase.dia_semana_num==fecha_casillero.weekday()
                        and fecha_casillero>=clase.fecha
                    ):
                        hay_clases_mes=True
                        break
                if hay_clases_mes:
                    break
        if hay_clases_mes:
            break
    actividades=Actividad.objects.all()
    mensaje_filtro=None
    if actividad_id and not hay_clases_mes:
        mensaje_filtro=(
            "No se encontraron clases disponibles para los filtros seleccionados"
        )

    context = {
        'semanas_matriz': semanas_matriz,
        'mes_nombre': meses_nombres[mes],
        'mes_actual': mes,
        'anio_actual': año,
        'proximos_meses': proximos_meses,
        'clases_por_dia': clases_por_dia,
        'fecha_seleccionada': fecha_seleccionada,
        'clases_detalle_dia': clases_detalle_dia,
        'hoy': ahora,
        'actividades':actividades,
        'actividad_seleccionada':actividad_id,
        'mensaje_filtro':mensaje_filtro,
    }
    
    if request.user.is_authenticated:
        cantidad_no_leidas = Notificacion.objects.filter(usuario=request.user, leida=False).count()
    else:
        cantidad_no_leidas = 0

    context['cantidad_no_leidas'] = cantidad_no_leidas
    return render(request, 'grilla.html', context)


def detalle_clase_fecha(request, clase_id):
    clase = get_object_or_404(Clase, id=clase_id)
    fecha_str = request.GET.get('fecha') # Capturamos la fecha del casillero de la grilla

    # Si es Admin, ve el panel de control de la clase para esa fecha
    if request.user.is_authenticated and request.user.rol == 'admin':
        # 1. Traemos a todos los usuarios que quedaron atrapados en la lista de espera para esta fecha
        cola_espera = Reserva.objects.filter(
            clase=clase, 
            fecha_clase=fecha_str, 
            en_lista_de_espera=True
        ).select_related('usuario')

        # 2. Traemos la lista completa de profesores para el elemento <select>
        lista_profesores = Profesor.objects.all()

        context = {
            'clase': clase,
            'fecha_clase': fecha_str,
            'cola_espera': cola_espera,
            'lista_profesores': lista_profesores,
        }
        return render(request, 'gestion/detalle_clase_admin.html', context)
    
    # Si es un usuario común, lo mandás al HTML genial que armó tu equipo
    context = {'clase': clase, 'fecha_clase': fecha_str}
    return render(request, 'gestion/detalle_clase_usuario.html', context)


# =========================================================================
# 2. INSCRIPCIONES Y RESERVAS
# =========================================================================

@login_required
def inscribirse_clase(request, clase_id):
    clase = get_object_or_404(Clase, id=clase_id)
    fecha_clase_str = request.POST.get('fecha_clase')

    if not fecha_clase_str:
        return redirect('grilla_actividades')

    try:
        fecha_clase = datetime.strptime(fecha_clase_str, '%Y-%m-%d').date()
    except ValueError:
        return redirect('grilla_actividades')

    if request.method == 'POST':
        tipo_pago = request.POST.get('tipo_pago')
        medio_pago = request.POST.get('medio_pago')
        flujo_tipo = request.POST.get('flujo_tipo', 'clase')  # 'clase' o 'mensualidad'

        if tipo_pago not in ('senia', 'total'):
            return redirect('grilla_actividades')

        if medio_pago not in ('Tarjeta', 'Mercado Pago'):
            return redirect('grilla_actividades')

        # Regla de negocio: Choque de horarios en inscripción individual
        choque_horario = Reserva.objects.filter(
            usuario=request.user,
            fecha_clase=fecha_clase,
            clase__horario=clase.horario,
            en_lista_de_espera=False
        ).exists()

        if choque_horario:  
            messages.error(request, f"Ya estás inscripto a otra clase en el horario de las {clase.horario.strftime('%H:%M')}.")
            return redirect('grilla_actividades')
        
        # Control A: Si es clase individual y ya tiene reserva para esta clase y fecha exacta
        if flujo_tipo == 'clase' and Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_clase).exists():
            messages.error(request, "Ya estás inscripto en esta clase para esta fecha.")
            return redirect('grilla_actividades')

        # Control B: Si es mensualidad, chequeamos que no tenga ya el abono activo este mes
        if flujo_tipo == 'mensualidad':
            mes_solicitado = fecha_clase.month
            anio_solicitado = fecha_clase.year
            
            if Mensualidad.objects.filter(
                usuario=request.user, 
                actividad=clase.actividad, 
                mes=mes_solicitado, 
                anio=anio_solicitado,
                estado='pagada'
            ).exists():
                messages.error(request, "Ya estás inscripto a una mensualidad de esta actividad.")
                return redirect('grilla_actividades')

        # Cálculo de costo de la mensualidad (MODELO MES CALENDARIO)
        if flujo_tipo == 'mensualidad':
            hoy = datetime.now().date()
            
            # Usamos el mes y año de la clase que seleccionó en la grilla
            anio_solicitado = fecha_clase.year
            mes_solicitado = fecha_clase.month
            
            dia_semana_objetivo = fecha_clase.weekday()
            clases_totales_restantes = 0

            # Obtenemos cuántos días tiene ese mes (ej: 28, 30, 31)
            _, ultimo_dia_mes = monthrange(anio_solicitado, mes_solicitado)
            
            # Si se está anotando para el mes EN CURSO, contamos desde hoy.
            # Si está pagando por adelantado el MES QUE VIENE, contamos desde el día 1.
            if hoy.month == mes_solicitado and hoy.year == anio_solicitado:
                dia_inicio = hoy.day
            else:
                dia_inicio = 1
            
            # Contamos las clases EXACTAS que le quedan en este mes
            for d in range(dia_inicio, ultimo_dia_mes + 1):
                fecha_evaluar = date(anio_solicitado, mes_solicitado, d)
                if fecha_evaluar.weekday() == dia_semana_objetivo:
                    clases_totales_restantes += 1

            if clases_totales_restantes == 0:
                clases_totales_restantes = 1
                
            # =========================================================
            # CÁLCULO PROPORCIONAL EXACTO DEL MES
            # =========================================================
            # El precio de la mensualidad toma como base 5 clases
            clases_ideales = Decimal('5.0') 
            
            precio_unitario_mensual = clase.actividad.precio_mensualidad / clases_ideales
            monto = precio_unitario_mensual * Decimal(clases_totales_restantes)
            
            # TOPE MÁXIMO: Nunca cobra más que la mensualidad base
            if monto > clase.actividad.precio_mensualidad:
                monto = clase.actividad.precio_mensualidad
            
            monto = round(monto, 2)
             
        else:
            # Flujo individual suelta
            if clase.cupos_para_fecha(fecha_clase) <= 0:
                Reserva.objects.create(
                    usuario=request.user,
                    clase=clase,
                    fecha_clase=fecha_clase,
                    en_lista_de_espera=True,
                    monto_pagado=0,
                    estado_pago='pendiente',
                )
                messages.warning(request, "Te registraste en la lista de espera para esta clase.")
                return redirect('grilla_actividades')
                
            precio = clase.actividad.precio_clase
            monto = precio / 2 if tipo_pago == 'senia' else precio

        # Guardamos en sesión
        request.session['inscripcion_pendiente'] = {
            'clase_id': clase.id,
            'fecha_clase': fecha_clase_str,
            'tipo_pago': tipo_pago,
            'monto': str(monto),
            'medio_pago': medio_pago,
            'flujo_tipo': flujo_tipo,
        }

        if medio_pago == 'Tarjeta':
            return redirect('pago_tarjeta')
        else:
            return redirect('pago_mercadopago')

    return redirect('grilla_actividades')


@login_required
def mis_reservas(request):
    from datetime import date
    reservas = Reserva.objects.filter(usuario=request.user, fecha_clase__gte=date.today())\
        .select_related('clase__actividad', 'clase__profesor')\
        .order_by('-fecha_clase', '-clase__horario')
    return render(request, 'gestion/mis_reservas.html', {'reservas': reservas})


# =========================================================================
# 3. PASARELAS DE PAGO Y CONFIRMACIONES
# =========================================================================

@login_required
def pago_tarjeta(request):
    datos = request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect('grilla_actividades')

    if request.method == 'POST':
        numero = request.POST.get('numero', '')
        vto = request.POST.get('vto', '')
        cvv = request.POST.get('cvv', '')
        titular = request.POST.get('titular', '')

        if not all([numero, vto, cvv, titular]):
            messages.error(request, "Complete todos los campos de la tarjeta.")
            return render(request, 'pago_tarjeta.html', {'monto': datos['monto']})

        numero_limpio = numero.replace(' ', '')
        
        try:
            mes_vto, anio_vto = vto.split('/')
            mes_vto = int(mes_vto)
            anio_vto = int(anio_vto)
            hoy = datetime.now()
            anio_actual = hoy.year % 100
            mes_actual = hoy.month
            if (anio_vto < anio_actual or (anio_vto == anio_actual and mes_vto < mes_actual)):
                resultado = "tarjeta_vencida"
        except:
            resultado = "tarjeta_vencida"

        if len(numero_limpio) != 16:
            resultado = "tarjeta_corta"
        elif len(cvv) != 3:
            resultado = "cvv_invalido"
        else:
            tarjetas_prueba = {
                "1234123412341234": {
                    "titular":"Facundo Carbone",
                    "cvv":"123",
                    "vto":"12/30",
                    "resultado":"ok"
                },
                "3456345634563456": {
                    "titular":"Juan Perez",
                    "cvv":"456",
                    "vto":"11/29",
                    "resultado":"error_banco"
                },
                "2134213421342134": {
                    "titular":"Maria Lopez",
                    "cvv":"789",
                    "vto":"10/28",
                    "resultado":"saldo_insuficiente"
                }
            }
            tarjeta = tarjetas_prueba.get(numero_limpio)
            if not tarjeta:
                resultado = "tarjeta_inexistente"
            elif tarjeta["titular"].lower() != titular.lower():
                resultado = "titular_incorrecto"
            elif tarjeta["cvv"] != cvv:
                resultado = "cvv_invalido"
            elif tarjeta["vto"] != vto:
                resultado = "tarjeta_vencida"
            else:
                resultado = tarjeta["resultado"]

        # =========================================================
        # MANEJO DE ESCENARIOS UNIFICADO (UX MEJORADA)
        # =========================================================
        if resultado != "ok":
            # 1. Errores de Tipeo (El usuario se queda en la pantalla para corregir)
            errores_tipeo = ["titular_incorrecto", "cvv_invalido", "tarjeta_vencida", "tarjeta_corta"]
            
            if resultado in errores_tipeo:
                if resultado == "titular_incorrecto":
                    messages.error(request, "El nombre del titular no coincide con el registrado en la tarjeta.")
                elif resultado == "cvv_invalido":
                    messages.error(request, "El CVV ingresado es incorrecto.")
                elif resultado == "tarjeta_vencida":
                    messages.error(request, "La tarjeta ingresada se encuentra vencida.")
                elif resultado == "tarjeta_corta":
                    messages.error(request, "La tarjeta ingresada debe tener 16 dígitos.")
                
                return render(request, 'pago_tarjeta.html', {'monto': datos['monto']})
            
            # 2. Errores Duros / Rechazos (Lo mandamos a la cruz roja)
            else:
                # saldo_insuficiente, tarjeta_inexistente, error_banco
                return redirect('pago_confirmacion', reserva_id=0)

        # Pago exitoso -> crear reservas asociadas y registrar la mensualidad vigente
        with transaction.atomic():
            clase = get_object_or_404(Clase, id=datos['clase_id'])
            fecha_inicial = datetime.strptime(datos['fecha_clase'], '%Y-%m-%d').date()
            hoy = datetime.now().date()
            
            if datos['flujo_tipo'] == 'mensualidad':
                mes_current = fecha_inicial.month
                anio_actual = fecha_inicial.year
                dia_semana_objetivo = fecha_inicial.weekday()
                
                reserva_principal = None
                lista_fechas_reservar = []

                # 1. Recolectar días válidos del mes actual
                _, ultimo_dia_mes = monthrange(anio_actual, mes_current)
                inicio_conteo = hoy if hoy.month == mes_current and hoy.year == anio_actual else date(anio_actual, mes_current, 1)
                
                for d in range(inicio_conteo.day, ultimo_dia_mes + 1):
                    f = date(anio_actual, mes_current, d)
                    if f.weekday() == dia_semana_objetivo:
                        lista_fechas_reservar.append(f)

                # 2. Recolectar días del mes siguiente hasta el 10 inclusive
                if mes_current == 12:
                    mes_siguiente = 1
                    anio_siguiente = anio_actual + 1
                else:
                    mes_siguiente = mes_current + 1
                    anio_siguiente = anio_actual

                for d in range(1, 11):
                    f_sig = date(anio_siguiente, mes_siguiente, d)
                    if f_sig.weekday() == dia_semana_objetivo:
                        lista_fechas_reservar.append(f_sig)

                # 3. Guardar registros físicos de las reservas
                for fecha_evaluar in lista_fechas_reservar:
                    # CONTROL ANTIDUPLICADOS
                    if Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_evaluar).exists():
                        continue 
                    
                    sin_cupo = clase.cupos_para_fecha(fecha_evaluar) <= 0
                    
                    nueva_reserva = Reserva.objects.create(
                        usuario=request.user,
                        clase=clase,
                        fecha_clase=fecha_evaluar,
                        monto_pagado=Decimal(datos['monto']) / max(len(lista_fechas_reservar), 1),
                        estado_pago='total',
                        medio_pago='Tarjeta',
                        en_lista_de_espera=sin_cupo
                    )
                    if not reserva_principal:
                        reserva_principal = nueva_reserva
                
                # 4. Registrar la mensualidad en estado pagada
                Mensualidad.objects.update_or_create(
                    usuario=request.user,
                    actividad=clase.actividad,
                    mes=mes_current,
                    anio=anio_actual,
                    defaults={
                        'fecha_pago': hoy,
                        'estado': 'pagada'
                    }
                )
                
                reserva = reserva_principal
                mensaje_notificacion = f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre}. Cupos reservados hasta el día 10 del próximo mes."
            
            else:
                # Flujo normal de una clase única individual
                estado_final = 'seña' if datos['tipo_pago'] == 'senia' else 'total'
                reserva = Reserva.objects.create(
                    usuario=request.user,
                    clase=clase,
                    fecha_clase=fecha_inicial,
                    monto_pagado=datos['monto'],
                    estado_pago=estado_final,
                    medio_pago='Tarjeta',
                )
                mensaje_notificacion = f"Se realizó con éxito tu pago para la clase: {clase.actividad.nombre}"

            Notificacion.objects.create(
                usuario=request.user,
                mensaje=mensaje_notificacion
            )

        enviar_confirmacion(request.user, clase, reserva)
        del request.session['inscripcion_pendiente']
        return redirect('pago_confirmacion', reserva_id=reserva.id)

    return render(request, 'pago_tarjeta.html', {'monto': datos['monto']})


@login_required
def pago_mercadopago(request):
    """
    Prepara la transacción y redirige al usuario a la pasarela de Mercado Pago.
    Usa la URL fija y contiene control de errores de conexión.
    """
    datos = request.session.get('inscripcion_pendiente')
    if not datos:
        messages.error(request, 'No hay ninguna inscripción pendiente.')
        return redirect('grilla_actividades')
        
    # Guardamos el ID del usuario en la sesión para recuperarlo al volver
    request.session['inscripcion_pendiente']['usuario_id'] = request.user.id
    request.session.modified = True
    
    sdk = mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)
    BASE_URL = "https://pancake-energetic-preseason.ngrok-free.dev"
    
    preference_data = {
        "items": [
            {
                "title": "Reserva Sportify",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": float(datos['monto'])
            }
        ],
        "back_urls": {
            "success": f"{BASE_URL}/pago/exito/",
            "failure": f"{BASE_URL}/pago/error/",
            "pending": f"{BASE_URL}/pago/pendiente/",
        },
        "auto_return": "approved"
    }
    
    try:
        preference_response = sdk.preference().create(preference_data)
    except Exception as e:
        print(f"❌ Error de conexión crítico con Mercado Pago: {e}")
        messages.error(request, 'No se pudo establecer conexión con el servidor de pagos. Intenta más tarde.')
        return redirect('grilla_actividades')
    
    if preference_response.get("status") not in [200, 201]:
        error_detalle = preference_response.get("response", "Error desconocido")
        print(f"❌ Error interno en la pasarela: {error_detalle}")
        messages.error(request, 'Ocurrió un error interno al generar la orden de pago.')
        return redirect('grilla_actividades')
        
    preference = preference_response["response"]
    return redirect(preference["init_point"])


@login_required
def pago_exito(request):
    """
    Destino cuando el pago es aprobado. Usa get_or_create y el modelo 
    de usuario personalizado para evitar colisiones en la base de datos.
    """
    print("🟢 ENTRÓ A PAGO ÉXITO - PROCESANDO RESERVA")
    datos = request.session.get('inscripcion_pendiente')
    
    if not datos:
        messages.warning(request, 'La sesión de tu pago expiró o ya fue procesada.')
        return redirect('grilla_actividades')
        
    # Sumamos Notificacion al import local
    from .models import Clase, Reserva, Notificacion 
    
    clase = get_object_or_404(Clase, id=datos['clase_id'])
    usuario_id = datos.get('usuario_id')
    usuario_reserva = get_object_or_404(Usuario, id=usuario_id) if usuario_id else request.user
    
    with transaction.atomic():
        reserva, creado = Reserva.objects.get_or_create(
            usuario=usuario_reserva,
            clase=clase,
            fecha_clase=datos['fecha_clase'],
            defaults={
                'monto_pagado': datos['monto'],
                'estado_pago': 'seña' if datos['tipo_pago'] == 'senia' else 'total',
                'medio_pago': 'Mercado Pago'
            }
        )
        
    if creado:
        print(f"✅ Reserva {reserva.id} creada con éxito en la base de datos.")
        
        # =========================================================
        # 🔔 LOGICA DE NOTIFICACIÓN IDÉNTICA A LA TARJETA
        # =========================================================
        if datos.get('flujo_tipo') == 'mensualidad':
            mensaje_notificacion = f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre}. Cupos reservados hasta el día 10 del próximo mes."
        else:
            mensaje_notificacion = f"Se realizó con éxito tu pago para la clase: {clase.actividad.nombre}"

        # Guardamos la notificación para la campanita de la interfaz
        Notificacion.objects.create(
            usuario=usuario_reserva,
            mensaje=mensaje_notificacion
        )
        
        # Disparamos el mail automático usando tus datos procesados
        enviar_confirmacion(usuario_reserva, clase, reserva)
        
    else:
        print(f"ℹ️ La reserva {reserva.id} ya existía. Se evitó el IntegrityError.")

    if 'inscripcion_pendiente' in request.session:
        del request.session['inscripcion_pendiente']
        
    response = redirect('pago_confirmacion', reserva_id=reserva.id)
    response["ngrok-skip-browser-warning"] = "true"
    return response


def pago_error(request):
    """
    ESCENARIO: PAGO FALLIDO / RECHAZADO (Mercado Pago)
    Redirige a la pantalla de confirmación con la Cruz Roja.
    """
    print("❌ EL PAGO FUE RECHAZADO POR MERCADO PAGO")
    
    response = redirect('pago_confirmacion', reserva_id=0)
    response["ngrok-skip-browser-warning"] = "true"
    return response


# Sin @login_required para evitar rebotes de mercadopago
def pago_pendiente(request):
    messages.warning(request, 'El pago quedó pendiente')
    return redirect('http://127.0.0.1:8000/grilla/')


@login_required
def pago_confirmacion(request, reserva_id):
    if reserva_id == 0:
        return render(request, 'pago_confirmacion.html', {'exito': False})
    reserva = get_object_or_404(Reserva, id=reserva_id, usuario=request.user)
    return render(request, 'pago_confirmacion.html', {
        'exito': True,
        'reserva': reserva,
        'clase': reserva.clase,
    })


def enviar_confirmacion(usuario, clase, reserva):
    try:
        fecha_clase = reserva.fecha_clase
        if isinstance(fecha_clase, str):
            fecha_clase = datetime.strptime(fecha_clase, '%Y-%m-%d').date()
        send_mail(
            subject=f"Sportify - Inscripción confirmada: {clase.actividad.nombre}",
            message=f"Hola {usuario.first_name},\n\n"
                    f"Te inscribiste a la clase de {clase.actividad.nombre} del {fecha_clase.strftime('%d-%m-%Y')} a las {clase.horario}.\n"
                    f"Monto pagado: ${reserva.monto_pagado}\n"
                    f"Medio de pago: {reserva.medio_pago}\n\n"
                    f"¡Gracias por elegir Sportify!",
            from_email='sportifygymapp@gmail.com',
            recipient_list=[usuario.email],
            fail_silently=False,
        )
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
# =========================================================================
# 4. PANEL DE ADMINISTRACIÓN Y PROFESORES
# =========================================================================
'''
def panel_admin(request):
    if not request.user.is_authenticated or request.user.rol != 'admin':
        return redirect('login')

    ahora = date.today()
    pestania_activa = 'clases'  # Por defecto abre la de clases

    if request.method == 'POST':
        action = request.POST.get('action')

        # --- A. PROCESAR NUEVA ACTIVIDAD ---
        if action == 'crear_actividad':
            pestania_activa = 'clases'
            nombre = request.POST.get('nombre')
            
            if nombre:
                nombre_limpio = nombre.strip() 
                if Actividad.objects.filter(nombre__iexact=nombre_limpio).exists():
                    messages.error(request, "Error: La actividad ya se encuentra registrada en el sistema.")
                else:
                    Actividad.objects.create(nombre=nombre_limpio.capitalize())
                    messages.success(request, f"Actividad '{nombre_limpio.capitalize()}' creada con éxito.")
            else:
                messages.error(request, "El nombre de la actividad no puede estar vacío.")

        # --- B. PROCESAR PROGRAMAR CLASE ---
        elif action == 'crear_clase':
            pestania_activa = 'clases'
            actividad_id = request.POST.get('actividad')
            profesor_id = request.POST.get('profesor')
            fecha_str = request.POST.get('fecha')
            horario_str = request.POST.get('horario')

            if not profesor_id or profesor_id == "":
                messages.error(request, "Error: Debe seleccionar obligatoriamente un profesor para la clase.")
            elif not fecha_str or not actividad_id or not horario_str:
                messages.error(request, "Por favor, complete todos los campos obligatorios.")
            else:
                fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                
                try:
                    horario_obj = datetime.strptime(horario_str, "%H:%M").time()
                except ValueError:
                    horario_obj = datetime.strptime(horario_str, "%H:%M:%S").time()

                if horario_obj.minute != 0 or horario_obj.second != 0:
                    messages.error(request, "Error: Las clases deben comenzar estrictamente en punto (Ej: 19:00).")
                elif horario_obj.hour < 8 or horario_obj.hour > 20:
                    messages.error(request, "Error: El gimnasio se encuentra cerrado. Las clases se dictan únicamente de 08 a 20 hs.")
                elif fecha_obj < ahora:
                    messages.error(request, "Error: No se pueden programar clases en una fecha que ya pasó.")
                elif fecha_obj.weekday() == 6:
                    messages.error(request, "Error: El gimnasio permanece cerrado los domingos.")
                else:
                    dia_semana_nuevo = fecha_obj.weekday()

                    clases_profe_horario = Clase.objects.filter(
                        profesor_id=profesor_id,
                        horario=horario_obj,
                        fecha__lte=fecha_obj
                    )

                    profesor_ocupado = False
                    for c in clases_profe_horario:
                        if c.dia_semana_num == dia_semana_nuevo:
                            profesor_ocupado = True
                            break

                    if profesor_ocupado:
                        messages.error(request, f"Error: El profesor ya se encuentra asignado a otra clase en ese mismo día y horario.")
                    else:
                        colision = Clase.objects.filter(actividad_id=actividad_id, horario=horario_obj)
                        ya_existe_choque = False
                        for c in colision:
                            if c.dia_semana_num == dia_semana_nuevo:
                                ya_existe_choque = True
                                break

                        if ya_existe_choque:
                            messages.error(request, "Error: ya existen clases de esa actividad en el horario y dia seleccionado.")
                        else:
                            actividad = Actividad.objects.get(id=actividad_id)
                            profesor = Profesor.objects.get(id=profesor_id)

                            Clase.objects.create(
                                actividad=actividad,
                                profesor=profesor,
                                fecha=fecha_obj,
                                horario=horario_obj
                            )
                            messages.success(request, "Clases creadas con éxito.")

        # --- C. PROCESAR REGISTRAR PROFESOR ---
        elif action == 'registrar_profesor':
            pestania_activa = 'profesores'
            
            # 1. Capturamos los datos
            dni = request.POST.get('dni', '').strip()
            nombre = request.POST.get('nombre', '').strip()
            apellido = request.POST.get('apellido', '').strip()
            fecha_nac = request.POST.get('fecha_nacimiento', '').strip()
            telefono = request.POST.get('telefono', '').strip()
            correo = request.POST.get('correo', '').strip()
            contrasenia = request.POST.get('contrasenia', '')

            import re
            import uuid
            
            errores = {}

            # 2. Validaciones Acumulativas (Campo por campo)
            if not all([dni, nombre, apellido, fecha_nac, telefono, correo, contrasenia]):
                errores['general'] = 'Por favor, complete todos los campos obligatorios.'

            if nombre and not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+$', nombre):
                errores['nombre'] = 'El nombre solo puede contener letras y espacios.'
                
            if apellido and not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+$', apellido):
                errores['apellido'] = 'El apellido solo puede contener letras y espacios.'

            if dni:
                if not dni.isdigit():
                    errores['dni'] = 'El DNI solo puede contener números.'
                elif Usuario.objects.filter(username=dni).exists():
                    errores['dni'] = 'Este DNI ya se encuentra registrado en el sistema.'

            if correo:
                if "@" not in correo or ".com" not in correo:
                    errores['correo'] = 'El email debe seguir el formato: ejemplo@gmail.com'
                elif Usuario.objects.filter(email=correo).exists():
                    errores['correo'] = 'Este correo ya se encuentra registrado.'

            if fecha_nac:
                try:
                    fecha_nac_dt = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                except ValueError:
                    try:
                        fecha_nac_dt = datetime.strptime(fecha_nac, '%d/%m/%Y').date()
                    except ValueError:
                        try:
                            fecha_nac_dt = datetime.strptime(fecha_nac, '%m/%d/%Y').date()
                        except ValueError:
                            errores['fecha_nacimiento'] = 'Formato de fecha inválido.'
                            fecha_nac_dt = None
                
                if fecha_nac_dt:
                    edad = relativedelta(date.today(), fecha_nac_dt).years
                    if edad < 18:
                        errores['fecha_nacimiento'] = 'El profesor debe ser mayor de 18 años.'

            if telefono and (not telefono.isdigit() or len(telefono) < 8 or len(telefono) > 12):
                errores['telefono'] = 'El teléfono debe contener solo números (entre 8 y 12 dígitos).'

            if contrasenia and len(contrasenia) < 4:
                errores['contrasenia'] = 'La contraseña debe tener al menos 4 caracteres.'

            # 3. Control de Errores: Si hay algo en el diccionario, volvemos al formulario
            if errores:
                # ATENCIÓN ACÁ: Tenés que pasarle el diccionario de errores y los valores que tipeó
                # para que los inputs no queden en blanco cuando la página recargue.
                contexto = {
                    'errores_profesor': errores,
                    'valores_profesor': request.POST,
                    'pestania_activa': 'profesores',
                    # IMPORTANTE: Acá deberías sumar cualquier otro dato que necesite tu panel_admin
                    # (ej: lista de profesores, clases, etc)
                }
                return render(request, 'panel_admin.html', contexto)

            # 4. Registro Exitoso (Si el diccionario está vacío, entra acá)
            try:
                with transaction.atomic():
                    token_unico = str(uuid.uuid4())

                    user = Usuario.objects.create(
                        username=dni,
                        dni=dni,
                        email=correo,
                        first_name=nombre,
                        last_name=apellido,
                        telefono=telefono,
                        fecha_nacimiento=fecha_nac_dt,
                        rol='profesor',
                        is_active=True,
                        reset_token=token_unico,
                        password=make_password(contrasenia)
                    )
                    
                    Profesor.objects.create(
                        usuario=user,
                        nombre=nombre,
                        apellido=apellido,
                        dni=dni,                    
                        telefono=telefono,           
                        correo=correo,              
                        fecha_nacimiento=fecha_nac_dt,  
                        especialidad=""              
                    )
                    
                    Notificacion.objects.create(
                        usuario=user,
                        mensaje=f"¡Bienvenido a Sportify, {nombre}! Tu perfil de profesor ha sido configurado.",
                        leida=False,
                    )
                    
                    base_url = request.build_absolute_uri('/')[:-1] 
                    reset_link = f"{base_url}/reset-password/{token_unico}/"
                    asunto = "¡Bienvenido a Sportify! Configura tu cuenta de Profesor"
                    
                    mensaje_texto = f"""
Hola {nombre},
Te damos la bienvenida a Sportify. El administrador te ha dado de alta exitosamente.
Ya podés iniciar sesión utilizando tu DNI como usuario. Si lo deseás, podés modificar tu clave ingresando aquí:
{reset_link}
Tu usuario de ingreso es tu DNI: {dni}
"""

                    mensaje_html = f"""
                    <div style="background-color:#000000; padding:40px; font-family:Poppins,sans-serif; text-align:center;">
                        <h1 style="color:#00ff88; margin-bottom:10px;">SPORTIFY</h1>
                        <h2 style="color:white; margin-bottom:25px;">¡Bienvenido al Equipo!</h2>
                        <p style="color:#cccccc; margin-bottom:20px; font-size:15px;">
                            Hola {nombre} {apellido}, has sido registrado con éxito como <b>Profesor</b>.
                        </p>
                        <p style="color:#cccccc; margin-bottom:35px; font-size:15px;">
                            Tu usuario de ingreso es tu DNI: {dni}.<br>
                            Podés ingresar de inmediato. Si querés modificar tu clave de acceso seguro, hacé clic abajo:
                        </p>
                        <a href="{reset_link}" style="background-color:#00ff88; color:black; padding:14px 28px; border-radius:10px; text-decoration:none; font-weight:700; display:inline-block; font-size:15px;">
                            Cambiar contraseña
                        </a>
                        <p style="color:#777777; margin-top:35px; font-size:13px;">
                            Si este correo no te corresponde, por favor comunícate con la administración.
                        </p>
                    </div>
                    """

                    email_message = EmailMultiAlternatives(
                        asunto,
                        mensaje_texto,
                        settings.EMAIL_HOST_USER,
                        [correo]
                    )
                    email_message.attach_alternative(mensaje_html, "text/html")
                    email_message.send()

                    messages.success(request, f"Profesor {apellido},{nombre} dado de alta con éxito.")
                    return redirect('panel_admin')

            except Exception as e:
                messages.error(request, f"Registro fallido. Ocurrió un error inesperado: {e}")
                return redirect('panel_admin')

        # --- D. ACTUALIZAR PRECIOS GLOBALES (Reincorporado) ---
        # --- D. ACTUALIZAR PRECIOS GLOBALES (Reincorporado) ---
        elif action == 'actualizar_precios_globales':
            pestania_activa = 'pagos'
            actividades = Actividad.objects.all()
            try:
                with transaction.atomic():
                    for act in actividades:
                        input_clase = f"precio_clase_{act.id}"
                        if input_clase in request.POST:
                            val_clase = request.POST.get(input_clase, '').strip()
                            if val_clase != '':
                                act.precio_clase = float(val_clase)

                        input_mes = f"precio_mes_{act.id}"
                        if input_mes in request.POST:
                            val_mes = request.POST.get(input_mes, '').strip()
                            if val_mes != '':
                                act.precio_mensualidad = float(val_mes)
                        
                        act.save()
                messages.success(request, "Tarifas actualizadas correctamente")
                
            except ValidationError as e:
                # ACÁ DESARMAMOS EL ERROR FEO
                if hasattr(e, 'message_dict'):
                    for campo, errores in e.message_dict.items():
                        for error in errores:
                            messages.error(request, f"Error en {act.nombre}: {error}")
                else:
                    for error in e.messages:
                        messages.error(request, f"Error en {act.nombre}: {error}")
                        
            except ValueError:
                messages.error(request, f"Error en {act.nombre}: Ingresaste un valor numérico inválido.")
                
            except Exception as e:
                messages.error(request, f"Error inesperado al guardar tarifas: {e}")
    # Generación de contexto para el panel admin GET
    año = int(request.GET.get('anio', ahora.year))
    mes = int(request.GET.get('mes', ahora.month))
    
    todas_las_clases = Clase.objects.all()

    cal = calendar.Calendar(firstweekday=0)
    semanas_matriz = cal.monthdayscalendar(año, mes)
    meses_nombres = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    clases_por_dia = {}
    for semana in semanas_matriz:
        for dia in semana:
            if dia != 0:
                fecha_casillero = date(año, mes, dia)
                dia_semana_casillero = fecha_casillero.weekday()
                
                clases_por_dia[dia] = []
                for clase in todas_las_clases:
                    if clase.dia_semana_num == dia_semana_casillero and fecha_casillero >= clase.fecha:
                        clase.cupos_mostrar = clase.cupos_para_fecha(fecha_casillero)
                        clases_por_dia[dia].append(clase)

    # Cálculo de ganancias en tiempo real (Reincorporado)
    resultado_ganancias = Reserva.objects.aggregate(total=Sum('monto_pagado'))
    total_ganancias = resultado_ganancias['total'] if resultado_ganancias['total'] is not None else 0.0

    context = {
        'actividades': Actividad.objects.all(),
        'profesores': Profesor.objects.all(),
        'semanas_matriz': semanas_matriz,
        'mes_nombre': meses_nombres[mes],
        'mes_actual': mes,
        'anio_actual': año,
        'clases_por_dia': clases_por_dia,
        'hoy': ahora,
        'pestania_activa': pestania_activa,
        'total_ganancias': total_ganancias, # Inyectado al context
    }
    return render(request, 'panel_admin.html', context)
'''
def panel_admin(request):
    if not request.user.is_authenticated or request.user.rol != 'admin':
        return redirect('login')

    # =========================================================
    # PESCAMOS LOS ERRORES DE LA SESIÓN (Si venimos de un error)
    # =========================================================
    errores_profesor = request.session.pop('errores_profesor', {})
    valores_profesor = request.session.pop('valores_profesor', {})
    mostrar_modal_profesor = request.session.pop('mostrar_modal_profesor', False)
    
    # Tomamos la pestaña activa de la sesión si falló algo, sino por defecto 'clases'
    pestania_activa = request.session.pop('pestania_activa', 'clases') 

    ahora = date.today()

    if request.method == 'POST':
        action = request.POST.get('action')

        # --- A. PROCESAR NUEVA ACTIVIDAD ---
        if action == 'crear_actividad':
            pestania_activa = 'clases'
            nombre = request.POST.get('nombre')
            
            if nombre:
                nombre_limpio = nombre.strip() 
                if Actividad.objects.filter(nombre__iexact=nombre_limpio).exists():
                    messages.error(request, "Error: La actividad ya se encuentra registrada en el sistema.")
                else:
                    Actividad.objects.create(nombre=nombre_limpio.capitalize())
                    messages.success(request, f"Actividad '{nombre_limpio.capitalize()}' creada con éxito.")
            else:
                messages.error(request, "El nombre de la actividad no puede estar vacío.")

        # --- B. PROCESAR PROGRAMAR CLASE ---
        elif action == 'crear_clase':
            pestania_activa = 'clases'
            actividad_id = request.POST.get('actividad')
            profesor_id = request.POST.get('profesor')
            fecha_str = request.POST.get('fecha')
            horario_str = request.POST.get('horario')

            if not profesor_id or profesor_id == "":
                messages.error(request, "Error: Debe seleccionar obligatoriamente un profesor para la clase.")
            elif not fecha_str or not actividad_id or not horario_str:
                messages.error(request, "Por favor, complete todos los campos obligatorios.")
            else:
                fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                
                try:
                    horario_obj = datetime.strptime(horario_str, "%H:%M").time()
                except ValueError:
                    horario_obj = datetime.strptime(horario_str, "%H:%M:%S").time()

                if horario_obj.minute != 0 or horario_obj.second != 0:
                    messages.error(request, "Error: Las clases deben comenzar estrictamente en punto (Ej: 19:00).")
                elif horario_obj.hour < 8 or horario_obj.hour > 20:
                    messages.error(request, "Error: El gimnasio se encuentra cerrado. Las clases se dictan únicamente de 08 a 20 hs.")
                elif fecha_obj < ahora:
                    messages.error(request, "Error: No se pueden programar clases en una fecha que ya pasó.")
                elif fecha_obj.weekday() == 6:
                    messages.error(request, "Error: El gimnasio permanece cerrado los domingos.")
                else:
                    dia_semana_nuevo = fecha_obj.weekday()

                    clases_profe_horario = Clase.objects.filter(
                        profesor_id=profesor_id,
                        horario=horario_obj,
                        fecha__lte=fecha_obj
                    )

                    profesor_ocupado = False
                    for c in clases_profe_horario:
                        if c.dia_semana_num == dia_semana_nuevo:
                            profesor_ocupado = True
                            break

                    if profesor_ocupado:
                        messages.error(request, f"Error: El profesor ya se encuentra asignado a otra clase en ese mismo día y horario.")
                    else:
                        colision = Clase.objects.filter(actividad_id=actividad_id, horario=horario_obj)
                        ya_existe_choque = False
                        for c in colision:
                            if c.dia_semana_num == dia_semana_nuevo:
                                ya_existe_choque = True
                                break

                        if ya_existe_choque:
                            messages.error(request, "Error: ya existen clases de esa actividad en el horario y dia seleccionado.")
                        else:
                            actividad = Actividad.objects.get(id=actividad_id)
                            profesor = Profesor.objects.get(id=profesor_id)

                            Clase.objects.create(
                                actividad=actividad,
                                profesor=profesor,
                                fecha=fecha_obj,
                                horario=horario_obj
                            )
                            messages.success(request, "Clases creadas con éxito.")

        # --- C. PROCESAR REGISTRAR PROFESOR ---
        elif action == 'registrar_profesor':
            pestania_activa = 'profesores'
            
            # 1. Capturamos los datos
            dni = request.POST.get('dni', '').strip()
            nombre = request.POST.get('nombre', '').strip()
            apellido = request.POST.get('apellido', '').strip()
            fecha_nac = request.POST.get('fecha_nacimiento', '').strip()
            telefono = request.POST.get('telefono', '').strip()
            correo = request.POST.get('correo', '').strip()
            contrasenia = request.POST.get('contrasenia', '')

            import re
            import uuid
            
            errores = {}

            # 2. Validaciones Acumulativas (Campo por campo)
            if not all([dni, nombre, apellido, fecha_nac, telefono, correo, contrasenia]):
                errores['general'] = 'Por favor, complete todos los campos obligatorios.'

            if nombre and not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+$', nombre):
                errores['nombre'] = 'El nombre solo puede contener letras y espacios.'
                
            if apellido and not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+$', apellido):
                errores['apellido'] = 'El apellido solo puede contener letras y espacios.'

            if dni:
                if not dni.isdigit():
                    errores['dni'] = 'El DNI solo puede contener números.'
                elif len(dni) < 7 or len(dni) > 9:
                    errores['dni'] = 'El DNI debe tener entre 7 y 9 dígitos.'
                elif Usuario.objects.filter(username=dni).exists():
                    errores['dni'] = 'Este DNI ya se encuentra registrado en el sistema.'

            if correo:
                if "@" not in correo or ".com" not in correo:
                    errores['correo'] = 'El email debe seguir el formato: ejemplo@gmail.com'
                elif Usuario.objects.filter(email=correo).exists():
                    errores['correo'] = 'Este correo ya se encuentra registrado.'

            if fecha_nac:
                try:
                    fecha_nac_dt = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                except ValueError:
                    try:
                        fecha_nac_dt = datetime.strptime(fecha_nac, '%d/%m/%Y').date()
                    except ValueError:
                        try:
                            fecha_nac_dt = datetime.strptime(fecha_nac, '%m/%d/%Y').date()
                        except ValueError:
                            errores['fecha_nacimiento'] = 'Formato de fecha inválido.'
                            fecha_nac_dt = None
                
                if fecha_nac_dt:
                    edad = relativedelta(date.today(), fecha_nac_dt).years
                    if edad < 18:
                        errores['fecha_nacimiento'] = 'El profesor debe ser mayor de 18 años.'

            if telefono and (not telefono.isdigit() or len(telefono) < 8 or len(telefono) > 12):
                errores['telefono'] = 'El teléfono debe contener solo números (entre 8 y 12 dígitos).'

            if contrasenia and len(contrasenia) < 4:
                errores['contrasenia'] = 'La contraseña debe tener al menos 4 caracteres.'

            # 3. Control de Errores: Guardamos en sesión y redirigimos
            if errores:
                request.session['errores_profesor'] = errores
                request.session['valores_profesor'] = request.POST.dict()
                request.session['mostrar_modal_profesor'] = True
                request.session['pestania_activa'] = 'profesores'
                return redirect('panel_admin')

            # 4. Registro Exitoso (Si el diccionario está vacío, entra acá)
            try:
                with transaction.atomic():
                    token_unico = str(uuid.uuid4())

                    user = Usuario.objects.create(
                        username=dni,
                        dni=dni,
                        email=correo,
                        first_name=nombre,
                        last_name=apellido,
                        telefono=telefono,
                        fecha_nacimiento=fecha_nac_dt,
                        rol='profesor',
                        is_active=True,
                        reset_token=token_unico,
                        password=make_password(contrasenia)
                    )
                    
                    Profesor.objects.create(
                        usuario=user,
                        nombre=nombre,
                        apellido=apellido,
                        dni=dni,                    
                        telefono=telefono,           
                        correo=correo,              
                        fecha_nacimiento=fecha_nac_dt,  
                        especialidad=""              
                    )
                    
                    Notificacion.objects.create(
                        usuario=user,
                        mensaje=f"¡Bienvenido a Sportify, {nombre}! Tu perfil de profesor ha sido configurado.",
                        leida=False,
                    )
                    
                    base_url = request.build_absolute_uri('/')[:-1] 
                    reset_link = f"{base_url}/reset-password/{token_unico}/"
                    asunto = "¡Bienvenido a Sportify! Configura tu cuenta de Profesor"
                    
                    mensaje_texto = f"""
Hola {nombre},
Te damos la bienvenida a Sportify. El administrador te ha dado de alta exitosamente.
Ya podés iniciar sesión utilizando tu DNI como usuario. Si lo deseás, podés modificar tu clave ingresando aquí:
{reset_link}
Tu usuario de ingreso es tu DNI: {dni}
"""

                    mensaje_html = f"""
                    <div style="background-color:#000000; padding:40px; font-family:Poppins,sans-serif; text-align:center;">
                        <h1 style="color:#00ff88; margin-bottom:10px;">SPORTIFY</h1>
                        <h2 style="color:white; margin-bottom:25px;">¡Bienvenido al Equipo!</h2>
                        <p style="color:#cccccc; margin-bottom:20px; font-size:15px;">
                            Hola {nombre} {apellido}, has sido registrado con éxito como <b>Profesor</b>.
                        </p>
                        <p style="color:#cccccc; margin-bottom:35px; font-size:15px;">
                            Tu usuario de ingreso es tu DNI: {dni}.<br>
                            Podés ingresar de inmediato. Si querés modificar tu clave de acceso seguro, hacé clic abajo:
                        </p>
                        <a href="{reset_link}" style="background-color:#00ff88; color:black; padding:14px 28px; border-radius:10px; text-decoration:none; font-weight:700; display:inline-block; font-size:15px;">
                            Cambiar contraseña
                        </a>
                        <p style="color:#777777; margin-top:35px; font-size:13px;">
                            Si este correo no te corresponde, por favor comunícate con la administración.
                        </p>
                    </div>
                    """

                    email_message = EmailMultiAlternatives(
                        asunto,
                        mensaje_texto,
                        settings.EMAIL_HOST_USER,
                        [correo]
                    )
                    email_message.attach_alternative(mensaje_html, "text/html")
                    email_message.send()

                    messages.success(request, f"Profesor {apellido},{nombre} dado de alta con éxito.")
                    return redirect('panel_admin')

            except Exception as e:
                messages.error(request, f"Registro fallido. Ocurrió un error inesperado: {e}")
                return redirect('panel_admin')

        # --- D. ACTUALIZAR PRECIOS GLOBALES ---
        elif action == 'actualizar_precios_globales':
            pestania_activa = 'pagos'
            actividades = Actividad.objects.all()
            try:
                with transaction.atomic():
                    for act in actividades:
                        input_clase = f"precio_clase_{act.id}"
                        if input_clase in request.POST:
                            val_clase = request.POST.get(input_clase, '').strip()
                            if val_clase != '':
                                act.precio_clase = float(val_clase)

                        input_mes = f"precio_mes_{act.id}"
                        if input_mes in request.POST:
                            val_mes = request.POST.get(input_mes, '').strip()
                            if val_mes != '':
                                act.precio_mensualidad = float(val_mes)
                        
                        act.save()
                messages.success(request, "Tarifas actualizadas correctamente")
                
            except ValidationError as e:
                if hasattr(e, 'message_dict'):
                    for campo, errores in e.message_dict.items():
                        for error in errores:
                            messages.error(request, f"Error en {act.nombre}: {error}")
                else:
                    for error in e.messages:
                        messages.error(request, f"Error en {act.nombre}: {error}")
                        
            except ValueError:
                messages.error(request, f"Error en {act.nombre}: Ingresaste un valor numérico inválido.")
                
            except Exception as e:
                messages.error(request, f"Error inesperado al guardar tarifas: {e}")

    # =========================================================
    # ARMADO DE DATOS (ESTO ES LO QUE SE ESTABA SALTEANDO)
    # =========================================================
    año = int(request.GET.get('anio', ahora.year))
    mes = int(request.GET.get('mes', ahora.month))
    
    todas_las_clases = Clase.objects.all()

    cal = calendar.Calendar(firstweekday=0)
    semanas_matriz = cal.monthdayscalendar(año, mes)
    meses_nombres = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    clases_por_dia = {}
    for semana in semanas_matriz:
        for dia in semana:
            if dia != 0:
                fecha_casillero = date(año, mes, dia)
                dia_semana_casillero = fecha_casillero.weekday()
                
                clases_por_dia[dia] = []
                for clase in todas_las_clases:
                    if clase.dia_semana_num == dia_semana_casillero and fecha_casillero >= clase.fecha:
                        clase.cupos_mostrar = clase.cupos_para_fecha(fecha_casillero)
                        clases_por_dia[dia].append(clase)

    # Cálculo de ganancias en tiempo real
    resultado_ganancias = Reserva.objects.aggregate(total=Sum('monto_pagado'))
    total_ganancias = resultado_ganancias['total'] if resultado_ganancias['total'] is not None else 0.0

    # =========================================================
    # EL CONTEXTO FINAL (Ahora tiene todo)
    # =========================================================
    context = {
        'actividades': Actividad.objects.all(),
        'profesores': Profesor.objects.all(),
        'semanas_matriz': semanas_matriz,
        'mes_nombre': meses_nombres[mes],
        'mes_actual': mes,
        'anio_actual': año,
        'clases_por_dia': clases_por_dia,
        'hoy': ahora,
        'pestania_activa': pestania_activa,
        'total_ganancias': total_ganancias, 
        # Le pasamos los errores que pescamos arriba
        'errores_profesor': errores_profesor,
        'valores_profesor': valores_profesor,
        'mostrar_modal_profesor': mostrar_modal_profesor,
    }
    return render(request, 'panel_admin.html', context)

@login_required
def guardar_precios_admin(request):
    if request.method == 'POST':
        actividades = Actividad.objects.all()
        try:
            with transaction.atomic():
                for act in actividades:
                    input_clase = f"precio_clase_{act.id}"
                    if input_clase in request.POST:
                        val_clase = request.POST.get(input_clase, '').strip()
                        if val_clase != '':
                            act.precio_clase = float(val_clase)

                    input_mes = f"precio_mes_{act.id}"
                    if input_mes in request.POST:
                        val_mes = request.POST.get(input_mes, '').strip()
                        if val_mes != '':
                            act.precio_mensualidad = float(val_mes)
                    
                    # Al hacer save(), salta al models.py y verifica las reglas
                    act.save()
            
            messages.success(request, "Tarifas actualizadas correctamente")
            
        except ValidationError as e:
            # ACÁ ES DONDE DESARMAMOS EL DICCIONARIO FEO
            if hasattr(e, 'message_dict'):
                for campo, errores in e.message_dict.items():
                    for error in errores:
                        messages.error(request, f"Revisá la actividad {act.nombre}: {error}")
            else:
                for error in e.messages:
                    messages.error(request, f"Revisá la actividad {act.nombre}: {error}")
                    
        except Exception as e:
            # Si cae acá, es porque rompió otra cosa ajena a los precios
            messages.error(request, "Ocurrió un error inesperado al procesar los montos.")

        return redirect('panel_admin')
        
@login_required
def asignar_profesor_clase(request, clase_id):
    if request.user.rol != 'admin':
        return redirect('grilla_actividades')

    if request.method == 'POST':
        clase = get_object_or_404(Clase, id=clase_id)
        profesor_id = request.POST.get('profesor_id')
        fecha_clase = request.POST.get('fecha_clase') 

        if profesor_id:
            clase.profesor = get_object_or_404(Profesor, id=profesor_id)
        else:
            clase.profesor = None
        clase.save()
        messages.success(request, "Profesor asignado con éxito a la clase.")
        
        if fecha_clase:
            partes = fecha_clase.split('-') 
            return redirect(f"/?anio={partes[0]}&mes={partes[1]}&dia_sel={int(partes[2])}")
            
    return redirect('grilla_actividades')


# =========================================================================
# 5. HISTORIAL DE PAGOS
# =========================================================================

@login_required
def historial_pagos(request):
    pagos = Reserva.objects.filter(usuario=request.user).order_by('-fecha_reserva')

    hoy = date.today()
    dia_hoy = hoy.day
    mes_hoy = hoy.month
    anio_hoy = hoy.year

    if mes_hoy == 1:
        mes_anterior = 12
        anio_anterior = anio_hoy - 1
    else:
        mes_anterior = mes_hoy - 1
        anio_anterior = anio_hoy

    mensualidades_actuales = Mensualidad.objects.filter(
        usuario=request.user,
        mes=mes_hoy,
        anio=anio_hoy
    )
    
    mensualidades_anteriores = Mensualidad.objects.filter(
        usuario=request.user,
        mes=mes_anterior,
        anio=anio_anterior,
        estado='pagada'
    )

    resultados_mensualidad = []
    actividades_procesadas = set()

    for m in mensualidades_actuales:
        actividades_procesadas.add(m.actividad.id)
        
        if m.estado == 'pagada':
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'estado': 'pagada',
                'mensaje': f'Su mensualidad de {m.actividad.nombre} está paga. ¡Puede disfrutar de su actividad!'
            })
        elif m.estado == 'pendiente' and dia_hoy <= 10:
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'estado': 'pendiente',
                'mensaje': f'Su mensualidad de {m.actividad.nombre} está pendiente de pago. Por favor abone antes del día 11.'
            })
        elif m.estado == 'vencida' or (m.estado == 'pendiente' and dia_hoy > 10):
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'estado': 'vencida',
                'mensaje': f'Tu mensualidad de {m.actividad.nombre} ha sido suspendida por falta de pago. El vencimiento fue el día 10 del corriente mes.'
            })

    if dia_hoy <= 10:
        for m_ant in mensualidades_anteriores:
            if m_ant.actividad.id not in actividades_procesadas:
                actividades_procesadas.add(m_ant.actividad.id)
                resultados_mensualidad.append({
                    'actividad': m_ant.actividad.nombre,
                    'estado': 'pagada',
                    'mensaje': f'Su mensualidad de {m_ant.actividad.nombre} se encuentra vigente (Período de gracia de renovación activo hasta el 10/{mes_hoy}).'
                })

    if not resultados_mensualidad:
        resultados_mensualidad.append({
            'actividad': None,
            'estado': 'sin_mensualidad',
            'mensaje': 'Usted no posee ninguna mensualidad vigente. Puede solicitar su mensualidad desde el cronograma.'
        })

    context = {
        'pagos': pagos,
        'resultados_mensualidad': resultados_mensualidad,
    }
    return render(request, 'gestion/historial_pagos.html', context)


# =========================================================================
# 6. NOTIFICACIONES
# =========================================================================

@login_required
def ver_notificaciones(request):
    notificaciones=Notificacion.objects.filter(usuario=request.user).order_by('-fecha')
    return render(request, 'gestion/notificaciones.html', {'notificaciones': notificaciones})

@login_required
def marcar_leida(request, notificacion_id):
    notificacion = Notificacion.objects.get(
        id=notificacion_id,
        usuario=request.user
    )
    notificacion.leida = True
    notificacion.save()
    return redirect('ver_notificaciones')

@login_required
def borrar_notificacion(request, notificacion_id):
    notificacion = Notificacion.objects.get(
        id=notificacion_id,
        usuario=request.user
    )
    notificacion.delete()
    return redirect('ver_notificaciones')

@login_required
def borrar_todas_notificaciones(request):
    Notificacion.objects.filter(usuario=request.user).delete()
    return redirect('ver_notificaciones')


# =========================================================================
# 7. GENERACIÓN DE REPORTES (PDF)
# =========================================================================

@login_required
def comprobante_pdf(request,reserva_id):
    reserva=get_object_or_404(
        Reserva,id=reserva_id,usuario=request.user
    )
    response=HttpResponse(content_type='application/pdf')
    response['Content-Disposition']=(
        f'attachment; filename="comprobante_Sportify.pdf"')
    pdf=canvas.Canvas(response,pagesize=A4)
    width,height=A4
    logo_path=os.path.join(
        settings.BASE_DIR,'static','img','logo_Sportify.png'
    )
    if os.path.exists(logo_path):
        pdf.drawImage(
            ImageReader(logo_path),
            220,
            height -140,
            width=150,
            height=100,
            mask='auto'
        )
    
    pdf.setFont("Helvetica-Bold",24)
    pdf.drawCentredString(width/2,height -180,"COMPROBANTE DE PAGO")

    pdf.drawCentredString(width/2,height -240, f" N° OPERACIÓN: {reserva.id}")

    pdf.rect(40,220,515,420)

    if os.path.exists(logo_path):
        pdf.saveState()
        pdf.setFillAlpha(0.08)
        pdf.drawImage(
            ImageReader(logo_path),
            120,
            330,
            width=350,
            height=250,
            mask='auto'
        )
        pdf.restoreState()

    y=height -330
    datos=[
        ("DNI DEL USUARIO:", request.user.username),
        ("ACTIVIDAD:",reserva.clase.actividad.nombre),
        ("FECHA DE LA CLASE:",str(reserva.fecha_clase)),
        ("MONTO PAGADO:",f"${reserva.monto_pagado}"),
        ("MEDIO DE PAGO:",reserva.medio_pago),
        ("ESTADO:",reserva.estado_pago),
        (
            "FECHA Y HORA DE EMISIÓN:",
            timezone.localtime(reserva.fecha_reserva).strftime("%d/%m/%Y %H:%M")
        )
    ]
    for titulo,valor in datos:
        pdf.setFont("Helvetica-Bold",16)
        pdf.drawString(60,y,titulo)
        pdf.setFont("Helvetica",16)
        pdf.drawString(340,y,str(valor))
        y-=42
        
    pdf.rect(40,80,515,120)
    pdf.setFont("Helvetica-Bold",18)
    pdf.drawCentredString(
        width/2,
        175,
        "DETALLE DEL PAGO"
    )
    pdf.line(40,150,555,150)
    pdf.setFont("Helvetica-Bold",14)
    pdf.drawString(50,125,"DESCRIPCIÓN")
    pdf.drawString(430,125,"IMPORTE")
    pdf.setFont("Helvetica",14)
    pdf.drawString(
        50,95,f"Clase: {reserva.clase.actividad.nombre}"
    )
    pdf.drawString(
        430,95,f"${reserva.monto_pagado}"
    )
    pdf.setFont("Helvetica-Bold",18)
    pdf.drawCentredString(width/2,40,"GRACIAS POR SER PARTE DE SPORTIFY!")
    pdf.save()
    return response


# =========================================================================
# 8. APIS JSON PARA JAVASCRIPT
# =========================================================================

def detalle_clase_api(request, clase_id):
    clase = get_object_or_404(Clase, id=clase_id)
    fecha_str = request.GET.get('fecha')
    ya_inscripto = False
    en_espera = False
    ya_mensualizado = False
    choque_horario = False
    actividad_choque_nombre = None
    
    if fecha_str:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        cupos = clase.cupos_para_fecha(fecha)
        if request.user.is_authenticated:
            reserva_user = Reserva.objects.filter(
                usuario=request.user, clase=clase, fecha_clase=fecha
            ).first()
            if reserva_user:
                ya_inscripto = True
                en_espera = reserva_user.en_lista_de_espera

            # Mensualidad mes actual
            mensualidad_mes_actual = Mensualidad.objects.filter(
                usuario=request.user, 
                actividad=clase.actividad,  
                mes=fecha.month, 
                anio=fecha.year, 
                estado='pagada'
            ).exists()

            # Mensualidad mes anterior
            mensualidad_mes_anterior = False
            if fecha.day <= 10:
                if fecha.month == 1:
                    mes_ant, anio_ant = 12, fecha.year - 1
                else:
                    mes_ant, anio_ant = fecha.month - 1, fecha.year

                mensualidad_mes_anterior = Mensualidad.objects.filter(
                    usuario=request.user, 
                    actividad=clase.actividad, 
                    mes=mes_ant, 
                    anio=anio_ant, 
                    estado='pagada'
                ).exists()

            ya_mensualizado = mensualidad_mes_actual or mensualidad_mes_anterior

            # Verificación choque de horario
            reserva_choque = Reserva.objects.filter(
                usuario=request.user,
                fecha_clase=fecha,
                clase__horario=clase.horario,
                en_lista_de_espera=False
            ).exclude(clase=clase).select_related('clase__actividad').first()

            if reserva_choque:
                actividad_choque_nombre = reserva_choque.clase.actividad.nombre
                choque_horario = True
    else:
        cupos = getattr(clase.actividad, 'capacidad_maxima', 30)

    es_admin = request.user.is_authenticated and request.user.rol == 'admin'
    cola_espera_data = []
    todos_profes_data = []

    if es_admin and fecha_str:
        cola = Reserva.objects.filter(clase=clase, fecha_clase=fecha, en_lista_de_espera=True).select_related('usuario')
        for r in cola:
            tiene_mensualidad = Mensualidad.objects.filter(
                usuario=r.usuario, actividad=clase.actividad, mes=fecha.month, anio=fecha.year, estado='pagada'
            ).exists()

            cola_espera_data.append({
                'username': r.usuario.username,
                'first_name': r.usuario.first_name,
                'last_name': r.usuario.last_name,
                'pase_mensual': tiene_mensualidad,
            })
            
        for p in Profesor.objects.all():
            todos_profes_data.append({
                'id': p.id,
                'nombre': p.nombre,
                'apellido': p.apellido,
            })

    data = {
        'id': clase.id,
        'actividad': clase.actividad.nombre,
        'actividad_id': clase.actividad.id,
        'fecha': fecha_str or clase.fecha.strftime('%d/%m/%Y'),
        'horario': clase.horario.strftime('%H:%M'),
        'profesor': f"{clase.profesor.apellido}, {clase.profesor.nombre}" if clase.profesor else 'Sin asignar',
        'profesor_id': clase.profesor.id if clase.profesor else '',
        'cupos_disponibles': cupos,
        'precio_clase': float(clase.actividad.precio_clase),
        'precio_mensualidad': float(clase.actividad.precio_mensualidad),
        'logueado': request.user.is_authenticated,
        'rol': request.user.rol if request.user.is_authenticated else 'anonimo',
        'ya_inscripto': ya_inscripto,
        'en_espera': en_espera,
        'ya_mensualizado': ya_mensualizado,  
        'choque_horario': choque_horario,  
        'actividad_choque_nombre': actividad_choque_nombre,
        'cola_espera': cola_espera_data,
        'todos_los_profesores': todos_profes_data,
    }
    return JsonResponse(data)