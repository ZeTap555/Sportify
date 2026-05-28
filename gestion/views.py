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
from .models import Clase, Actividad, Profesor, Reserva
from reservas.models import Mensualidad
from usuarios.models import Usuario
from calendar import monthrange
from .models import Notificacion
import mercadopago
from django.http import HttpResponse
from django.db.models import Sum
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import Color, black, grey
from django.utils.timezone import localtime
from reportlab.pdfbase.pdfmetrics import stringWidth
import os

# =========================================================================
# 1. LA GRILLA PRINCIPAL
# =========================================================================
def grilla_actividades(request):
    ahora = timezone.now().date()
    año = int(request.GET.get('anio', ahora.year))
    mes = int(request.GET.get('mes', ahora.month))
    dia_seleccionado_str = request.GET.get('dia_sel', str(ahora.day))
    
    fecha_seleccionada = date(año, mes, int(dia_seleccionado_str))

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

    todas_las_clases = Clase.objects.all()
    
    cal = calendar.Calendar(firstweekday=0) 
    semanas_matriz = cal.monthdayscalendar(año, mes)

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

    clases_detalle_dia = []
    if fecha_seleccionada >= ahora:
        dia_semana_sel = fecha_seleccionada.weekday()
        for clase in todas_las_clases:
            if clase.dia_semana_num == dia_semana_sel and fecha_seleccionada >= clase.fecha:
                clase.cupos_mostrar = clase.cupos_para_fecha(fecha_seleccionada)
                clases_detalle_dia.append(clase)
        
        clases_detalle_dia.sort(key=lambda x: x.horario)

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
        'clase_feedback_id': int(request.GET.get('clase_feedback_id', 0) or 0),
        'pago_status': request.GET.get('pago_status', ''),
        'pago_msg': request.GET.get('pago_msg', ''),
        'exito': True,
    }
    
    if request.user.is_authenticated:
        cantidad_no_leidas = Notificacion.objects.filter(usuario=request.user, leida=False).count()
    else:
        cantidad_no_leidas = 0

    context['cantidad_no_leidas'] = cantidad_no_leidas
    return render(request, 'grilla.html', context)


def enviar_confirmacion(usuario, clase, reserva):
    try:
        send_mail(
            subject=f"Sportify - Inscripción confirmada: {clase.actividad.nombre}",
            message=f"Hola {usuario.first_name},\n\n"
                    f"Te inscribiste a {clase.actividad.nombre} el {clase.fecha} a las {clase.horario}.\n"
                    f"Monto pagado: ${reserva.monto_pagado}\n"
                    f"Medio de pago: {reserva.medio_pago}\n\n"
                    f"¡Gracias por elegir Sportify!",
            from_email='noreply@sportify.com',
            recipient_list=[usuario.email],
            fail_silently=True,
        )
    except Exception:
        pass


# =========================================================================
# 2. PROCESO DE INSCRIPCIÓN A CLASES
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

        if tipo_pago not in ('senia', 'total'):
            return redirect('grilla_actividades')

        if medio_pago not in ('Tarjeta', 'Mercado Pago'):
            return redirect('grilla_actividades')

        choque_horario = Reserva.objects.filter(
            usuario=request.user,
            fecha_clase=fecha_clase,
            clase__horario=clase.horario,
            en_lista_de_espera=False
        ).exists()

        if choque_horario:  
            messages.error(request, f"Ya estás inscripto a otra clase en el horario de las {clase.horario.strftime('%H:%M')}.")
            return redirect('grilla_actividades')
        
        if flujo_tipo == 'clase' and Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_clase).exists():
            messages.error(request, "Ya estás inscripto en esta clase para esta fecha.")
            return redirect('grilla_actividades')

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

        if flujo_tipo == 'mensualidad':
            hoy = datetime.now().date()
            anio_actual = fecha_clase.year
            mes_current = fecha_clase.month
            
            dia_semana_objetivo = fecha_clase.weekday()
            clases_totales_restantes = 0

            _, ultimo_dia_mes = monthrange(anio_actual, mes_current)
            inicio_conteo = hoy if hoy.month == mes_current and hoy.year == anio_actual else date(anio_actual, mes_current, 1)
            
            for d in range(inicio_conteo.day, ultimo_dia_mes + 1):
                fecha_evaluar = date(anio_actual, mes_current, d)
                if fecha_evaluar.weekday() == dia_semana_objetivo:
                    clases_totales_restantes += 1

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

        request.session['inscripcion_pendiente'] = {
            'clase_id': clase.id,
            'fecha_clase': fecha_clase_str,
            'tipo_pago': tipo_pago,
            'monto': str(monto),
            'medio_pago': medio_pago,
            'flujo_tipo': flujo_tipo,
            'grilla_anio': request.POST.get('grilla_anio', str(fecha_clase.year)),
            'grilla_mes': request.POST.get('grilla_mes', str(fecha_clase.month)),
            'grilla_dia': request.POST.get('grilla_dia', str(fecha_clase.day)),
        }

        if medio_pago == 'Tarjeta':
            return redirect('pago_tarjeta')
        else:
            return redirect('pago_mercadopago')

    return redirect('grilla_actividades')


# =========================================================================
# 3. PASARELA DE PAGO: TARJETA LOCAL
# =========================================================================
@login_required
def pago_tarjeta(request):
    datos = request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect('grilla_actividades')

    g_anio = datos.get('grilla_anio')
    g_mes = datos.get('grilla_mes')
    g_dia = datos.get('grilla_dia')
    clase_id = datos.get('clase_id')

    contexto = {
        'monto': datos['monto'],
        'g_anio': g_anio,
        'g_mes': g_mes,
        'g_dia': g_dia,
        'clase_id': clase_id,
        'msg_feedback': None,
        'msg_url_grilla': None
    }

    if request.method == 'POST':
        numero = request.POST.get('numero', '').strip()
        vto = request.POST.get('vto', '').strip()
        cvv = request.POST.get('cvv', '').strip()
        titular = request.POST.get('titular', '').strip()

        if not all([numero, vto, cvv, titular]):
            contexto['msg_feedback'] = "Complete todos los campos de la tarjeta."
            contexto['msg_url_grilla'] = "Ocurrió un error con el pago"
            return render(request, 'pago_tarjeta.html', contexto)

        numero_limpio = numero.replace(' ', '')
        resultado = "ok"
        
        try:
            mes_vto, anio_vto = vto.split('/')
            mes_vto = int(mes_vto.strip())
            anio_vto = int(anio_vto.strip())
            hoy = datetime.now()
            anio_actual = hoy.year % 100
            mes_actual = hoy.month
            if anio_vto < anio_actual or (anio_vto == anio_actual and mes_vto < mes_actual):
                resultado = "tarjeta_vencida"
        except:
            resultado = "tarjeta_vencida"

        if len(numero_limpio) != 16:
            resultado = "tarjeta_corta"
        elif len(cvv) != 3:
            resultado = "cvv_invalido"
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
                resultado = "cvv_invalido"
            elif tarjeta["vto"] != vto:
                resultado = "tarjeta_vencida"
            else:
                resultado = tarjeta["resultado"]
        
        if resultado != "ok":
            if resultado == "saldo_insuficiente":
                msg_pantalla = "Tarjeta sin fondos suficientes."
            elif resultado in ["tarjeta_inexistente", "titular_incorrecto"]:
                msg_pantalla = "Tarjeta no registrada o datos inválidos."
            elif resultado == "tarjeta_vencida":
                msg_pantalla = "La tarjeta se encuentra vencida."
            elif resultado == "cvv_invalido":
                msg_pantalla = "Código CVV incorrecto."
            elif resultado == "tarjeta_corta":
                msg_pantalla = "El número de tarjeta debe tener 16 dígitos."
            else:
                msg_pantalla = "Ocurrió un error con el pago."

            contexto['msg_feedback'] = msg_pantalla
            contexto['msg_url_grilla'] = "Ocurrió un error con el pago"
            return render(request, 'pago_tarjeta.html', contexto)

        try:
            with transaction.atomic():
                clase = get_object_or_404(Clase, id=clase_id)
                fecha_inicial = datetime.strptime(datos['fecha_clase'], '%Y-%m-%d').date()
                hoy_date = datetime.now().date()
                
                if datos['flujo_tipo'] == 'mensualidad':
                    mes_current = fecha_inicial.month
                    anio_actual = fecha_inicial.year
                    dia_semana_objetivo = fecha_inicial.weekday()
                    
                    reserva_principal = None
                    lista_fechas_reservar = []

                    _, ultimo_dia_mes = monthrange(anio_actual, mes_current)
                    inicio_conteo = hoy_date if hoy_date.month == mes_current and hoy_date.year == anio_actual else date(anio_actual, mes_current, 1)
                    
                    for d in range(inicio_conteo.day, ultimo_dia_mes + 1):
                        f = date(anio_actual, mes_current, d)
                        if f.weekday() == dia_semana_objetivo:
                            lista_fechas_reservar.append(f)

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

                    for fecha_evaluar in lista_fechas_reservar:
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
                    
                    Mensualidad.objects.update_or_create(
                        usuario=request.user,
                        actividad=clase.actividad,
                        mes=mes_current,
                        anio=anio_actual,
                        defaults={
                            'fecha_pago': hoy_date,
                            'estado': 'pagada'
                        }
                    )
                    
                    reserva = reserva_principal
                    mensaje_notificacion = f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre}."
                
                else:
                    estado_final = 'seña' if datos['tipo_pago'] == 'senia' else 'total'
                    reserva = Reserva.objects.create(
                        usuario=request.user,
                        clase=clase,
                        fecha_clase=datos['fecha_clase'],
                        monto_pagado=datos['monto'],
                        estado_pago=estado_final,
                        medio_pago='Tarjeta',
                    )
                    mensaje_notificacion = f"Se realizó con éxito tu pago para la clase: {clase.actividad.nombre}"

                Notificacion.objects.create(
                    usuario=request.user,
                    mensaje=mensaje_notificacion
                )

            en_confirmacion = reserva.id if reserva else 0
            url_retorno = f"/pago/confirmacion/{en_confirmacion}/?anio={g_anio}&mes={g_mes}&dia={g_dia}&clase_id={clase_id}"
            
            if 'inscripcion_pendiente' in request.session:
                del request.session['inscripcion_pendiente']
                
            return redirect(url_retorno)

        except Exception as e:
            contexto['msg_feedback'] = "Error al procesar la inscripción en el sistema."
            return render(request, 'pago_tarjeta.html', contexto)

    return render(request, 'pago_tarjeta.html', contexto)


# =========================================================================
# 4. PASARELA DE PAGO: MERCADO PAGO NATIVO
# =========================================================================
@login_required
def pago_mercadopago(request):
    datos = request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect('grilla_actividades')

    sdk = mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)
    
    preference_response = sdk.preference().create({
        "items": [
            {
                "title": "Reserva Sportify",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": float(datos['monto'])
            }
        ],
        "back_urls": {
            "success": "http://127.0.0.1:8000/pago/exito/?status=approved",
            "failure": "http://127.0.0.1:8000/pago/error/",
            "pending": "http://127.0.0.1:8000/pago/pendiente/",
        },
    })
    
    preference = preference_response["response"]
    return redirect(preference["init_point"])


@login_required
def pago_exito(request):
    datos = request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect('grilla_actividades')

    g_anio = datos.get('grilla_anio')
    g_mes = datos.get('grilla_mes')
    g_dia = datos.get('grilla_dia')
    clase_id = datos.get('clase_id')

    try:
        with transaction.atomic():
            clase = get_object_or_404(Clase, id=clase_id)
            estado_final = ('total' if datos['flujo_tipo'] == 'mensualidad' else ('seña' if datos['tipo_pago'] == 'senia' else 'total'))

            reserva = Reserva.objects.create(
                usuario=request.user,
                clase=clase,
                fecha_clase=datos['fecha_clase'],
                monto_pagado=datos['monto'],
                estado_pago=estado_final,
                medio_pago='Mercado Pago',
            )
            
            if datos['flujo_tipo'] == 'mensualidad':
                fecha_obj = datetime.strptime(datos['fecha_clase'], '%Y-%m-%d').date()
                Mensualidad.objects.update_or_create(
                    usuario=request.user, actividad=clase.actividad,
                    mes=fecha_obj.month, anio=fecha_obj.year, defaults={'estado': 'pagada'}
                )

        Notificacion.objects.create(
            usuario=request.user,
            mensaje=f"Se realizó con éxito tu pago por Mercado Pago para la clase: {clase.actividad.nombre}"
        )

        del request.session['inscripcion_pendiente']
        return redirect(f"/pago/confirmacion/{reserva.id}/?anio={g_anio}&mes={g_mes}&dia={g_dia}&clase_id={clase_id}")

    except Exception:
        return redirect(f"/?anio={g_anio}&mes={g_mes}&dia_sel={g_dia}&clase_feedback_id={clase_id}&pago_status=fallback&pago_msg=Ocurrió un error con el pago")


@login_required
def pago_error(request):
    datos = request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect('grilla_actividades')

    g_anio = datos.get('grilla_anio')
    g_mes = datos.get('grilla_mes')
    g_dia = datos.get('grilla_dia')
    clase_id = datos.get('clase_id')

    return redirect(f"/?anio={g_anio}&mes={g_mes}&dia_sel={g_dia}&clase_feedback_id={clase_id}&pago_status=fallback&pago_msg=Ocurrió un error con el pago de Mercado Pago")


@login_required
def pago_pendiente(request):
    messages.warning(request,'El pago quedo pendiente')
    return redirect('grilla_actividades')


@login_required
def pago_confirmacion(request, reserva_id):
    reserva = get_object_or_404(Reserva, id=reserva_id)
    g_anio = request.GET.get('anio', '')
    g_mes = request.GET.get('mes', '')
    g_dia = request.GET.get('dia', '')
    clase_id = request.GET.get('clase_id', '') 

    context = {
        'reserva': reserva,
        'g_anio': g_anio,
        'g_mes': g_mes,
        'g_dia': g_dia,
        'clase_id': clase_id,
    }
    return render(request, 'pago_confirmacion.html', context)


# =========================================================================
# 5. PANEL DE CONTROL E HISTORIALES
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

    mensualidades_actuales = Mensualidad.objects.filter(usuario=request.user, mes=mes_hoy, anio=anio_hoy)
    mensualidades_anteriores = Mensualidad.objects.filter(usuario=request.user, mes=mes_anterior, anio=anio_anterior, estado='pagada')

    resultados_mensualidad = []
    actividades_processed = set()

    for m in mensualidades_actuales:
        actividades_processed.add(m.actividad.id)
        if m.estado == 'pagada':
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre, 'estado': 'pagada',
                'mensaje': f'Su mensualidad de {m.actividad.nombre} está paga. ¡Puede disfrutar de su actividad!'
            })
        elif m.estado == 'pendiente' and dia_hoy <= 10:
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre, 'estado': 'pendiente',
                'mensaje': f'Su mensualidad de {m.actividad.nombre} está pendiente de pago. Por favor abone antes del día 11.'
            })
        elif m.estado == 'vencida' or (m.estado == 'pendiente' and dia_hoy > 10):
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre, 'estado': 'vencida',
                'mensaje': f'Tu mensualidad de {m.actividad.nombre} ha sido suspendida por falta de pago.'
            })

    if dia_hoy <= 10:
        for m_ant in mensualidades_anteriores:
            if m_ant.actividad.id not in actividades_processed:
                actividades_processed.add(m_ant.actividad.id)
                resultados_mensualidad.append({
                    'actividad': m_ant.actividad.nombre, 'estado': 'pagada',
                    'mensaje': f'Su mensualidad de {m_ant.actividad.nombre} se encuentra vigente (Período de gracia de renovación activo hasta el 10/{mes_hoy}).'
                })

    if not resultados_mensualidad:
        resultados_mensualidad.append({
            'actividad': None, 'estado': 'sin_mensualidad',
            'mensaje': 'Usted no posee ninguna mensualidad vigente. Puede solicitar su mensualidad desde el cronograma.'
        })

    context = {'pagos': pagos, 'resultados_mensualidad': resultados_mensualidad}
    return render(request, 'gestion/historial_pagos.html', context)


@login_required
def ver_notificaciones(request):
    notificaciones = Notificacion.objects.filter(usuario=request.user).order_by('-fecha')
    return render(request, 'gestion/notificaciones.html', {'notificaciones': notificaciones})


@login_required
def marcar_leida(request, notificacion_id):
    notificacion = Notificacion.objects.get(id=notificacion_id, usuario=request.user)
    notificacion.leida = True
    notificacion.save()
    return redirect('ver_notificaciones')


@login_required
def borrar_notificacion(request, notificacion_id):
    notificacion = Notificacion.objects.get(id=notificacion_id, usuario=request.user)
    notificacion.delete()
    return redirect('ver_notificaciones')


@login_required
def borrar_todas_notificaciones(request):
    Notificacion.objects.filter(usuario=request.user).delete()
    return redirect('ver_notificaciones')


# =========================================================================
# 6. REPORTES: COMPROBANTES EN PDF
# =========================================================================
@login_required
def comprobante_pdf(request, reserva_id):
    reserva = get_object_or_404(Reserva, id=reserva_id, usuario=request.user)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="comprobante_Sportify.pdf"'
    
    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_Sportify.png')
    
    if os.path.exists(logo_path):
        pdf.drawImage(ImageReader(logo_path), 220, height - 140, width=150, height=100, mask='auto')
    
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawCentredString(width/2, height - 180, "COMPROBANTE DE PAGO")
    pdf.drawCentredString(width/2, height - 240, f" N° OPERACIÓN: {reserva.id}")
    pdf.rect(40, 220, 515, 420)

    if os.path.exists(logo_path):
        pdf.saveState()
        pdf.configure(fillAlpha=0.08)
        pdf.drawImage(ImageReader(logo_path), 120, 330, width=350, height=250, mask='auto')
        pdf.restoreState()

    y = height - 330
    datos = [
        ("DNI DEL USUARIO:", request.user.username),
        ("ACTIVIDAD:", reserva.clase.actividad.nombre),
        ("FECHA DE LA CLASE:", str(reserva.fecha_clase)),
        ("MONTO PAGADO:", f"${reserva.monto_pagado}"),
        ("MEDIO DE PAGO:", reserva.medio_pago),
        ("ESTADO:", reserva.estado_pago),
        ("FECHA Y HORA DE EMISIÓN:", reserva.fecha_reserva.strftime("%d/%m/%Y %H:%M"))
    ]
    for titulo, valor in datos:
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(60, y, titulo)
        pdf.setFont("Helvetica", 16)
        pdf.drawString(340, y, str(valor))
        y -= 42
        
    pdf.rect(40, 80, 515, 120)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(width/2, 175, "DETALLE DEL PAGO")
    pdf.line(40, 150, 555, 150)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, 125, "DESCRIPCIÓN")
    pdf.drawString(430, 125, "IMPORTE")
    pdf.setFont("Helvetica", 14)
    pdf.drawString(50, 95, f"Clase: {reserva.clase.actividad.nombre}")
    pdf.drawString(430, 95, f"${reserva.monto_pagado}")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(width/2, 40, "GRACIAS POR SER PARTE DE SPORTIFY!")
    pdf.save()
    return response


# =========================================================================
# 7. APIS COMPARTIDAS PARA JAVASCRIPT
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
            reserva_user = Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha).first()
            if reserva_user:
                ya_inscripto = True
                en_espera = reserva_user.en_lista_de_espera

            mensualidad_mes_actual = Mensualidad.objects.filter(
                usuario=request.user, actividad=clase.actividad, mes=fecha.month, anio=fecha.year, estado='pagada'
            ).exists()

            mensualidad_mes_anterior = False
            if fecha.day <= 10:
                if fecha.month == 1:
                    mes_ant, anio_ant = 12, fecha.year - 1
                else:
                    mes_ant, anio_ant = fecha.month - 1, fecha.year
                mensualidad_mes_anterior = Mensualidad.objects.filter(
                    usuario=request.user, actividad=clase.actividad, mes=mes_ant, anio=anio_ant, estado='pagada'
                ).exists()

            ya_mensualizado = mensualidad_mes_actual or mensualidad_mes_anterior

            reserva_choque = Reserva.objects.filter(
                usuario=request.user, fecha_clase=fecha, clase__horario=clase.horario, en_lista_de_espera=False
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
                'username': r.usuario.username, 'first_name': r.usuario.first_name, 'last_name': r.usuario.last_name, 'pase_mensual': tiene_mensualidad,
            })
            
        for p in Profesor.objects.all():
            todos_profes_data.append({'id': p.id, 'nombre': p.nombre, 'apellido': p.apellido})

    data = {
        'id': clase.id, 'actividad': clase.actividad.nombre, 'actividad_id': clase.actividad.id,
        'fecha': fecha_str or clase.fecha.strftime('%d/%m/%Y'), 'horario': clase.horario.strftime('%H:%M'),
        'profesor': f"{clase.profesor.apellido}, {clase.profesor.nombre}" if clase.profesor else 'Sin asignar',
        'profesor_id': clase.profesor.id if clase.profesor else '', 'cupos_disponibles': cupos,
        'precio_clase': float(clase.actividad.precio_clase), 'precio_mensualidad': float(clase.actividad.precio_mensualidad),
        'logueado': request.user.is_authenticated, 'rol': request.user.rol if request.user.is_authenticated else 'anonimo',
        'ya_inscripto': ya_inscripto, 'en_espera': en_espera, 'ya_mensualizado': ya_mensualizado,  
        'choque_horario': choque_horario, 'actividad_choque_nombre': actividad_choque_nombre,  
        'cola_espera': cola_espera_data, 'todos_los_profesores': todos_profes_data,
    }
    return JsonResponse(data)


# =========================================================================
# 8. PANEL DE ADMINISTRACIÓN UNIFICADO
# =========================================================================
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

        elif action == 'actualizar_precios_globales':
            pestania_activa = 'pagos'  # Guardamos y nos quedamos parados en la solapa de pagos
            actividades = Actividad.objects.all()
            
            try:
                with transaction.atomic():
                    for act in actividades:
                        # Buscamos los inputs dinámicos por el ID de la actividad
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
            except Exception as e:
                messages.error(request, f"Error al guardar tarifas: {e}")   



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

   # 🚀 CALCULO REAL DE GANANCIAS EN TIEMPO REAL
    resultado_ganancias = Reserva.objects.aggregate(total=Sum('monto_pagado'))
    print("👉 CONTENIDO DE RESULTADO_GANANCIAS:", resultado_ganancias) # 🔍 Diagnóstico 1
    
    total_ganancias = resultado_ganancias['total'] if resultado_ganancias['total'] is not None else 0.0
    print("👉 VALOR FINAL EN TOTAL_GANANCIAS:", total_ganancias)       # 🔍 Diagnóstico 2
   
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
        'total_ganancias': total_ganancias,  # 🌟 REVISÁ ESTA LÍNEA EXACTA
    }
    return render(request, 'panel_admin.html', context)


# =========================================================================
# 9. GUARDAR TARIFAS GENERALES POR ACTIVIDAD
# =========================================================================
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
                    
                    act.save()
            messages.success(request, "Tarifas actualizadas correctamente")
        except Exception as e:
            messages.error(request, f"Error al procesar el guardado de montos: {e}")

        return redirect('panel_admin')
        
    return redirect('grilla_actividades')
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
    
    # Si es un usuario común, va al HTML de usuario
    context = {'clase': clase, 'fecha_clase': fecha_str}
    return render(request, 'gestion/detalle_clase_usuario.html', context)