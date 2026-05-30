import calendar
from datetime import datetime, date
from multiprocessing import context
from dateutil.relativedelta import relativedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from decimal import Decimal
from django.db import transaction
from django.core.mail import send_mail
from django.conf import settings
from requests import request
from urllib3 import request
from .models import Clase, Actividad, Profesor, Reserva
from reservas.models import Mensualidad
from usuarios.models import Usuario
from django.contrib.auth.decorators import login_required
from calendar import monthrange
from .models import Notificacion
import mercadopago
from django.http import HttpResponse
from gestion.models import Notificacion
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import Color,black,grey
from django.utils.timezone import localtime
from reportlab.pdfbase.pdfmetrics import stringWidth
from django.utils import timezone
import os
# 1. LA GRILLA REAL (Trae los datos que guardás en la BD)
def grilla_actividades(request):
    ahora = timezone.now().date()
    
    # 1. Capturar mes y año seleccionados (por defecto el mes actual)
    año = int(request.GET.get('anio', ahora.year))
    mes = int(request.GET.get('mes', ahora.month))
    dia_seleccionado_str = request.GET.get('dia_sel', str(ahora.day))
    
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

    # 3. 🔄 NUEVA LOGICA DE REPETICIÓN INFINITA PARA LOS CASILLEROS
    # Traemos todas las clases del sistema para evaluar en qué casilleros se repiten
    todas_las_clases = Clase.objects.all()
    
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
                    # Se repite si coincide el día de la semana Y el casillero es posterior o igual al inicio de la clase
                    if clase.dia_semana_num == dia_semana_casillero and fecha_casillero >= clase.fecha:
                        # 🌟 CORRECCIÓN 1: Calculamos el cupo dinámico y compartido por casillero del mes
                        clase.cupos_mostrar = clase.cupos_para_fecha(fecha_casillero)
                        clases_por_dia[dia].append(clase)

    # 5. 📋 NUEVA LOGICA PARA EL DETALLE DEL DÍA SELECCIONADO (Abajo a la derecha)
    # Filtramos las recurrentes que caen el día clickeado, respetando tu regla de ocultar si ya pasó
    clases_detalle_dia = []
    if fecha_seleccionada >= ahora:
        dia_semana_sel = fecha_seleccionada.weekday()
        for clase in todas_las_clases:
            if clase.dia_semana_num == dia_semana_sel and fecha_seleccionada >= clase.fecha:
                clase.cupos_mostrar = clase.cupos_para_fecha(fecha_seleccionada)
                clases_detalle_dia.append(clase)
        
        # Las ordenamos por horario para que no queden mezcladas
        clases_detalle_dia.sort(key=lambda x: x.horario)

    # Tu bloque context y render se quedan exactamente IGUAL que antes:
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
    }
    if request.user.is_authenticated:
        cantidad_no_leidas = Notificacion.objects.filter(usuario=request.user, leida=False).count()
    else:
        cantidad_no_leidas = 0

    context['cantidad_no_leidas'] = cantidad_no_leidas
    return render(request, 'grilla.html', context)

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

"""""
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

        if tipo_pago not in ('senia', 'total'):
            return redirect('grilla_actividades')

        if medio_pago not in ('Tarjeta', 'Mercado Pago'):
            return redirect('grilla_actividades')

        # Ya inscripto en esta fecha
        if Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_clase).exists():
            return redirect('grilla_actividades')

        # Sin cupo -> lista de espera para ESTA clase puntual
        if clase.cupos_para_fecha(fecha_clase) <= 0:
            reserva = Reserva.objects.create(
                usuario=request.user,
                clase=clase,
                fecha_clase=fecha_clase,
                en_lista_de_espera=True,
                monto_pagado=0,
                estado_pago='pendiente',
            )
            return redirect('grilla_actividades')

        # 🧮 CÁLCULO DE MONTO INTELIGENTE
        if flujo_tipo == 'mensualidad':
            hoy = datetime.now().date()
            anio = fecha_clase.year
            mes = fecha_clase.month
            
            # Buscamos el rango de días del mes (ej: de 1 a 31)
            _, ultimo_dia = monthrange(anio, mes)
            
            # Determinamos el día de la semana de esta clase (0=Lunes, 1=Martes... 6=Domingo)
            dia_semana_objetivo = fecha_clase.weekday()
            
            clases_validas_restantes = 0
            
            # Recorremos desde hoy (o desde el 1 del mes si es un mes futuro) hasta el fin de mes
            inicio_conteo = hoy if hoy.month == mes and hoy.year == anio else date(anio, mes, 1)
            
            for d in range(inicio_conteo.day, ultimo_dia + 1):
                fecha_evaluar = date(anio, mes, d)
                
                # Si coincide el día de la semana (ej: todos los martes que quedan)
                if fecha_evaluar.weekday() == dia_semana_objetivo:
                    # REGLA: Verificar si esa fecha futura de la clase tiene cupo disponible
                    if clase.cupos_para_fecha(fecha_evaluar) > 0:
                        clases_validas_restantes += 1
            
            # Si por alguna razón da 0 (ej: te anotás al último día sin cupos en los otros), cobramos mínimo 1
            if clases_validas_restantes == 0:
                clases_validas_restantes = 1
                
            # El monto es el proporcional de las clases que realmente va a aprovechar
            monto = clase.actividad.precio_clase * clases_validas_restantes
            
        else:
            # Flujo normal por clase suelta
            precio = clase.actividad.precio_clase
            if tipo_pago == 'senia':
                monto = (precio * Decimal('0.50')).quantize(Decimal('0.01'))
            else:
                monto = precio

        # Guardar en sesión para Mercado Pago o Tarjeta
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
"""
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

        # 🛑 REGLA DE NEGOCIO NUEVA: Choque de horarios en inscripción individual
        # Evita que se anote a otra actividad que coincida en fecha y hora exacta
        choque_horario = Reserva.objects.filter(
            usuario=request.user,
            fecha_clase=fecha_clase,
            clase__horario=clase.horario,
            en_lista_de_espera=False
        ).exists()

        if choque_horario:  # 👈 DEBE QUEDAR ASÍ, SIN EL FLUJO_TIPO
            messages.error(request, f"Ya estás inscripto a otra clase en el horario de las {clase.horario.strftime('%H:%M')}.")
            return redirect('grilla_actividades')
        
        # 🛑 CONTROL A: Si es clase individual y ya tiene reserva para esta clase y fecha exacta
        if flujo_tipo == 'clase' and Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_clase).exists():
            messages.error(request, "Ya estás inscripto en esta clase para esta fecha.")
            return redirect('grilla_actividades')

        # 🛑 CONTROL B: Si es mensualidad, chequeamos que no tenga ya el abono activo este mes
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

        # 🧮 CÁLCULO DE COSTO DE LA MENSUALIDAD
        if flujo_tipo == 'mensualidad':
            hoy = datetime.now().date()
            anio_actual = fecha_clase.year
            mes_current = fecha_clase.month
            
            dia_semana_objetivo = fecha_clase.weekday()
            clases_totales_restantes = 0

            # --- Días que restan del mes actual ---
            _, ultimo_dia_mes = monthrange(anio_actual, mes_current)
            inicio_conteo = hoy if hoy.month == mes_current and hoy.year == anio_actual else date(anio_actual, mes_current, 1)
            
            for d in range(inicio_conteo.day, ultimo_dia_mes + 1):
                fecha_evaluar = date(anio_actual, mes_current, d)
                if fecha_evaluar.weekday() == dia_semana_objetivo:
                    clases_totales_restantes += 1

            # --- Días del mes siguiente hasta el 10 inclusive ---
            if mes_current == 12:
                mes_siguiente = 1
                anio_siguiente = anio_actual + 1
            else:
                mes_siguiente = mes_current + 1
                anio_siguiente = anio_actual

            for d in range(1, 11):
                fecha_evaluar_sig = date(anio_siguiente, mes_siguiente, d)
                if fecha_evaluar_sig.weekday() == dia_semana_objetivo:
                    clases_totales_restantes += 1
            
            if clases_totales_restantes == 0:
                clases_totales_restantes = 1
                
            monto = clase.actividad.precio_clase * clases_totales_restantes
            
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
            monto = precio * Decimal('0.50') if tipo_pago == 'senia' else precio

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
""""
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

        # Simular validación de tarjeta
        if len(numero.replace(' ', '')) < 16 or len(cvv) < 3:
            del request.session['inscripcion_pendiente']
            return redirect('pago_confirmacion', reserva_id=0)

        # Pago exitoso -> crear reserva
        with transaction.atomic():
            clase = get_object_or_404(Clase, id=datos['clase_id'])
            reserva = Reserva.objects.create(
                usuario=request.user,
                clase=clase,
                fecha_clase=datos['fecha_clase'],
                monto_pagado=datos['monto'],
                estado_pago='seña' if datos['tipo_pago'] == 'senia' else 'total',
                medio_pago='Tarjeta',
            )

        enviar_confirmacion(request.user, clase, reserva)
        del request.session['inscripcion_pendiente']
        return redirect('pago_confirmacion', reserva_id=reserva.id)

    return render(request, 'pago_tarjeta.html', {'monto': datos['monto']})"""
    
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
        #VALIDAR CAMPOS VACIOS

        if not all([numero, vto, cvv, titular]):
            messages.error(request, "Complete todos los campos de la tarjeta.")
            return render(request, 'pago_tarjeta.html', {'monto': datos['monto']})

        numero_limpio=numero.replace(' ','')
        
        try:
            mes_vto,anio_vto=vto.split('/')
            mes_vto=int(mes_vto)
            anio_vto=int(anio_vto)
            hoy=datetime.now()
            anio_actual=hoy.year %100
            mes_actual=hoy.month
            if(
                anio_vto<anio_actual 
                or(
                    anio_vto==anio_actual and mes_vto<mes_actual
                )
            ):
                resultado="tarjeta_vencida"
        except:
            resultado="tarjeta_vencida"


        if len(numero_limpio)!=16:
            resultado="tarjeta_corta"
        elif len(cvv)!=3:
            resultado="cvv_invalido"
        else:
            tarjetas_prueba={
                "1234123412341234":{
                    "titular":"Facundo Carbone",
                    "cvv":"123",
                    "vto":"12/30",
                    "resultado":"ok"
                },
                "3456345634563456":{
                    "titular":"Juan Perez",
                    "cvv":"456",
                    "vto":"11/29",
                    "resultado":"error_banco"
                },
                "2134213421342134":{
                    "titular":"Maria Lopez",
                    "cvv":"789",
                    "vto":"10/28",
                    "resultado":"saldo_insuficiente"
                }
            }
            tarjeta=tarjetas_prueba.get(numero_limpio)
            if not tarjeta:
                resultado="tarjeta_inexistente"
            elif tarjeta["titular"].lower() != titular.lower():
                resultado="titular_incorrecto"
            elif tarjeta["cvv"] != cvv:
                resultado="cvv_invalido"
            elif tarjeta["vto"] != vto:
                resultado="tarjeta_vencida"
            else:
                resultado=tarjeta["resultado"]
        

        
        #MANEJO DE ESCENARIOS
        if resultado=="titular_incorrecto":
            messages.error(request,"El nombre del titular no coincide con el registrado en la tarjeta")
            return render(request,'pago_tarjeta.html',{'monto':datos['monto']})
        if resultado=="cvv_invalido":
            messages.error(request,"El CVV ingresado es incorrecto")
            return render(request,'pago_tarjeta.html',{'monto':datos['monto']})
        if resultado=="tarjeta_vencida":
            messages.error(request,"La tarjeta ingresada se encuentra vencida")
            return render(request,'pago_tarjeta.html',{'monto':datos['monto']})
        if resultado=="saldo_insuficiente":
            messages.error(request,"La tarjeta no posee saldo suficiente para completar la operación")
            return render(request,'pago_tarjeta.html',{'monto':datos['monto']})
        if resultado == "tarjeta_inexistente":
            messages.error(request,"La tarjeta no existe")
            return render(request,'pago_tarjeta.html',{'monto':datos['monto']})
        if resultado == "error_banco":
            messages.error(request,"ERROR-No se pudo establecer conexión con el banco.")
            return render(request,'pago_tarjeta.html',{'monto':datos['monto']})
        if resultado=="tarjeta_corta":
            messages.error(request,"La tarjeta ingresada debe tener 16 digitos.")
            return render(request,'pago_tarjeta.html',{'monto':datos['monto']})
        

        """"
        # Pago exitoso -> crear reserva asociada a la clase
        with transaction.atomic():
            clase = get_object_or_404(Clase, id=datos['clase_id'])
            
            # Determinamos el estado del pago. Si es mensualidad, el pago siempre es 'total'
            estado_final = ('total' if datos['flujo_tipo'] == 'mensualidad' else ('seña' if datos['tipo_pago'] == 'senia' else 'total'))

            reserva = Reserva.objects.create(
                usuario=request.user,
                clase=clase,
                fecha_clase=datos['fecha_clase'],
                monto_pagado=datos['monto'],
                estado_pago=estado_final,
                medio_pago='Tarjeta',
            )
            Notificacion.objects.create(
                usuario=request.user,
                mensaje=f"Se realizó con éxito tu pago para la clase: {clase.actividad.nombre}"
            )
        """
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

                # 2. Recolectar días del mes siguiente hasta el 10 inclusive (Lógica limpia sin sobreescrituras)
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
                    
                    # 🛑 CONTROL ANTIDUPLICADOS: Si ya existe una reserva idéntica, saltamos la iteración
                    if Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_evaluar).exists():
                        continue # Evita el IntegrityError y sigue con la fecha siguiente
                    
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
                fecha_clase = datetime.strptime(datos['fecha_clase'], '%Y-%m-%d').date()
                reserva = Reserva.objects.create(
                    usuario=request.user,
                    clase=clase,
                    fecha_clase=fecha_clase,
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
    
    datos=request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect ('grilla_actividades')
    sdk=mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)
    
    preference_response=sdk.preference().create({
        "items": [
            {
                "title":"Reserva Sportify",
                "quantity":1,
                "currency_id":"ARS",
                "unit_price":float(datos['monto'])
            }
        ],
        "back_urls":{
            "success": "http://127.0.0.1:8000/pago/exito/?status=approved",
            "failure":"http://127.0.0.1:8000/pago/error/",
            "pending": "http://127.0.0.1:8000/pago/pendiente/",
        },
    })
    print(preference_response)
    preference=preference_response["response"]
    return redirect (preference["init_point"])
@login_required
def pago_exito(request):
    print("ENTRO A PAGO EXITO")
    datos=request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect ('grilla_actividades')
    clase=get_object_or_404(Clase,id=datos['clase_id'])
    with transaction.atomic():
        reserva=Reserva.objects.create(usuario=request.user,clase=clase,fecha_clase=datos['fecha_clase'],monto_pagado=datos['monto'],estado_pago='seña' if datos['tipo_pago']=='senia' else 'total',medio_pago='Mercado Pago')
    enviar_confirmacion(request.user,clase,reserva)
    del request.session['inscripcion_pendiente']
    return redirect('pago_confirmacion',reserva_id=reserva.id)

@login_required
def pago_error(request):
    messages.error(request,'El pago fue cancelado')
    return redirect('grilla_actividades'
    )

@login_required
def pago_pendiente(request):
    messages.warning(request,'El pago quedo pendiente')
    return redirect('grilla_actividades')
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

def detalle_clase_fecha(request, clase_id):
    clase = get_object_or_404(Clase, id=clase_id)
    fecha_str = request.GET.get('fecha') # Capturamos la fecha del casillero de la grilla

    # Si es Admin, ve el panel de control de la clase para esa fecha
    if request.user.is_authenticated and request.user.rol == 'admin':
        cola_espera = Reserva.objects.filter(
            clase=clase, 
            fecha_clase=fecha_str, 
            en_lista_de_espera=True
        ).select_related('usuario')

        lista_profesores = Profesor.objects.all()

        context = {
            'clase': clase,
            'fecha_clase': fecha_str,
            'cola_espera': cola_espera,
            'lista_profesores': lista_profesores,
        }
        return render(request, 'gestion/detalle_clase_admin.html', context)

@login_required
def asignar_profesor_clase(request, clase_id):
    if request.user.rol != 'admin':
        return redirect('grilla_actividades')

    if request.method == 'POST':
        clase = get_object_or_404(Clase, id=clase_id)
        profesor_id = request.POST.get('profesor_id')
        fecha_clase = request.POST.get('fecha_clase') # Atajamos la fecha que mandó el modal

        if profesor_id:
            clase.profesor = get_object_or_404(Profesor, id=profesor_id)
        else:
            clase.profesor = None
        clase.save()
        messages.success(request, "Profesor asignado con éxito a la clase.")
        
        # Volvemos a la grilla manteniendo la posición en el calendario
        if fecha_clase:
            partes = fecha_clase.split('-') # ['2026', '05', '20']
            return redirect(f"/?anio={partes[0]}&mes={partes[1]}&dia_sel={int(partes[2])}")
            
    return redirect('grilla_actividades')
"""""
def detalle_clase_api(request, clase_id):
    clase = get_object_or_404(Clase, id=clase_id)
    fecha_str = request.GET.get('fecha')
    ya_inscripto = False
    en_espera = False
    
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
    else:
        cupos = 30

    # 🍏 LÓGICA NUEVA PARA EL ADMIN: Empaquetamos cola de espera y profesores
    es_admin = request.user.is_authenticated and request.user.rol == 'admin'
    cola_espera_data = []
    todos_profes_data = []

    if es_admin and fecha_str:
        # 1. Alumnos en la lista de espera para esta fecha exacta
        cola = Reserva.objects.filter(clase=clase, fecha_clase=fecha, en_lista_de_espera=True).select_related('usuario')
        
        # Obtenemos el mes y año de la clase para validar la mensualidad correspondiente
        mes_clase = fecha.month
        anio_clase = fecha.year

        for r in cola:
            # Buscamos si este usuario específico tiene una mensualidad activa/paga para esta actividad en este mes
            tiene_mensualidad = Mensualidad.objects.filter(
                usuario=r.usuario,
                actividad=clase.actividad,
                mes=mes_clase,
                anio=anio_clase,
                estado='pagada' # Modificá esto si consideran válidas las 'pendientes'
            ).exists()

            cola_espera_data.append({
                'username': r.usuario.username,
                'first_name': r.usuario.first_name,
                'last_name': r.usuario.last_name,
                'pase_mensual': tiene_mensualidad, # <-- Mandamos el Booleano (True/False)
            })
        # 2. Todos los profesores para armar el <select> dinámico
        profesores = Profesor.objects.all()
        for p in profesores:
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
        'rol': request.user.rol if request.user.is_authenticated else 'anonimo', # <-- Agregamos el Rol para el JS
        'ya_inscripto': ya_inscripto,
        'en_espera': en_espera,
        
        # Guardamos las nuevas listas que el JS necesita mapear
        'cola_espera': cola_espera_data,
        'todos_los_profesores': todos_profes_data,
    }
    return JsonResponse(data)
"""
def detalle_clase_api(request, clase_id):
    clase = get_object_or_404(Clase, id=clase_id)
    fecha_str = request.GET.get('fecha')
    ya_inscripto = False
    en_espera = False
    ya_mensualizado = False
    choque_horario = False
    
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

            # 🚀 REGLA DE MENSUALIDAD CORREGIDA (Con 'actividad' bien escrito)
            # Caso A: Mensualidad paga del mes de la celda de la grilla
            mensualidad_mes_actual = Mensualidad.objects.filter(
                usuario=request.user, 
                actividad=clase.actividad,  # 👈 corregido: 'actividad' en vez de 'activity'
                mes=fecha.month, 
                anio=fecha.year, 
                estado='pagada'
            ).exists()

            # Caso B: Cobertura de mensualidad del mes anterior (hasta el día 10 inclusive)
            mensualidad_mes_anterior = False
            if fecha.day <= 10:
                if fecha.month == 1:
                    mes_ant, anio_ant = 12, fecha.year - 1
                else:
                    mes_ant, anio_ant = fecha.month - 1, fecha.year

                mensualidad_mes_anterior = Mensualidad.objects.filter(
                    usuario=request.user, 
                    actividad=clase.actividad,  # 👈 corregido: 'actividad'
                    mes=mes_ant, 
                    anio=anio_ant, 
                    estado='pagada'
                ).exists()

            # Si es True cualquiera de las dos, el usuario está cubierto por mensualidad en esta fecha
            ya_mensualizado = mensualidad_mes_actual or mensualidad_mes_anterior

            # 🌟 VERIFICACIÓN DE CHOQUE DE HORARIO MEJORADA:
            # Buscamos si hay otra reserva activa a la misma hora y día
            reserva_choque = Reserva.objects.filter(
                usuario=request.user,
                fecha_clase=fecha,
                clase__horario=clase.horario,
                en_lista_de_espera=False
            ).exclude(clase=clase).select_related('clase__actividad').first()

            # Si existe una reserva que choca, guardamos el nombre de la actividad
            actividad_choque_nombre = reserva_choque.clase.actividad.nombre if reserva_choque else None
            choque_horario = reserva_choque is not None
    else:
        # En vez de 30 hardcodeado, usamos la capacidad máxima configurada o fallback seguro si no hay fecha
        cupos = getattr(clase.actividad, 'capacidad_maxima', 30)

    # 🍏 LÓGICA PARA EL PANEL DE ADMIN O PROFESOR
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

    # Diccionario final mapeado que consume el JavaScript
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
        'actividad_choque_nombre': actividad_choque_nombre,  # 🚀 MANDAMOS EL NOMBRE DE LA OTRA CLASE  
        'cola_espera': cola_espera_data,
        'todos_los_profesores': todos_profes_data,
    }
    return JsonResponse(data)

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

        # --- B. PROCESAR PROGRAMAR CLASE (¡CON CANDADO DE PROFESOR!) ---
        elif action == 'crear_clase':
            pestania_activa = 'clases'
            actividad_id = request.POST.get('actividad')
            profesor_id = request.POST.get('profesor')
            fecha_str = request.POST.get('fecha')
            horario_str = request.POST.get('horario')

            # 🛠️ VALIDACIÓN 1: Profesor obligatorio
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

                # 🛠️ VALIDACIÓN 2: Solo horas en punto
                if horario_obj.minute != 0 or horario_obj.second != 0:
                    messages.error(request, "Error: Las clases deben comenzar estrictamente en punto (Ej: 19:00).")
                
                # 🛠️ VALIDACIÓN 3: Rango de 8 a 20 hs
                elif horario_obj.hour < 8 or horario_obj.hour > 20:
                    messages.error(request, "Error: El gimnasio se encuentra cerrado. Las clases se dictan únicamente de 08 a 20 hs.")
                
                # 🛠️ VALIDACIÓN 4: Prohibir fechas pasadas
                elif fecha_obj < ahora:
                    messages.error(request, "Error: No se pueden programar clases en una fecha que ya pasó.")
                
                # 🛠️ VALIDACIÓN 5: Prohibir los domingos
                elif fecha_obj.weekday() == 6:
                    messages.error(request, "Error: El gimnasio permanece cerrado los domingos.")
                
                else:
                    dia_semana_nuevo = fecha_obj.weekday()

                    # 1. Le pedimos a la DB solo los campos físicos que sí entiende (profesor, hora e inicio)
                    clases_profe_horario = Clase.objects.filter(
                        profesor_id=profesor_id,
                        horario=horario_obj,
                        fecha__lte=fecha_obj  # Filtra que la recurrencia haya empezado antes o igual a hoy
                    )

                    # 2. Usamos tu @property en memoria recorriendo la lista con Python nativo
                    profesor_ocupado = False
                    for c in clases_profe_horario:
                        if c.dia_semana_num == dia_semana_nuevo:  # 🌟 ¡Acá usamos tu propiedad impecable!
                            profesor_ocupado = True
                            break

                    if profesor_ocupado:
                        messages.error(request, f"Error: El profesor ya se encuentra asignado a otra clase en ese mismo día y horario.")
                    else:
                        # Chequeamos colisión base de la misma actividad
                        colision = Clase.objects.filter(
                            actividad_id=actividad_id,
                            horario=horario_obj
                        )

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
            dni = request.POST.get('dni')
            nombre = request.POST.get('nombre')
            apellido = request.POST.get('apellido')
            fecha_nac = request.POST.get('fecha_nacimiento')
            telefono = request.POST.get('telefono')
            correo = request.POST.get('correo')
            contrasenia = request.POST.get('contrasenia')

            try:
                if Usuario.objects.filter(username=dni).exists():
                    messages.error(request, "Error: Ya existe un usuario registrado con ese DNI.")
                else:
                    user = Usuario.objects.create(
                        username=dni,
                        dni=dni,
                        email=correo,
                        first_name=nombre,
                        last_name=apellido,
                        telefono=telefono,
                        fecha_nacimiento=fecha_nac,
                        rol='profesor',
                        is_active=True,
                        password=make_password(contrasenia)
                    )
                    Profesor.objects.create(
                        usuario=user,
                        nombre=nombre,
                        apellido=apellido,
                        dni=dni,                    
                        telefono=telefono,           
                        correo=correo,              
                        fecha_nacimiento=fecha_nac,  
                        especialidad=""              
                    )
                    messages.success(request, f"Profesor {apellido}, {nombre} dado de alta con éxito.")
            except Exception as e:
                messages.error(request, f"Error en los datos: {e}")

    # --- GENERACIÓN DEL CONTEXTO (GET) (Limpio y sin bucles duplicados) ---
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
                        # Sincronizamos los cupos compartidos dinámicamente usando el nuevo método del models.py
                        clase.cupos_mostrar = clase.cupos_para_fecha(fecha_casillero)
                        clases_por_dia[dia].append(clase)

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
    }
    return render(request, 'panel_admin.html', context)
"""""
@login_required
def historial_pagos(request):
    from datetime import date

    pagos = Reserva.objects.filter(usuario=request.user).order_by('-fecha_reserva')

    hoy = date.today()
    dia_hoy = hoy.day
    mes_hoy = hoy.month
    anio_hoy = hoy.year

    # Buscamos si el usuario tiene mensualidades este mes
    mensualidades = Mensualidad.objects.filter(
        usuario=request.user,
        mes=mes_hoy,
        anio=anio_hoy
    )

    # --- LOGICA DE LOS 4 ESCENARIOS DE LA USER STORY ---
    resultados_mensualidad = []

    if not mensualidades.exists():
        # ESCENARIO 3: No posee ninguna mensualidad este mes
        resultados_mensualidad.append({
            'actividad': None,
            'estado': 'sin_mensualidad',
            'mensaje': 'Usted no posee ninguna mensualidad. Puede solicitar su mensualidad desde el cronograma.'
        })
    else:
        for m in mensualidades:
            if m.estado == 'pagada':
                # ESCENARIO 1: Mensualidad pagada
                resultados_mensualidad.append({
                    'actividad': m.actividad.nombre,
                    'estado': 'pagada',
                    'mensaje': f'Su mensualidad de {m.actividad.nombre} está paga. ¡Puede disfrutar de su actividad!'
                })
            elif m.estado == 'pendiente' and dia_hoy <= 10:
                # ESCENARIO 2: Pendiente pero dentro del plazo (día 1 al 10)
                resultados_mensualidad.append({
                    'actividad': m.actividad.nombre,
                    'estado': 'pendiente',
                    'mensaje': f'Su mensualidad de {m.actividad.nombre} está pendiente de pago. Por favor abone antes del día 11.'
                })
            elif m.estado == 'vencida' or (m.estado == 'pendiente' and dia_hoy > 10):
                # ESCENARIO 4: Vencida (pasó el día 10 y no pagó)
                resultados_mensualidad.append({
                    'actividad': m.actividad.nombre,
                    'estado': 'vencida',
                    'mensaje': f'Tu mensualidad de {m.actividad.nombre} ha sido suspendida por falta de pago. El vencimiento fue el día 10 del corriente mes.'
                })

    context = {
        'pagos': pagos,
        'resultados_mensualidad': resultados_mensualidad,
    }
    return render(request, 'gestion/historial_pagos.html', context)
"""
@login_required
def historial_pagos(request):
    from datetime import date
    from calendar import monthrange

    pagos = Reserva.objects.filter(usuario=request.user).order_by('-fecha_reserva')

    hoy = date.today()
    dia_hoy = hoy.day
    mes_hoy = hoy.month
    anio_hoy = hoy.year

    # Calculamos de forma segura cuál fue el mes anterior y su año correspondiente
    if mes_hoy == 1:
        mes_anterior = 12
        anio_anterior = anio_hoy - 1
    else:
        mes_anterior = mes_hoy - 1
        anio_anterior = anio_hoy

    # 🔎 BUSQUEDA AMPLIADA: Traemos mensualidades del mes actual O del mes anterior
    mensualidades_actuales = Mensualidad.objects.filter(
        usuario=request.user,
        mes=mes_hoy,
        anio=anio_hoy
    )
    
    mensualidades_anteriores = Mensualidad.objects.filter(
        usuario=request.user,
        mes=mes_anterior,
        anio=anio_anterior,
        estado='pagada' # Solo nos importan las pagadas del mes pasado para el período de gracia
    )

    resultados_mensualidad = []
    actividades_procesadas = set()

    # --- 1. PROCESAMOS LAS MENSUALIDADES DEL MES ACTUAL ---
    for m in mensualidades_actuales:
        actividades_procesadas.add(m.actividad.id)
        
        if m.estado == 'pagada':
            # ESCENARIO 1: Mensualidad del mes corriente pagada con éxito
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'estado': 'pagada',
                'mensaje': f'Su mensualidad de {m.actividad.nombre} está paga. ¡Puede disfrutar de su actividad!'
            })
        elif m.estado == 'pendiente' and dia_hoy <= 10:
            # ESCENARIO 2: Pendiente pero dentro del plazo de gracia (día 1 al 10)
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'estado': 'pendiente',
                'mensaje': f'Su mensualidad de {m.actividad.nombre} está pendiente de pago. Por favor abone antes del día 11.'
            })
        elif m.estado == 'vencida' or (m.estado == 'pendiente' and dia_hoy > 10):
            # ESCENARIO 4: Vencida y suspendida (pasó el día 10 del mes actual y no pagó)
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'estado': 'vencida',
                'mensaje': f'Tu mensualidad de {m.actividad.nombre} ha sido suspendida por falta de pago. El vencimiento fue el día 10 del corriente mes.'
            })

    # --- 2. PROCESAMOS EL PERÍODO DE GRACIA (MENSUALIDADES DEL MES ANTERIOR) ---
    # Si estamos antes o en el día 10, y el usuario pagó el mes pasado pero aún no generó el registro de este mes
    if dia_hoy <= 10:
        for m_ant in mensualidades_anteriores:
            if m_ant.actividad.id not in actividades_procesadas:
                actividades_procesadas.add(m_ant.actividad.id)
                # ESCENARIO 1 EXTENDIDO: Sigue vigente por derecho de gracia hasta el 10
                resultados_mensualidad.append({
                    'actividad': m_ant.actividad.nombre,
                    'estado': 'pagada',
                    'mensaje': f'Su mensualidad de {m_ant.actividad.nombre} se encuentra vigente (Período de gracia de renovación activo hasta el 10/{mes_hoy}).'
                })

    # --- 3. ESCENARIO 3: SI NO TIENE NINGUNA REGISTRADA ---
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

@login_required
def mis_reservas(request):
    from datetime import date
    reservas = Reserva.objects.filter(usuario=request.user, fecha_clase__gte=date.today())\
        .select_related('clase__actividad', 'clase__profesor')\
        .order_by('-fecha_clase', '-clase__horario')
    return render(request, 'gestion/mis_reservas.html', {'reservas': reservas})
    
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
            reserva.fecha_reserva.strftime("%d/%m/%Y %H:%M")
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


