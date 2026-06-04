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

    # =========================================================
    # LA GUILLOTINA: Si pasamos el día 10, volamos a los morosos del mes actual
    # =========================================================
    if ahora.day > 10:
        reservas_morosas = Reserva.objects.filter(
            tipo_reserva='mensualidad',
            estado_pago='pendiente',
            clase__fecha__month=ahora.month,
            clase__fecha__year=ahora.year
        )
        if reservas_morosas.exists():
            reservas_morosas.delete()
    # =========================================================

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
    
    # Validamos que actividad_id tenga un valor real y no sea el string 'None' o un texto vacío
    if actividad_id and actividad_id != 'None' and actividad_id != '':
        todas_las_clases = todas_las_clases.filter(
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
                    if clase.dia_semana_num == dia_semana_casillero and fecha_casillero >= clase.fecha:
                        clase.cupos_mostrar = clase.cupos_para_fecha(fecha_casillero)
                        
                        # 🔥 NUEVO: Detectar si este usuario debe esta clase específica
                        clase.tiene_deuda = Reserva.objects.filter(
                            usuario=request.user, 
                            clase=clase, 
                            fecha_clase=fecha_casillero, 
                            estado_pago='pendiente'
                        ).exists() if request.user.is_authenticated else False
                        
                        clases_por_dia[dia].append(clase)

    # 5. Lógica para el detalle del día seleccionado (Abajo a la derecha)
    clases_detalle_dia = []
    if fecha_seleccionada >= ahora:
        dia_semana_sel = fecha_seleccionada.weekday()
        for clase in todas_las_clases:
            if clase.dia_semana_num == dia_semana_sel and fecha_seleccionada >= clase.fecha:
                clase.cupos_mostrar = clase.cupos_para_fecha(fecha_seleccionada)
                # 🔥 NUEVO: Detectar deuda para el detalle
                clase.tiene_deuda = Reserva.objects.filter(
                    usuario=request.user, 
                    clase=clase, 
                    fecha_clase=fecha_seleccionada, 
                    estado_pago='pendiente'
                ).exists() if request.user.is_authenticated else False
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
        ).select_related('usuario').order_by('-tipo_reserva', 'id')

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
        flujo_tipo = request.POST.get('flujo_tipo', 'clase')

        # --- LÓGICA DE PRECIO Y RESERVA ---
        if flujo_tipo == 'mensualidad':
            tiene_pendiente = Reserva.objects.filter(
                usuario=request.user, 
                clase__actividad=clase.actividad, 
                estado_pago='pendiente',
                tipo_reserva='mensualidad'
            ).exists()

            if tiene_pendiente:
                monto = Decimal(str(clase.actividad.precio_mensualidad))
                tipo_reserva = 'mensualidad'
            else:
                anio_solicitado, mes_solicitado = fecha_clase.year, fecha_clase.month
                dia_semana_objetivo = fecha_clase.weekday()
                _, ultimo_dia_mes = monthrange(anio_solicitado, mes_solicitado)
                
                clases_totales_restantes = 0
                for d in range(fecha_clase.day, ultimo_dia_mes + 1):
                    f_eval = date(anio_solicitado, mes_solicitado, d)
                    if f_eval.weekday() == dia_semana_objetivo:
                        if Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=f_eval).exists():
                            continue
                        clases_totales_restantes += 1
                
                if clases_totales_restantes == 0: clases_totales_restantes = 1
                
                precio_unitario_mensual = clase.actividad.precio_mensualidad / Decimal('4.0')
                monto = precio_unitario_mensual * Decimal(clases_totales_restantes)
                monto = round(monto, 2)
                tipo_reserva = 'mensualidad'
        else:
            precio = clase.actividad.precio_clase
            monto = precio / 2 if tipo_pago == 'senia' else precio
            tipo_reserva = 'clase'

        if tipo_pago not in ('senia', 'total') or medio_pago not in ('Tarjeta', 'Mercado Pago'):
            return redirect('grilla_actividades')

        # Reglas de Choque
        choque_horario = Reserva.objects.filter(
            usuario=request.user,
            fecha_clase=fecha_clase,
            clase__horario=clase.horario,
            en_lista_de_espera=False
        ).exclude(estado_pago='pendiente', clase=clase).exists()

        if choque_horario:  
            messages.error(request, f"Ya estás inscripto a otra clase en el horario de las {clase.horario.strftime('%H:%M')}.")
            return redirect('grilla_actividades')
        
        if flujo_tipo == 'clase' and Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_clase).exists():
            messages.error(request, "Ya estás inscripto en esta clase para esta fecha.")
            return redirect('grilla_actividades')

        # Guardamos en sesión
        request.session['inscripcion_pendiente'] = {
            'clase_id': clase.id,
            'fecha_clase': fecha_clase_str,
            'tipo_pago': tipo_pago,
            'monto': str(monto),
            'medio_pago': medio_pago,
            'flujo_tipo': flujo_tipo,
        }

        return redirect('pago_tarjeta') if medio_pago == 'Tarjeta' else redirect('pago_mercadopago')

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
            total_sin_cupo = 0
            
            if datos['flujo_tipo'] == 'mensualidad':
                mes_current = fecha_inicial.month
                anio_actual = fecha_inicial.year
                dia_semana_objetivo = fecha_inicial.weekday()
                
                reserva_principal = None
                fechas_sin_cupo = []

                # =========================================================
                # 🔥 PASO 1: ASEGURAR EL MES ACTUAL (RENOVACIÓN O NUEVO)
                # =========================================================
                _, ultimo_dia_mes = monthrange(anio_actual, mes_current)
                lista_fechas_actual = []

                for d in range(fecha_inicial.day, ultimo_dia_mes + 1):
                    f = date(anio_actual, mes_current, d)
                    if f.weekday() == dia_semana_objetivo:
                        lista_fechas_actual.append(f)

                # Dividimos el pago proporcionalmente entre las clases del mes
                monto_por_clase = Decimal(datos['monto']) / max(len(lista_fechas_actual), 1)

                for fecha_evaluar in lista_fechas_actual:
                    # Buscamos si el sistema ya le había guardado el cupo
                    reserva_existente = Reserva.objects.filter(
                        usuario=request.user,
                        clase=clase,
                        fecha_clase=fecha_evaluar,
                    ).first()

                    if reserva_existente:
                        # Si ya tenía reserva, la actualizamos a mensualidad pagada
                        reserva_existente.estado_pago = 'total'
                        reserva_existente.monto_pagado = monto_por_clase
                        reserva_existente.tipo_reserva = 'mensualidad'
                        reserva_existente.save()
                        if not reserva_principal:
                            reserva_principal = reserva_existente
                    else:
                        # Si es la primera vez que compra, creamos la reserva PAGADA
                        sin_cupo = clase.cupos_para_fecha(fecha_evaluar) <= 0
                        if sin_cupo:
                            fechas_sin_cupo.append(fecha_evaluar)
                        nueva_reserva = Reserva.objects.create(
                            usuario=request.user,
                            clase=clase,
                            fecha_clase=fecha_evaluar,
                            monto_pagado=monto_por_clase,
                            estado_pago='total',
                            medio_pago='Tarjeta',
                            en_lista_de_espera=sin_cupo,
                            tipo_reserva='mensualidad'
                        )
                        if not reserva_principal:
                            reserva_principal = nueva_reserva

                # =========================================================
                # 🔥 PASO 2: PATEAR LA PELOTA AL MES SIGUIENTE (PENDIENTES)
                # =========================================================
                if mes_current == 12:
                    mes_siguiente = 1
                    anio_siguiente = anio_actual + 1
                else:
                    mes_siguiente = mes_current + 1
                    anio_siguiente = anio_actual

                # AHORA LE GUARDAMOS TODO EL MES ENTERO (NO SOLO HASTA EL 10)
                _, ultimo_dia_mes_sig = monthrange(anio_siguiente, mes_siguiente)

                for d in range(1, ultimo_dia_mes_sig + 1):
                    f_sig = date(anio_siguiente, mes_siguiente, d)
                    if f_sig.weekday() == dia_semana_objetivo:
                        # Nos aseguramos de no duplicarle la reserva pendiente si ya la tiene
                        if not Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=f_sig).exists():
                            sin_cupo_sig = clase.cupos_para_fecha(f_sig) <= 0
                            if sin_cupo_sig:
                                fechas_sin_cupo.append(f_sig)
                            Reserva.objects.create(
                                usuario=request.user,
                                clase=clase,
                                fecha_clase=f_sig,
                                monto_pagado=0, # Está pendiente, no pagó nada por esta todavía
                                estado_pago='pendiente',
                                medio_pago='Tarjeta',
                                en_lista_de_espera=sin_cupo_sig,
                                tipo_reserva='mensualidad'
                            )

                # 4. Registrar la tabla Mensualidad en estado pagada
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
                total_sin_cupo = len(fechas_sin_cupo)
                if total_sin_cupo > 0:
                    request.session['mensualidad_sin_cupo'] = {
                        'hay': True,
                        'cantidad': total_sin_cupo,
                    }
                    mensaje_notificacion = (
                        f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre}. "
                        f"{total_sin_cupo} clase(s) no tenían cupo disponible. "
                        f"Te notificaremos si logras entrar, caso contrario se te dará un voucher."
                    )
                else:
                    mensaje_notificacion = f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre}. Tus cupos ya están asegurados para este mes y el próximo."
            
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

        enviar_confirmacion(request.user, clase, reserva, tiene_sin_cupo=total_sin_cupo > 0, cantidad_sin_cupo=total_sin_cupo)
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
    host_url = f"https://{request.get_host()}"
    
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
            "success": f"{host_url}/pago/exito/",
            "failure": f"{host_url}/pago/error/",
            "pending": f"{host_url}/pago/pendiente/",
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
    Destino cuando el pago es aprobado por Mercado Pago. 
    Replica la lógica proporcional base 4 y automatización del mes siguiente.
    """
    print("🟢 ENTRÓ A PAGO ÉXITO - PROCESANDO RESERVA")
    datos = request.session.get('inscripcion_pendiente')
    
   
        
    from .models import Clase, Reserva, Notificacion 
    from reservas.models import Mensualidad
    
    clase = get_object_or_404(Clase, id=datos['clase_id'])
    usuario_id = datos.get('usuario_id')
    usuario_reserva = get_object_or_404(Usuario, id=usuario_id) if usuario_id else request.user
    
    fecha_inicial = datetime.strptime(datos['fecha_clase'], '%Y-%m-%d').date()
    hoy = datetime.now().date()
    
    creado = False
    reserva = None
    total_sin_cupo = 0

    with transaction.atomic():
        if datos.get('flujo_tipo') == 'mensualidad':
            mes_current = fecha_inicial.month
            anio_actual = fecha_inicial.year
            dia_semana_objetivo = fecha_inicial.weekday()
            
            # Control de doble impacto de Mercado Pago: verificamos si la mensualidad ya se pagó
            if Mensualidad.objects.filter(
                usuario=usuario_reserva, 
                actividad=clase.actividad, 
                mes=mes_current, 
                anio=anio_actual, 
                estado='pagada'
            ).exists():
                reserva = Reserva.objects.filter(usuario=usuario_reserva, clase=clase, fecha_clase=fecha_inicial).first()
                creado = False
            else:
                reserva_principal = None
                fechas_sin_cupo = []
                _, ultimo_dia_mes = monthrange(anio_actual, mes_current)
                lista_fechas_actual = []

                # 1. Recolectamos las clases físicas del mes actual desde el día seleccionado
                for d in range(fecha_inicial.day, ultimo_dia_mes + 1):
                    f = date(anio_actual, mes_current, d)
                    if f.weekday() == dia_semana_objetivo:
                        lista_fechas_actual.append(f)

                monto_por_clase = Decimal(datos['monto']) / max(len(lista_fechas_actual), 1)

                # 2. Registramos o actualizamos las reservas físicas del mes corriente
                for fecha_evaluar in lista_fechas_actual:
                    reserva_existente = Reserva.objects.filter(
                        usuario=usuario_reserva,
                        clase=clase,
                        fecha_clase=fecha_evaluar,
                    ).first()

                    if reserva_existente:
                        reserva_existente.estado_pago = 'total'
                        reserva_existente.monto_pagado = monto_por_clase
                        reserva_existente.medio_pago = 'Mercado Pago'
                        reserva_existente.tipo_reserva = 'mensualidad'
                        reserva_existente.save()
                        if not reserva_principal:
                            reserva_principal = reserva_existente
                    else:
                        sin_cupo = clase.cupos_para_fecha(fecha_evaluar) <= 0
                        if sin_cupo:
                            fechas_sin_cupo.append(fecha_evaluar)
                        nueva_reserva = Reserva.objects.create(
                            usuario=usuario_reserva,
                            clase=clase,
                            fecha_clase=fecha_evaluar,
                            monto_pagado=monto_por_clase,
                            estado_pago='total',
                            medio_pago='Mercado Pago',
                            en_lista_de_espera=sin_cupo,
                            tipo_reserva='mensualidad'
                        )
                        if not reserva_principal:
                            reserva_principal = nueva_reserva

                # 3. Reservas fijas automáticas en estado PENDIENTE para TODO el mes siguiente
                if mes_current == 12:
                    mes_siguiente = 1
                    anio_siguiente = anio_actual + 1
                else:
                    mes_siguiente = mes_current + 1
                    anio_siguiente = anio_actual

                _, ultimo_dia_mes_sig = monthrange(anio_siguiente, mes_siguiente)

                for d in range(1, ultimo_dia_mes_sig + 1):
                    f_sig = date(anio_siguiente, mes_siguiente, d)
                    if f_sig.weekday() == dia_semana_objetivo:
                        if not Reserva.objects.filter(usuario=usuario_reserva, clase=clase, fecha_clase=f_sig).exists():
                            sin_cupo_sig = clase.cupos_para_fecha(f_sig) <= 0
                            if sin_cupo_sig:
                                fechas_sin_cupo.append(f_sig)
                            Reserva.objects.create(
                                usuario=usuario_reserva,
                                clase=clase,
                                fecha_clase=f_sig,
                                monto_pagado=0,
                                estado_pago='pendiente',
                                medio_pago='Mercado Pago',
                                en_lista_de_espera=sin_cupo_sig,
                                tipo_reserva='mensualidad'
                            )

                # 4. Confirmamos la mensualidad global en el sistema
                Mensualidad.objects.update_or_create(
                    usuario=usuario_reserva,
                    actividad=clase.actividad,
                    mes=mes_current,
                    anio=anio_actual,
                    defaults={
                        'fecha_pago': hoy,
                        'estado': 'pagada'
                    }
                )
                reserva = reserva_principal
                creado = True
                total_sin_cupo = len(fechas_sin_cupo)
                if total_sin_cupo > 0:
                    request.session['mensualidad_sin_cupo'] = {
                        'hay': True,
                        'cantidad': total_sin_cupo,
                    }
                    mensaje_notificacion = (
                        f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre}. "
                        f"{total_sin_cupo} clase(s) no tenían cupo disponible. "
                        f"Te notificaremos si logras entrar, caso contrario se te dará un voucher."
                    )
                else:
                    mensaje_notificacion = f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre}. Tus cupos ya están asegurados para este mes y el próximo."
        
        else:
            # Flujo para clases sueltas individuales
            estado_final = 'seña' if datos['tipo_pago'] == 'senia' else 'total'
            reserva, creado = Reserva.objects.get_or_create(
                usuario=usuario_reserva,
                clase=clase,
                fecha_clase=datos['fecha_clase'],
                defaults={
                    'monto_pagado': datos['monto'],
                    'estado_pago': estado_final,
                    'medio_pago': 'Mercado Pago',
                    'tipo_reserva': 'clase'
                }
            )
            mensaje_notificacion = f"Se realizó con éxito tu pago para la clase: {clase.actividad.nombre}"

    # Despacho de notificaciones y correo electrónico (solo en la primera ejecución exitosa)
    if creado and reserva:
        print(f"✅ Transacción {reserva.id} procesada con éxito.")
        
        Notificacion.objects.create(
            usuario=usuario_reserva,
            mensaje=mensaje_notificacion
        )
        
        enviar_confirmacion(usuario_reserva, clase, reserva, tiene_sin_cupo=total_sin_cupo > 0, cantidad_sin_cupo=total_sin_cupo)
    else:
        print(f"ℹ️ La transacción ya había sido asentada previamente por resguardo de duplicados.")

    if 'inscripcion_pendiente' in request.session:
        del request.session['inscripcion_pendiente']
        
    response = redirect('pago_confirmacion', reserva_id=reserva.id if reserva else 0)
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
    sin_cupo_info = request.session.pop('mensualidad_sin_cupo', None)
    return render(request, 'pago_confirmacion.html', {
        'exito': True,
        'reserva': reserva,
        'clase': reserva.clase,
        'sin_cupo_info': sin_cupo_info,
    })


def enviar_confirmacion(usuario, clase, reserva, tiene_sin_cupo=False, cantidad_sin_cupo=0):
    try:
        fecha_clase = reserva.fecha_clase
        if isinstance(fecha_clase, str):
            fecha_clase = datetime.strptime(fecha_clase, '%Y-%m-%d').date()
        
        msg_adicional = ""
        if tiene_sin_cupo and cantidad_sin_cupo > 0:
            msg_adicional = (
                f"\n\n⚠️ {cantidad_sin_cupo} de las clases de tu mensualidad no tenían cupo disponible. "
                f"Te notificaremos si logras entrar, caso contrario se te dará un voucher."
            )
        
        send_mail(
            subject=f"Sportify - Inscripción confirmada: {clase.actividad.nombre}",
            message=f"Hola {usuario.first_name},\n\n"
                    f"Te inscribiste a la clase de {clase.actividad.nombre} del {fecha_clase.strftime('%d-%m-%Y')} a las {clase.horario}.\n"
                    f"Monto pagado: ${reserva.monto_pagado}\n"
                    f"Medio de pago: {reserva.medio_pago}\n\n"
                    f"¡Gracias por elegir Sportify!{msg_adicional}",
            from_email='sportifygymapp@gmail.com',
            recipient_list=[usuario.email],
            fail_silently=False,
        )
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
# =========================================================================
# 4. PANEL DE ADMINISTRACIÓN Y PROFESORES
# =========================================================================
    
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
                        
                        # --- AQUÍ ESTÁ EL AJUSTE ---
                        # Buscamos la reserva, pero chequeamos su estado
                        reserva = Reserva.objects.filter(
                            usuario=request.user, 
                            clase=clase, 
                            fecha_clase=fecha_casillero
                        ).first()

                        if reserva:
                            if reserva.estado_pago == 'pendiente':
                                clase.estado_reserva = 'pendiente_pago' # NUEVO ESTADO
                            else:
                                clase.estado_reserva = 'confirmado'
                        else:
                            clase.estado_reserva = 'libre'
                        
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
    
    # Obtenemos todas las mensualidades del mes actual
    hoy = date.today()
    mensualidades = Mensualidad.objects.filter(usuario=request.user, mes=hoy.month, anio=hoy.year)
    
    resultados_mensualidad = []

    if not mensualidades.exists():
        resultados_mensualidad.append({
            'actividad': None, 
            'estado': 'sin_mensualidad', 
            'mensaje': 'Usted no posee ninguna mensualidad vigente.'
        })
    else:
        for m in mensualidades:
            # Determinamos el estado para el template
            estado_visual = m.estado  # 'pagada' o 'pendiente'
            
            # Ajuste de lógica para "vencida"
            if m.estado == 'pendiente' and hoy.day > 10:
                estado_visual = 'vencida'
            
            mensaje = ""
            if estado_visual == 'pagada':
                mensaje = f'Su mensualidad de {m.actividad.nombre} está paga. ¡Puede disfrutar de su actividad!'
            elif estado_visual == 'pendiente':
                mensaje = f'Su mensualidad de {m.actividad.nombre} está pendiente de pago. Por favor abone antes del día 11.'
            else:
                mensaje = f'Tu mensualidad de {m.actividad.nombre} ha sido suspendida por falta de pago.'
                
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'estado': estado_visual,
                'mensaje': mensaje
            })

    return render(request, 'gestion/historial_pagos.html', {
        'pagos': pagos, 
        'resultados_mensualidad': resultados_mensualidad
    })
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
    fecha_obj = None
    clase = get_object_or_404(Clase, id=clase_id)
    fecha_str = request.GET.get('fecha')
    ya_inscripto = False
    en_espera = False
    ya_mensualizado = False
    choque_horario = False
    actividad_choque_nombre = None
    choque_mensual_abono = False
    nombre_actividad_choque_m = None
    
    # Inicializamos las variables del cálculo para que existan siempre
    clases_restantes = 0
    monto_mensual_proporcional = 0
    diferencia_mensualidad = 0
    
    if fecha_str:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        fecha_obj = fecha
        cupos = clase.cupos_para_fecha(fecha)
        if request.user.is_authenticated:
            reserva_user = Reserva.objects.filter(
                usuario=request.user, clase=clase, fecha_clase=fecha
            ).first()
            if reserva_user:
                ya_inscripto = True
                en_espera = reserva_user.en_lista_de_espera

            # Desactivamos restricción para permitir múltiples mensualidades de la misma actividad
            ya_mensualizado = False

            # Verificación choque de horario (Inscripción individual suelta)
            reserva_choque = Reserva.objects.filter(
                usuario=request.user,
                fecha_clase=fecha,
                clase__horario=clase.horario,
                en_lista_de_espera=False
            ).exclude(clase=clase).select_related('clase__actividad').first()

            if reserva_choque:
                actividad_choque_nombre = reserva_choque.clase.actividad.nombre
                choque_horario = True

            # Verificación choque de horario para modalidad Mensualidad
            choque_m = Reserva.objects.filter(
                usuario=request.user,
                tipo_reserva='mensualidad',
                fecha_clase=fecha,
                clase__horario=clase.horario
            ).exclude(clase__actividad=clase.actividad).exclude(estado_pago='pendiente', clase=clase).select_related('clase__actividad').first()

            choque_mensual_abono = True if choque_m else False
            nombre_actividad_choque_m = choque_m.clase.actividad.nombre if choque_m else None

        # =========================================================
        # 🔥 CÁLCULO PROPORCIONAL CORREGIDO DESDE EL DÍA SELECCIONADO (BASE 4)
        # =========================================================
        anio_s = fecha.year
        mes_s = fecha.month
        dia_objetivo = fecha.weekday()
        _, ultimo_dia = monthrange(anio_s, mes_s)
        
        # Contamos las clases que quedan estrictamente desde el día clickeado en la grilla
        for d in range(fecha.day, ultimo_dia + 1):
            f_eval = date(anio_s, mes_s, d)
            if f_eval.weekday() == dia_objetivo:
                # 🔥 NUEVO: Si el usuario ya tiene una reserva para este día, no se la volvemos a cobrar
                if request.user.is_authenticated and Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=f_eval).exists():
                    continue
                clases_restantes += 1
        tiene_pendiente = Reserva.objects.filter(
            usuario=request.user,
            clase__actividad=clase.actividad,
            estado_pago='pendiente',
            tipo_reserva='mensualidad'
        ).exists() if request.user.is_authenticated else False

        if tiene_pendiente:
            # Si tiene deuda, ignoramos el proporcional y forzamos el precio fijo
            monto_mensual_proporcional = float(clase.actividad.precio_mensualidad)
            diferencia_mensualidad = 0
            clases_restantes = 4 # Lo dejamos en 4 para que sea estético
        else:        
            if clases_restantes == 0:
                clases_restantes = 1
                
            precio_fijo = float(clase.actividad.precio_mensualidad)
            
            # Evaluamos el caso especial para la interfaz
            if clases_restantes == 1:
                monto_mensual_proporcional = float(clase.actividad.precio_clase)
                diferencia_mensualidad = precio_fijo - monto_mensual_proporcional
            else:
                precio_unitario = precio_fijo / 4.0
                monto_mensual_proporcional = precio_unitario * clases_restantes
                diferencia_mensualidad = precio_fijo - monto_mensual_proporcional
        # =========================================================
        
    else:
        cupos = getattr(clase.actividad, 'capacidad_maxima', 30)

    es_admin = request.user.is_authenticated and request.user.rol in ['admin', 'profesor']
    cola_espera_data = []
    inscriptos_data = []
    todos_profes_data = []

    if es_admin and fecha_str:
        # 1. Traer INSCRIPTOS CONFIRMADOS
        confirmados = Reserva.objects.filter(
            clase=clase, fecha_clase=fecha, en_lista_de_espera=False
        ).select_related('usuario').order_by('fecha_reserva')
        
        for r in confirmados:
            inscriptos_data.append({
                'username': r.usuario.username,
                'first_name': r.usuario.first_name,
                'last_name': r.usuario.last_name,
                'tipo_reserva': r.tipo_reserva,
            })

        # 2. Traer LISTA DE ESPERA
        cola = Reserva.objects.filter(
            clase=clase, fecha_clase=fecha, en_lista_de_espera=True
        ).select_related('usuario').order_by('-tipo_reserva', 'id')
        
        for r in cola:
            cola_espera_data.append({
                'username': r.usuario.username,
                'first_name': r.usuario.first_name,
                'last_name': r.usuario.last_name,
                'tipo_reserva': r.tipo_reserva,
            })
            
        # 3. Traer PROFESORES para el select
        if request.user.rol == 'admin':
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
        'inscriptos': inscriptos_data,
        'cola_espera': cola_espera_data,
        'todos_los_profesores': todos_profes_data,
        'choque_mensual_abono': choque_mensual_abono,
        'nombre_actividad_choque_m': nombre_actividad_choque_m,
        'reserva_pendiente': Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_obj if fecha_obj else date.today(),estado_pago='pendiente').exists(),
        # 🔥 VARIABLES ENVIADAS AL JSON PARA EL TICKET DE LA GRILLA
        'clases_restantes_mes': clases_restantes,
        'monto_mensual_proporcional': round(monto_mensual_proporcional, 2),
        'diferencia_mensualidad': round(diferencia_mensualidad, 2),
    }
    return JsonResponse(data)