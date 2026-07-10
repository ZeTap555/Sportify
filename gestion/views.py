# =========================================================================
# LIBRERÍAS ESTÁNDAR DE PYTHON
# =========================================================================
import os
import re
import logging
import uuid
import calendar
import threading
from calendar import monthrange
from datetime import datetime, date, timedelta
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
from django.db import models
from django.db.models import Count
import django.db.models as django_models

# =========================================================================
# MODELOS LOCALES
# =========================================================================
from .models import Clase, Actividad, Profesor, Reserva, Notificacion, SuspensionClase, Voucher
from reservas.models import Mensualidad
from usuarios.models import Strike, Usuario

# Trae tu modelo personalizado
Usuario = get_user_model()
logger = logging.getLogger(__name__)


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
    fecha_vista = date(año, mes, 1)
    mes_actual_date = date(ahora.year, ahora.month, 1)

    meses_nombres = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    # 2. Próximos 6 meses desde hoy (para todos los roles)
    proximos_meses = []
    for i in range(6):
        futuro = ahora + relativedelta(months=i)
        proximos_meses.append({
            'anio': futuro.year,
            'mes': futuro.month,
            'nombre': f"{meses_nombres[futuro.month]} {futuro.year}",
            'activo': futuro.year == año and futuro.month == mes
        })

    # 3. Meses anteriores solo para admins
    meses_anteriores = []
    if fecha_vista < mes_actual_date:
        # Admin navegando un mes pasado: ventana centrada con tope en mes actual
        for i in range(-2, 3):
            m = fecha_vista + relativedelta(months=i)
            if date(m.year, m.month, 1) < mes_actual_date:
                meses_anteriores.append({
                    'anio': m.year,
                    'mes': m.month,
                    'nombre': f"{meses_nombres[m.month]} {m.year}",
                    'activo': m.year == año and m.month == mes
                })
    else:
        # Admin en mes actual o futuro: muestra los 5 meses anteriores fijos
        for i in range(5, 0, -1):
            m = mes_actual_date - relativedelta(months=i)
            meses_anteriores.append({
                'anio': m.year,
                'mes': m.month,
                'nombre': f"{meses_nombres[m.month]} {m.year}",
                'activo': False
            })

    # 4. Traemos todas las clases activas
    todas_las_clases = Clase.objects.filter(activa=True)
    if actividad_id and actividad_id != 'None' and actividad_id != '':
        todas_las_clases = todas_las_clases.filter(actividad_id=actividad_id)

    # 5. Construir las semanas del calendario
    cal = calendar.Calendar(firstweekday=0)
    semanas_matriz = cal.monthdayscalendar(año, mes)

    # Mapeamos clases por día con lógica de recurrencia semanal
    clases_por_dia = {}
    for semana in semanas_matriz:
        for dia in semana:
            if dia != 0:
                fecha_casillero = date(año, mes, dia)
                clases_por_dia[dia] = []
                for clase in todas_las_clases:
                    if clase.fecha == fecha_casillero:
                        clase.cupos_mostrar = clase.cupos_para_fecha(fecha_casillero)
                        clases_por_dia[dia].append(clase)

    # 6. Detalle del día seleccionado
    clases_detalle_dia = []
    for clase in todas_las_clases:
        if clase.fecha == fecha_seleccionada:
            clase.cupos_mostrar = clase.cupos_para_fecha(fecha_seleccionada)
            if fecha_seleccionada == ahora:
                fecha_hora_clase = timezone.make_aware(
                    datetime.combine(fecha_seleccionada, clase.horario)
                )
                if fecha_hora_clase < timezone.now():
                    continue
            clases_detalle_dia.append(clase)

    clases_detalle_dia.sort(key=lambda x: x.horario)

    # 7. Detectar si hay clases en el mes para el mensaje de filtro
    hay_clases_mes = False
    for semana in semanas_matriz:
        for dia in semana:
            if dia != 0:
                fecha_casillero = date(año, mes, dia)
                for clase in todas_las_clases:
                    if clase.fecha == fecha_casillero:
                        hay_clases_mes = True
                        break
                if hay_clases_mes:
                    break
        if hay_clases_mes:
            break

    actividades = Actividad.objects.all()
    mensaje_filtro = None
    if actividad_id and not hay_clases_mes:
        mensaje_filtro = "No se encontraron clases disponibles para los filtros seleccionados"
    
    tiene_voucher=False
    if request.user.is_authenticated:
        tiene_voucher=Voucher.objects.filter(
            cliente=request.user
        ).exists()

    context = {
        'semanas_matriz': semanas_matriz,
        'mes_nombre': meses_nombres[mes],
        'mes_actual': mes,
        'anio_actual': año,
        'proximos_meses': proximos_meses,
        'meses_anteriores': meses_anteriores,
        'clases_por_dia': clases_por_dia,
        'fecha_seleccionada': fecha_seleccionada,
        'clases_detalle_dia': clases_detalle_dia,
        'hoy': ahora,
        'actividades': actividades,
        'actividad_seleccionada': actividad_id,
        'mensaje_filtro': mensaje_filtro,
        'tiene_voucher':tiene_voucher,
    }

    if request.user.is_authenticated:
        context['cantidad_no_leidas'] = Notificacion.objects.filter(
            usuario=request.user, leida=False
        ).count()
        context['apto_vigente'] = True if request.user.rol != 'cliente' else request.user.tiene_apto_vigente()
    else:
        context['cantidad_no_leidas'] = 0
        context['apto_vigente'] = False

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


@login_required
def suspender_clase(request, clase_id):
    if request.user.rol != 'admin':
        messages.error(request, 'No tenés permisos para realizar esta acción.')
        return redirect('grilla_actividades')

    clase = get_object_or_404(Clase, id=clase_id)

    if request.method == 'POST':
        fecha_str = request.POST.get('fecha')
        if not fecha_str:
            messages.error(request, 'Debe seleccionar una fecha para la suspensión.')
            return redirect('grilla_actividades')

        fecha_susp = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        ahora = timezone.localtime()
        clase_datetime = timezone.make_aware(
            datetime.combine(fecha_susp, clase.horario)
        )

        if ahora > clase_datetime:
            messages.error(request, 'La clase se encuentra en curso, no es posible suspenderla.')
            return redirect('grilla_actividades')

        if SuspensionClase.objects.filter(clase=clase, fecha=fecha_susp).exists():
            messages.error(request, 'Esta clase ya se encuentra suspendida.')
            return redirect('grilla_actividades')

        motivo = request.POST.get('motivo')
        otro_motivo = request.POST.get('otro_motivo', '')
        comentario = request.POST.get('comentario', '')

        if motivo == 'otro' and not otro_motivo:
            messages.error(request, 'Debe completar el motivo cuando selecciona "Otro".')
            return redirect('grilla_actividades')

        actividad_nombre = clase.actividad.nombre
        horario_str = clase.horario.strftime('%H:%M')

        with transaction.atomic():
            SuspensionClase.objects.create(
                clase=clase,
                fecha=fecha_susp,
                motivo=motivo,
                otro_motivo=otro_motivo,
                comentario=comentario,
            )

            if clase.profesor and clase.profesor.usuario:
                msg_prof = (
                    f"La clase de {actividad_nombre} del "
                    f"{fecha_susp.strftime('%d/%m/%Y')} a las "
                    f"{horario_str} hs fue suspendida."
                )
                if comentario:
                    msg_prof += f" Motivo: {comentario}"
                Notificacion.objects.create(
                    usuario=clase.profesor.usuario,
                    mensaje=msg_prof,
                )
                asunto_prof = f"Clase suspendida - {actividad_nombre}"
                html_prof = _armar_html_email(actividad_nombre, msg_prof, "Clase suspendida")
                transaction.on_commit(
                    lambda d=clase.profesor.usuario.email, a=asunto_prof, h=html_prof: _enviar_email(d, a, h)
                )

            reservas_afectadas = Reserva.objects.filter(
                fecha_clase=fecha_susp,
                clase__horario=clase.horario,
                clase__actividad=clase.actividad,
            ).select_related('usuario')

            reservas_pagas = [r for r in reservas_afectadas if not r.en_lista_de_espera]
            reservas_waitlist = [r for r in reservas_afectadas if r.en_lista_de_espera]

            for r in reservas_waitlist:
                Notificacion.objects.create(
                    usuario=r.usuario,
                    mensaje=(
                        f"La clase {actividad_nombre} del "
                        f"{fecha_susp.strftime('%d/%m/%Y')} a las {horario_str} hs "
                        f"fue suspendida."
                    )
                )

            for reserva in reservas_pagas:
                usuario = reserva.usuario
                fecha_fmt = fecha_susp.strftime('%d/%m/%Y')

                if reserva.modalidad == 'mensual':
                    ultimo_dia = calendar.monthrange(fecha_susp.year, fecha_susp.month)[1]
                    Voucher.objects.create(
                        cliente=usuario,
                        fecha_vencimiento=date(fecha_susp.year, fecha_susp.month, ultimo_dia),
                    )
                    mensaje = (
                        f"La clase {actividad_nombre} del {fecha_fmt} a las {horario_str} hs "
                        f"fue suspendida. Se generó automáticamente un voucher "
                        f"para utilizar en cualquier otra clase disponible."
                    )
                else:
                    mensaje = (
                        f"La clase {actividad_nombre} del {fecha_fmt} a las {horario_str} hs "
                        f"fue suspendida. Comunícate con el personal para solicitar "
                        f"la devolución correspondiente."
                    )

                Notificacion.objects.create(usuario=usuario, mensaje=mensaje)

                asunto = f"Clase suspendida - {actividad_nombre}"
                html = _armar_html_email(actividad_nombre, mensaje, "Clase suspendida")
                transaction.on_commit(
                    lambda d=usuario.email, a=asunto, h=html: _enviar_email(d, a, h)
                )

        dias = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
        dia_nombre = dias[fecha_susp.weekday()]
        messages.success(
            request,
            f'La clase {actividad_nombre} del {fecha_susp.strftime("%d/%m/%Y")} '
            f'a las {horario_str} hs '
            f'fue suspendida correctamente.'
        )
        return redirect('grilla_actividades')

    return redirect('grilla_actividades')


def _armar_html_email(actividad_nombre, mensaje, titulo="Clase eliminada"):
    return f"""
    <div style="background:#000000;padding:40px;font-family:Poppins,sans-serif;">
        <h1 style="color:#00ff88;margin:0 0 10px;">SPORTIFY</h1>
        <h2 style="color:#ffffff;margin:0 0 15px;">{titulo}</h2>
        <p style="color:#ffffff;line-height:1.6;margin:0;">{mensaje}</p>
    </div>
    """


def _enviar_email(destino, asunto, html):
    try:
        msg = EmailMultiAlternatives(asunto, "", settings.EMAIL_HOST_USER, [destino])
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception as e:
        logger.error(f"Error al enviar email a {destino}: {e}")


@login_required
def eliminar_clase(request, clase_id):
    if request.user.rol != 'admin':
        messages.error(request, 'No tenés permisos para realizar esta acción.')
        return redirect('grilla_actividades')

    clase = get_object_or_404(Clase, id=clase_id, activa=True)

    if request.method == 'POST':
        hoy = date.today()
        now = timezone.now()

        clases_a_eliminar = Clase.objects.filter(
            actividad=clase.actividad,
            horario=clase.horario,
            profesor=clase.profesor,
            fecha__gte=hoy,
            activa=True,
        )
        clase_ids = list(clases_a_eliminar.values_list('id', flat=True))

        if not clase_ids:
            messages.error(request, 'No se encontraron clases para eliminar.')
            return redirect('grilla_actividades')

        with transaction.atomic():
            fechas_suspendidas = SuspensionClase.objects.filter(
                clase_id__in=clase_ids
            ).values_list('fecha', flat=True)

            reservas_afectadas = Reserva.objects.filter(
                clase_id__in=clase_ids,
                fecha_clase__gte=hoy,
            ).exclude(
                models.Q(modalidad='mensual', estado_pago='pendiente')
            ).exclude(
                fecha_clase__in=fechas_suspendidas
            ).select_related('usuario')

            afectadas_final = []
            for r in reservas_afectadas:
                if r.fecha_clase == hoy:
                    ocurrencia = timezone.make_aware(
                        datetime.combine(hoy, clase.horario)
                    )
                    if now > ocurrencia:
                        continue
                afectadas_final.append(r)

            reservas_pagas = [r for r in afectadas_final if not r.en_lista_de_espera]
            reservas_waitlist = [r for r in afectadas_final if r.en_lista_de_espera]

            for r in reservas_waitlist:
                Notificacion.objects.create(
                    usuario=r.usuario,
                    mensaje=(
                        f"La clase {clase.actividad.nombre} "
                        f"fue eliminada definitivamente."
                    )
                )

            actividad_nombre = clase.actividad.nombre
            horario_str = clase.horario.strftime('%H:%M')
            dia_nombre = clase.dia_semana_nombre
            mensuales_notificados = set()

            for reserva in reservas_pagas:
                usuario = reserva.usuario
                fecha_fmt = reserva.fecha_clase.strftime('%d/%m/%Y')

                if reserva.modalidad == 'mensual':
                    ultimo_dia = calendar.monthrange(
                        reserva.fecha_clase.year, reserva.fecha_clase.month
                    )[1]
                    Voucher.objects.create(
                        cliente=usuario,
                        fecha_vencimiento=date(
                            reserva.fecha_clase.year,
                            reserva.fecha_clase.month,
                            ultimo_dia
                        ),
                        motivo=f'Clase eliminada - {actividad_nombre}',
                    )

                    if usuario.id not in mensuales_notificados:
                        mensuales_notificados.add(usuario.id)
                        mensaje = (
                            f"La clase {actividad_nombre} de los {dia_nombre} "
                            f"a las {horario_str} hs fue eliminada. "
                            f"Se te asignaron los vouchers correspondientes "
                            f"de las clases que tenías pagas."
                        )
                        Notificacion.objects.create(usuario=usuario, mensaje=mensaje)

                        asunto = f"Clase eliminada - {actividad_nombre}"
                        html = _armar_html_email(actividad_nombre, mensaje)
                        transaction.on_commit(
                            lambda d=usuario.email, a=asunto, h=html: _enviar_email(d, a, h)
                        )
                else:
                    mensaje = (
                        f"La clase {actividad_nombre} del {fecha_fmt} a las "
                        f"{horario_str} hs fue eliminada definitivamente. "
                        f"Comunicate con el personal para solicitar "
                        f"la devolución correspondiente."
                    )
                    Notificacion.objects.create(usuario=usuario, mensaje=mensaje)

                    asunto = f"Clase eliminada - {actividad_nombre}"
                    html = _armar_html_email(actividad_nombre, mensaje)
                    transaction.on_commit(
                        lambda d=usuario.email, a=asunto, h=html: _enviar_email(d, a, h)
                    )

            Mensualidad.objects.filter(
                clase_id__in=clase_ids, estado='pagada'
            ).update(estado='vencida')

            if clase.profesor and clase.profesor.usuario:
                msg_prof = (
                    f"La clase de {clase.actividad.nombre} "
                    f"({clase.dia_semana_nombre} {horario_str} hs) "
                    f"fue eliminada definitivamente del sistema."
                )
                Notificacion.objects.create(
                    usuario=clase.profesor.usuario,
                    mensaje=msg_prof,
                )
                asunto_prof = f"Clase eliminada - {actividad_nombre}"
                html_prof = _armar_html_email(actividad_nombre, msg_prof)
                transaction.on_commit(
                    lambda d=clase.profesor.usuario.email, a=asunto_prof, h=html_prof: _enviar_email(d, a, h)
                )

            clases_a_eliminar.update(activa=False)

        messages.success(
            request,
            f'La clase {actividad_nombre} del {dia_nombre} a las {horario_str}hrs fue eliminada correctamente. '
        )
        return redirect('grilla_actividades')

    return redirect('grilla_actividades')


# =========================================================================
# 2. INSCRIPCIONES Y RESERVAS
# =========================================================================

@login_required
def inscribirse_clase(request, clase_id):
    clase = get_object_or_404(Clase, id=clase_id)
    fecha_clase_str = request.POST.get('fecha_clase')

    # -----------------------------------------------------------------
    # BLOQUEO POR APTO MÉDICO VENCIDO O INEXISTENTE
    # -----------------------------------------------------------------
    # Esta validación se hace siempre en el backend, sin importar si la
    # petición vino del formulario de la grilla o de una llamada directa
    # (URL, API, herramientas externas, etc), ya que el frontend no es
    # una fuente confiable de seguridad.
    if request.user.rol == 'cliente' and not request.user.tiene_apto_vigente():
        messages.error(
            request,
            "Tu apto médico se encuentra vencido. Debes cargar uno nuevo para continuar "
            "utilizando las funciones de reserva e inscripción."
        )
        return redirect('grilla_actividades')

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
        usar_voucher=request.POST.get('usar_voucher')=='true'

        if not usar_voucher:
            if tipo_pago not in('senia','total'):
                return redirect('grilla_actividades')
            if medio_pago not in('Tarjeta','Mercado Pago'):
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

        # Regla de negocio: inscripción individual solo dentro de 7 días
        if flujo_tipo == 'clase':
            hoy = date.today()
            if fecha_clase > hoy + timedelta(days=7):
                messages.error(request, "Solo podés inscribirte a clases dentro de la próxima semana.")
                return redirect('grilla_actividades')
            if fecha_clase < hoy:
                messages.error(request, "No podés inscribirte a una clase que ya pasó.")
                return redirect('grilla_actividades')

        # Control B: Si es mensualidad, chequeamos que no tenga ya el abono activo este mes
        if flujo_tipo == 'mensualidad':
            mes_solicitado = fecha_clase.month
            anio_solicitado = fecha_clase.year
            dia_semana_objetivo = fecha_clase.weekday()
            
            if Mensualidad.objects.filter(
                usuario=request.user, 
                clase=clase, 
                mes=mes_solicitado, 
                anio=anio_solicitado,
                estado='pagada'
            ).exists():
                messages.error(request, "Ya estás inscripto a una mensualidad de esta actividad.")
                return redirect('grilla_actividades')
            
            # Control C: Otra mensualidad en el mismo horario/día de la semana
            otras_mensualidades = Mensualidad.objects.filter(
                usuario=request.user, mes=mes_solicitado, anio=anio_solicitado,
                estado='pagada', clase__horario=clase.horario,
            ).exclude(actividad=clase.actividad).select_related('clase')
            
            if any(m.clase and m.clase.fecha.weekday() == dia_semana_objetivo for m in otras_mensualidades):
                messages.error(
                    request,
                    f"Ya tenés una mensualidad activa en el horario de las "
                    f"{clase.horario.strftime('%H:%M')} hs. No podés contratar otra en el mismo horario."
                )
                return redirect('grilla_actividades')

        # Cálculo de costo de la mensualidad (MODELO MES CALENDARIO)
        if flujo_tipo == 'mensualidad':
            hoy = datetime.now().date()
            
            anio_solicitado = fecha_clase.year
            mes_solicitado = fecha_clase.month
            dia_semana_objetivo = fecha_clase.weekday()

            _, ultimo_dia_mes = monthrange(anio_solicitado, mes_solicitado)
            
            if hoy.month == mes_solicitado and hoy.year == anio_solicitado:
                dia_inicio = hoy.day
            else:
                dia_inicio = 1
            
            fechas_con_cupo = []
            fechas_sin_cupo = []

            for d in range(dia_inicio, ultimo_dia_mes + 1):
                fecha_evaluar = date(anio_solicitado, mes_solicitado, d)
                if fecha_evaluar.weekday() == dia_semana_objetivo:
                    if fecha_evaluar == hoy:
                        clase_datetime = timezone.make_aware(
                            timezone.datetime.combine(fecha_evaluar, clase.horario)
                        )
                        if timezone.now() > clase_datetime:
                            continue
                    if Reserva.objects.filter(
                        usuario=request.user,
                        fecha_clase=fecha_evaluar,
                        clase__horario=clase.horario,
                        clase__actividad=clase.actividad,
                        en_lista_de_espera=False
                    ).exists():
                        continue
                    if clase.cupos_para_fecha(fecha_evaluar) > 0:
                        fechas_con_cupo.append(fecha_evaluar)
                    else:
                        fechas_sin_cupo.append(fecha_evaluar)

            # Escenario 4: todas las clases del mes sin cupo
            if not fechas_con_cupo:
                messages.error(
                    request,
                    f"No hay cupos disponibles para ninguna de las clases de {clase.actividad.nombre} "
                    f"de los {clase.dia_semana_plural.lower()} a las {clase.horario.strftime('%H:%M')} hs de este mes."
                )
                return redirect('grilla_actividades')

            # Escenario 2: algunas sin cupo, el precio se calcula solo sobre las que tienen cupo
            clases_totales_restantes = len(fechas_con_cupo)

            if clases_totales_restantes == 0:
                clases_totales_restantes = 1
                
            # =========================================================
            # CÁLCULO PROPORCIONAL EXACTO DEL MES
            # =========================================================
            clases_ideales = Decimal('5.0') 
            
            precio_unitario_mensual = clase.actividad.precio_mensualidad / clases_ideales
            monto = precio_unitario_mensual * Decimal(clases_totales_restantes)
            
            if monto > clase.actividad.precio_mensualidad:
                monto = clase.actividad.precio_mensualidad
            
            monto = round(monto, 2)
            if request.user.penalizacion_pendiente_individual:
                monto = Decimal(str(monto)) * Decimal('1.25')
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
                messages.success(request, "Te registraste en la lista de espera para esta clase.")
                return redirect('grilla_actividades')
                
            precio = clase.actividad.precio_clase
            if usar_voucher:
                voucher=Voucher.objects.filter(cliente=request.user,utilizado=False).first()
                if not voucher:
                    messages.error(request,"No tienes vouchers disponibles.")
                    return redirect('grilla_actividades')
                voucher.delete()
                reserva=Reserva.objects.create(
                    usuario=request.user,
                    clase=clase,
                    fecha_clase=fecha_clase,
                    monto_pagado=0,
                    estado_pago='total',
                    medio_pago='Voucher',
                    modalidad='individual'
                )
                mensaje_notificacion=(
                    f"Se realizó con éxito tu inscripción con voucher para la clase: "
                    f"{clase.actividad.nombre} del {fecha_clase.strftime('%d/%m/%Y')}."
                )
                Notificacion.objects.create(
                    usuario=request.user,mensaje=mensaje_notificacion
                )
                threading.Thread(
                    target=enviar_confirmacion,args=(request.user,clase,reserva)
                ).start()
                return redirect('pago_confirmacion', reserva_id=reserva.id)
            monto = precio / 2 if tipo_pago == 'senia' else precio
            if request.user.penalizacion_pendiente_individual:
                monto = Decimal(str(monto)) * Decimal('1.25')
                monto = round(monto, 2)
                
        
        # Guardamos en sesión
        session_data = {
            'clase_id': clase.id,
            'fecha_clase': fecha_clase_str,
            'tipo_pago': tipo_pago,
            'monto': str(monto),
            'medio_pago': medio_pago,
            'flujo_tipo': flujo_tipo,
        }
        if flujo_tipo == 'mensualidad':
            session_data['fechas_con_cupo'] = [f.strftime('%Y-%m-%d') for f in fechas_con_cupo]
            session_data['fechas_sin_cupo'] = [f.strftime('%Y-%m-%d') for f in fechas_sin_cupo]
        request.session['inscripcion_pendiente'] = session_data

        if medio_pago == 'Tarjeta':
            return redirect('pago_tarjeta')
        else:
            return redirect('pago_mercadopago')

    return redirect('grilla_actividades')


@login_required
def mis_reservas(request):
    from datetime import date
    from reservas.models import Mensualidad
    
    base_qs = Reserva.objects.filter(usuario=request.user, fecha_clase__gte=date.today())\
        .select_related('clase__actividad', 'clase__profesor')

    # Distinct values for filter dropdowns
    actividades_filtro = Actividad.objects.filter(
        id__in=base_qs.values_list('clase__actividad_id', flat=True).distinct()
    )
    horarios_filtro = (
        base_qs.values_list('clase__horario', flat=True)
        .distinct()
        .order_by('clase__horario')
    )

    # Read filters from GET
    actividad_id = request.GET.get('actividad') or ''
    dia_semana = request.GET.get('dia') or ''
    horario = request.GET.get('horario') or ''
    tipo = request.GET.get('tipo') or ''

    # Build filtered queryset for all tabs
    reservas_qs = base_qs.order_by('fecha_clase', 'clase__horario')
    if actividad_id:
        reservas_qs = reservas_qs.filter(clase__actividad_id=actividad_id)
    if dia_semana:
        reservas_qs = reservas_qs.filter(fecha_clase__week_day=dia_semana)
    if horario:
        reservas_qs = reservas_qs.filter(clase__horario=horario)
    if tipo:
        reservas_qs = reservas_qs.filter(modalidad=tipo)

    suspension_claves = {(r.clase.horario, r.clase.actividad_id, r.fecha_clase) for r in reservas_qs}
    suspensiones = SuspensionClase.objects.filter(
        clase__horario__in=[h for h, _, _ in suspension_claves],
        clase__actividad_id__in=[a for _, a, _ in suspension_claves],
        fecha__in=[f for _, _, f in suspension_claves],
    ).select_related('clase')
    suspension_set = {(s.clase.horario, s.clase.actividad_id, s.fecha) for s in suspensiones}
    for r in reservas_qs:
        r.suspendida = (r.clase.horario, r.clase.actividad_id, r.fecha_clase) in suspension_set
        r.clase_eliminada = not r.clase.activa

    reservas_normales = []
    reservas_pendientes_pago = []
    reservas_espera = []

    mensualidades = Mensualidad.objects.filter(
        usuario=request.user, estado='pagada'
    ).values_list('actividad_id', 'mes', 'anio')
    mensualidades_set = {(m[0], m[1], m[2]) for m in mensualidades}

    for r in reservas_qs:
        if r.en_lista_de_espera:
            reservas_espera.append(r)
        elif r.estado_pago == 'seña':
            r.es_mensual = False
            reservas_pendientes_pago.append(r)
        elif r.modalidad == 'mensual' and r.estado_pago == 'pendiente':
            r.es_mensual_pendiente = True
            r.es_mensual = False
            reservas_pendientes_pago.append(r)
        else:
            r.es_mensual = r.modalidad == 'mensual' and r.estado_pago != 'pendiente'
            reservas_normales.append(r)

    from gestion.models import Notificacion
    cantidad_no_leidas = Notificacion.objects.filter(usuario=request.user, leida=False).count()

    return render(request, 'gestion/mis_reservas.html', {
        'reservas': reservas_normales,
        'reservas_espera': reservas_espera,
        'reservas_pendientes_pago': reservas_pendientes_pago,
        'cantidad_no_leidas': cantidad_no_leidas,
        'actividades_filtro': actividades_filtro,
        'horarios_filtro': horarios_filtro,
        'filtro_actividad': actividad_id,
        'filtro_dia': dia_semana,
        'filtro_horario': horario,
        'filtro_tipo': tipo,
    })

@login_required
def salir_lista_espera(request,reserva_id):
    reserva=get_object_or_404(
        Reserva,
        id=reserva_id,
        usuario=request.user,
        en_lista_de_espera=True
    )
    reserva.delete()
    messages.success(request,"Te has dado de baja de la lista de espera exitosamente. No recibirás avisos sobre esa clase")
    return redirect("mis_reservas")
# =========================================================================
# 3. PASARELAS DE PAGO Y CONFIRMACIONES
# =========================================================================
@login_required
def mis_clases(request):
    profesor=Profesor.objects.get(usuario=request.user)
    clases_raw = Clase.objects.filter(profesor=profesor, activa=True).select_related('actividad')
    vistas = set()
    clases = []
    for c in clases_raw:
        key = (c.actividad_id, c.horario)
        if key not in vistas:
            vistas.add(key)
            clases.append(c)
    hoy=date.today()
    clases_pendientes=[]
    clases_finalizadas=[]
    for clase in clases:
        fecha_inicio=clase.fecha
        fecha_minima=hoy-timedelta(days=90)
        fecha_maxima=hoy+timedelta(days=90)
        fecha_actual=fecha_inicio
        while fecha_actual<=fecha_maxima:
            cantidad_inscriptos=Reserva.objects.filter(
                fecha_clase=fecha_actual,
                clase__horario=clase.horario,
                clase__actividad=clase.actividad,
                en_lista_de_espera=False
            ).count()
            ocurrencia={
                'clase':clase,
                'fecha':fecha_actual,
                'dia':clase.dia_semana_nombre,
                'inscriptos':cantidad_inscriptos,
            }
            fecha_hora=timezone.datetime.combine(
                fecha_actual,clase.horario
            )
            fin_clase=fecha_hora+timedelta(hours=1,minutes=15)
            ahora=timezone.localtime().replace(tzinfo=None)
        
            if fin_clase>=ahora:
                    clases_pendientes.append(ocurrencia)
            else:
                    clases_finalizadas.append(ocurrencia)

            fecha_actual+=timedelta(days=7)
    clases_pendientes.sort(key=lambda x:(x['fecha'],x['clase'].horario))
    clases_finalizadas.sort(key=lambda x:(x['fecha'],x['clase'].horario),reverse=True)
    notificaciones_no_leidas = Notificacion.objects.filter(usuario=request.user, leida=False).count()
    print("pendientes",len(clases_pendientes))
    print("finalizadas",len(clases_finalizadas))
    return render(request,'gestion/mis_clases.html',{
        'clases_pendientes':clases_pendientes,
        'clases_finalizadas':clases_finalizadas,
        'cantidad_no_leidas': notificaciones_no_leidas,
    })
@login_required
def ver_inscriptos(request,clase_id,fecha):
    clase=Clase.objects.get(id=clase_id)
    fecha_obj=datetime.strptime(fecha, "%Y-%m-%d").date()
    reservas=Reserva.objects.filter(
        fecha_clase=fecha_obj,
        clase__horario=clase.horario,
        clase__actividad=clase.actividad,
        en_lista_de_espera=False
    ).select_related('usuario')
    datos=[]
    for reserva in reservas:
        datos.append({
            'nombre':reserva.usuario.first_name,
            'apellido':reserva.usuario.last_name,
            'dni':reserva.usuario.dni,
            'asistio':reserva.asistio,
            'estado':"✅" if reserva.asistio else("❌" if timezone.localtime()>timezone.make_aware(datetime.combine(fecha_obj,clase.horario))+timedelta(hours=1,minutes=15)else "-"),
        })
    return JsonResponse({'inscriptos':datos})


from.models import Voucher
@login_required
def mis_vouchers(request):
    vouchers=Voucher.objects.filter(cliente=request.user,utilizado=False).order_by("fecha_vencimiento")
    cantidad_no_leidas = Notificacion.objects.filter(usuario=request.user, leida=False).count()

    return render(request,"mis_vouchers.html",{"vouchers":vouchers,"cantidad_no_leidas":cantidad_no_leidas,})

import calendar
@login_required
def cancelar_reserva(request,reserva_id):
    reserva=get_object_or_404(
        Reserva,
        id=reserva_id,
        usuario=request.user
    )
    Strike.objects.create(
            usuario=request.user, 
            tipo='mensual'
    )
    # Dentro de cancelar_reserva o cancelar_clase_individual
    strikes_actuales = request.user.obtener_strikes_mes_actual('mensual')

    # Si llega a 3 (o el que sea tu límite), activamos la bandera
    if strikes_actuales >= 3:
        request.user.penalizacion_pendiente_mensual = True
        request.user.save()
        print(f"DEBUG: Penalización activada para {request.user.dni}") # MIRA TU TERMINAL

    if  reserva.modalidad.strip().lower()!="mensual":
        return redirect("mis_reservas")
    hoy=timezone.localdate()
    tiene_voucher=(reserva.fecha_clase - hoy)>=timedelta(days=2)
    ultimo_dia=calendar.monthrange(hoy.year,hoy.month)[1]
    fecha_vencimiento=hoy.replace(day=ultimo_dia)
    if tiene_voucher:
        Voucher.objects.create(
            cliente=request.user,
            fecha_vencimiento=fecha_vencimiento,
        )
        Notificacion.objects.create(
            usuario=request.user,
            mensaje="Cancelaste tu reserva correctamente. Se acreditó un voucher en tu cuenta, usalo antes de que expire!!!",
            leida=False
        )
        asunto="Voucher acreditado - Sportify"
        mensaje_html=f"""
        <div style="background:#000000;padding:40px;font-family:Poppins,sans-serif,text-aling:center;">
            <h1 style="color:#00ff88;">SPORTIFY</h1>
            <h2>Tu reserva fue cancelada correctamente</h2>
            <p> Como la cancelación se realizó con al menos 2 días de anticipación,se acreditó un voucher en tu cuenta</p>
            <p>Podrás utilizarlo para reservar otra clase hasta que finalice el mes corriente</p>
        </div>
        """
        email_message=EmailMultiAlternatives(
            asunto,"",settings.EMAIL_HOST_USER,[request.user.email]
        )
        email_message.attach_alternative(mensaje_html,"text/html")
        email_message.send()
    else:

        Notificacion.objects.create(
            usuario=request.user,
            mensaje="Cancelaste tu reserva correctamente. Como la cancelación se dió con menos de 2 días de anticipación, no se generó ningun voucher",
            leida=False
        )
        asunto="Reserva cancelada - Sportify"
        mensaje_html=f"""
        <div style="background:#000000;padding:40px;font-family:Poppins,sans-serif,text-aling:center;">
            <h1 style="color:#00ff88;">SPORTIFY</h1>
            <h2>Tu reserva fue cancelada correctamente</h2>
            <p> Como la cancelación se realizó con  menos 2 días de anticipación,no se acreditó un voucher en tu cuenta</p>
        </div>
        """
        email_message=EmailMultiAlternatives(
            asunto,"",settings.EMAIL_HOST_USER,[request.user.email]
        )
        email_message.attach_alternative(mensaje_html,"text/html")
        email_message.send()
        

    reserva.delete()
    
    return redirect("mis_vouchers")

@login_required
def cancelar_clase_individual(request, reserva_id):
    reserva = get_object_or_404(Reserva, id=reserva_id, usuario=request.user)

    if reserva.modalidad.strip().lower() != "individual":
        return redirect("mis_reservas")

    ahora = timezone.localtime()
    fecha_clase_dt = timezone.make_aware(
        datetime.combine(reserva.fecha_clase, reserva.clase.horario)
    )
    Strike.objects.create(
            usuario=request.user, 
            tipo='individual'
    )
    # Dentro de cancelar_reserva o cancelar_clase_individual
    strikes_actuales = request.user.obtener_strikes_mes_actual('individual')

    # Si llega a 3 (o el que sea tu límite), activamos la bandera
    if strikes_actuales >= 3:
        request.user.penalizacion_pendiente_individual = True
        request.user.save()
        print(f"DEBUG: Penalización activada para {request.user.dni}") # MIRA TU TERMINAL

    con_reintegro = (fecha_clase_dt - ahora) >= timedelta(days=1) and reserva.estado_pago in ('seña', 'total')

    if con_reintegro:
        monto = reserva.clase.actividad.precio_clase / 2
        actividad = reserva.clase.actividad.nombre
        fecha = reserva.fecha_clase.strftime("%d/%m/%Y")
        horario = reserva.clase.horario.strftime("%H:%M")
        Notificacion.objects.create(
            usuario=request.user,
            mensaje=f"Cancelaste tu clase individual de {actividad} el {fecha} a las {horario}hs. Se te otorgó un ticket de reintegro por ${monto} para retirar en recepción.",
            leida=False
        )
        asunto = "Ticket de reintegro - Sportify"
        mensaje_html = f"""
        <div style="background:#ffffff;padding:40px;font-family:Poppins,sans-serif;">
            <h1 style="color:#00ff88;">SPORTIFY</h1>
            <h2>Cancelacion exitosa</h2>
            <p>Cancelacion exitosa de la clase de {actividad} el {fecha} a las {horario}hs, se le ha otorgado un ticket por ${monto} para que pueda retirar su dinero de manera presencial. Muestre este email en recepcion.</p>
        </div>
        """
    else:

        actividad = reserva.clase.actividad.nombre
        fecha = reserva.fecha_clase.strftime("%d/%m/%Y")
        horario = reserva.clase.horario.strftime("%H:%M")
        Notificacion.objects.create(
            usuario=request.user,
            mensaje=f"Cancelaste tu clase individual de {actividad} el {fecha} a las {horario}hs.",
            leida=False
        )
        asunto = "Clase cancelada - Sportify"
        mensaje_html = f"""
        <div style="background:#ffffff;padding:40px;font-family:Poppins,sans-serif;">
            <h1 style="color:#00ff88;">SPORTIFY</h1>
            <h2>Cancelacion exitosa</h2>
            <p>Cancelacion exitosa de la clase de {actividad} el {fecha} a las {horario}hs.</p>
        </div>
        """

    email_message = EmailMultiAlternatives(
        asunto, "", settings.EMAIL_HOST_USER, [request.user.email]
    )
    email_message.attach_alternative(mensaje_html, "text/html")
    email_message.send()

    reserva.delete()
    return redirect("mis_reservas")

import qrcode 
from io import BytesIO
@login_required
def generar_qr(request,clase_id,fecha):
    contenido=f"{request.scheme}://{request.get_host()}/registrar-asistencia/{clase_id}/{fecha}/"
    cantidad_inscriptos=Reserva.objects.filter(
        clase_id=clase_id,
        fecha_clase=fecha
    ).count()
    qr=qrcode.make(contenido)
    buffer=BytesIO()
    qr.save(buffer, format='PNG')
    buffer.seek(0)
    return HttpResponse(buffer.getvalue(), content_type='image/png')

@login_required
def validar_horario_qr(request,clase_id,fecha):
    clase=Clase.objects.get(id=clase_id)
    fecha_obj=datetime.strptime(fecha,"%Y-%m-%d").date()
    inicio=timezone.make_aware(
        datetime.combine(fecha_obj,clase.horario)
    )
    fin=inicio + timedelta(hours=1)
    ahora=timezone.localtime()
    permitido=(
        inicio-timedelta(minutes=15)<=ahora<=fin + timedelta(minutes=15)
    )
    return JsonResponse({
        "permitido":permitido
    })

from django.contrib.auth import authenticate
def registrar_asistencia(request, clase_id, fecha):
    clase=Clase.objects.get(id=clase_id)
    fecha_obj=datetime.strptime(fecha,"%Y-%m-%d").date()
    inicio=timezone.make_aware(
        datetime.combine(fecha_obj,clase.horario)
    )
    fin=inicio+timedelta(hours=1)
    ahora=timezone.now()
    #ESCENARIO QR EXPIRADO
    if ahora<inicio-timedelta(minutes=15)or ahora>fin + timedelta(minutes=15):
        return render(request,"gestion/mensaje_asistencia.html",{
            "icono":"⌛",
            "titulo":"QR expirado",
            "mensaje":"El código QR ya no es válido. No se puede registrar tu asistencia a esta clase."})
    if request.method=="GET":
        return render(request,"gestion/registrar_asistencia.html")
    dni=request.POST.get("dni")
    password=request.POST.get("password")
    usuario=authenticate(
        request,
        username=dni,
        password=password
    )
    if usuario is None:
        return render(request,"gestion/registrar_asistencia.html",{
            "error":"DNI o contraseña incorrectos."
        })
    try:
        reserva=Reserva.objects.get(
            usuario=usuario,
            fecha_clase=fecha_obj,
            clase__horario=clase.horario,
            clase__actividad=clase.actividad,
        )
    except Reserva.DoesNotExist:
        return render(request,"gestion/mensaje_asistencia.html",{
            "icono":"❌",
            "titulo":"No estás inscripto",
            "mensaje":"Lo sentimos, no estás inscripto en esta clase."        })
    
    if reserva.asistio:
        return render(request,"gestion/mensaje_asistencia.html",{
            "icono":"⚠️",
            "titulo":"Asistencia ya registrada",
            "mensaje":"Ya registraste tu asistencia para esta clase previamente."
        })
    reserva.asistio=True
    reserva.save()
    return render(request,"gestion/mensaje_asistencia.html",{
        "icono":"✅",
        "titulo":"Asistencia registrada",
        "mensaje":"Asistencia registrada correctamente.Gracias por venir!"
        })

def estado_qr(request,clase_id,fecha):
    clase=Clase.objects.get(id=clase_id)
    fecha_obj=datetime.strptime(
        fecha,
        "%Y-%m-%d"
    ).date()
    inicio=timezone.make_aware(datetime.combine(fecha_obj,clase.horario))
    fin=inicio+timedelta(hours=1)
    ahora=timezone.localtime()
    qr_vigente=(
        inicio-timedelta(minutes=15)
        <= ahora<=
        fin + timedelta(minutes=15)
    )
    reservas=Reserva.objects.filter(
        fecha_clase=fecha_obj,
        clase__horario=clase.horario,
        clase__actividad=clase.actividad,
    )
    inscriptos=reservas.count()
    asistentes=reservas.filter(asistio=True)
    ultimo_asistente=asistentes.order_by("-id").first()
    lista_reservas=[]
    for reserva in reservas:
        lista_reservas.append({
            "id":reserva.id,
            "nombre":f"{reserva.usuario.first_name} {reserva.usuario.last_name}",
            "dni":reserva.usuario.dni,
            "asistio":reserva.asistio,
            "estado":"✅" if reserva.asistio else("-" if qr_vigente else"❌"),
        })
    return JsonResponse({
        "qr_vigente":qr_vigente,
        "inscriptos":inscriptos,
        "asistentes":reservas.filter(asistio=True).count(),
        "ultimo_asistente":(
            f"{ultimo_asistente.usuario.first_name} {ultimo_asistente.usuario.last_name}"
            if ultimo_asistente else None
        ),
        "reservas":lista_reservas,
    })

def pago_tarjeta(request):
    datos = request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect('grilla_actividades')

    # Defensa en profundidad: aunque este flujo solo se alcanza después de
    # pasar por inscribirse_clase (que ya valida el apto), volvemos a
    # chequear acá porque esta vista confirma la creación real de la Reserva.
    if not request.user.is_authenticated:
        request.session.pop('inscripcion_pendiente', None)
        return redirect('login')

    if request.user.rol == 'cliente' and not request.user.tiene_apto_vigente():
        messages.error(
            request,
            "Tu apto médico se encuentra vencido. Debes cargar uno nuevo para continuar "
            "utilizando las funciones de reserva e inscripción."
        )
        request.session.pop('inscripcion_pendiente', None)
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
            errores_tipeo = ["titular_incorrecto", "cvv_invalido", "tarjeta_vencida", "tarjeta_corta","tarjeta_inexistente","error_banco"]
            
            if resultado in errores_tipeo:
                if resultado == "titular_incorrecto":
                    messages.error(request, "El nombre del titular no coincide con el registrado en la tarjeta.")
                elif resultado == "cvv_invalido":
                    messages.error(request, "El CVV ingresado es incorrecto.")
                elif resultado == "tarjeta_vencida":
                    messages.error(request, "La tarjeta ingresada se encuentra vencida.")
                elif resultado == "tarjeta_corta":
                    messages.error(request, "La tarjeta ingresada debe tener 16 dígitos.")
                elif resultado=="tarjeta_inexistente":
                    messages.error(request,"La tarjeta no existe")
                elif resultado=="error_banco":
                    messages.error(request, "ERROR-No se pudo establecer conexión con el banco.")
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
            
            mensaje_sin_cupo = None
            
            if datos.get('tipo_operacion') == 'completar_senia':
                reserva = get_object_or_404(Reserva, id=datos['reserva_id'], usuario=request.user)
                reserva.estado_pago = 'total'
                reserva.monto_pagado = Decimal(datos['monto'])
                reserva.medio_pago = 'Tarjeta'
                reserva.save()
                mensaje_notificacion = f"Se completó con éxito el pago de tu clase: {reserva.clase.actividad.nombre} del {reserva.fecha_clase.strftime('%d/%m/%Y')}"

            elif datos.get('tipo_operacion') == 'renovar_mensualidad':
                reserva_ids = datos['reserva_ids']
                cant = len(reserva_ids)
                monto_unitario = Decimal(datos['monto']) / cant
                Reserva.objects.filter(
                    id__in=reserva_ids, usuario=request.user
                ).update(
                    estado_pago='total',
                    monto_pagado=monto_unitario,
                    medio_pago='Tarjeta',
                    fecha_reserva=timezone.now()
                )

                Mensualidad.objects.update_or_create(
                    usuario=request.user,
                    clase=clase,
                    actividad=clase.actividad,
                    mes=datos['mes'],
                    anio=datos['anio'],
                    defaults={'fecha_pago': hoy, 'estado': 'pagada'}
                )
                reserva = Reserva.objects.filter(id__in=datos['reserva_ids']).first()
                mensaje_notificacion = f"Se renovó tu mensualidad de {clase.actividad.nombre} los {clase.dia_semana_plural.lower()} a las {clase.horario.strftime('%H:%M')} hs correctamente."

            elif datos.get('flujo_tipo') == 'mensualidad':
                mes_current = fecha_inicial.month
                anio_actual = fecha_inicial.year
                dia_semana_objetivo = fecha_inicial.weekday()
                
                reserva_principal = None

                # 1. Fase A: Mes actual (pagado)
                fechas_con_cupo = datos.get('fechas_con_cupo', [])
                cant_fechas_mes_actual = len(fechas_con_cupo)

                for f_str in fechas_con_cupo:
                    fecha_evaluar = datetime.strptime(f_str, '%Y-%m-%d').date()
                    if Reserva.objects.filter(
                        usuario=request.user,
                        fecha_clase=fecha_evaluar,
                        clase__horario=clase.horario,
                        clase__actividad=clase.actividad,
                        en_lista_de_espera=False
                    ).exists():
                        continue
                    nueva_reserva = Reserva.objects.create(
                        usuario=request.user,
                        clase=clase,
                        fecha_clase=fecha_evaluar,
                        monto_pagado=Decimal(datos['monto']) / max(cant_fechas_mes_actual, 1),
                        estado_pago='total',
                        medio_pago='Tarjeta',
                        en_lista_de_espera=False,
                        modalidad='mensual'
                    )
                    if not reserva_principal:
                        reserva_principal = nueva_reserva

                # 2. Fase B: Mes siguiente completo (pendiente de pago)
                if mes_current == 12:
                    mes_siguiente = 1
                    anio_siguiente = anio_actual + 1
                else:
                    mes_siguiente = mes_current + 1
                    anio_siguiente = anio_actual

                _, ultimo_dia_mes_sig = monthrange(anio_siguiente, mes_siguiente)
                for d in range(1, ultimo_dia_mes_sig + 1):
                    f_sig = date(anio_siguiente, mes_siguiente, d)
                    if f_sig.weekday() != dia_semana_objetivo:
                        continue
                    if Reserva.objects.filter(
                        usuario=request.user,
                        fecha_clase=f_sig,
                        clase__horario=clase.horario,
                        clase__actividad=clase.actividad,
                        en_lista_de_espera=False
                    ).exists():
                        continue
                    Reserva.objects.create(
                        usuario=request.user,
                        clase=clase,
                        fecha_clase=f_sig,
                        monto_pagado=0,
                        estado_pago='pendiente',
                        medio_pago='Tarjeta',
                        en_lista_de_espera=False,
                        modalidad='mensual'
                    )
                
                # 3. Registrar la mensualidad en estado pagada
                Mensualidad.objects.update_or_create(
                    usuario=request.user,
                    clase=clase,
                    actividad=clase.actividad,
                    mes=mes_current,
                    anio=anio_actual,
                    defaults={
                        'fecha_pago': hoy,
                        'estado': 'pagada'
                    }
                )
                
                reserva = reserva_principal
                fechas_sin_cupo = datos.get('fechas_sin_cupo', [])
                mensaje_notificacion = f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre} los {clase.dia_semana_plural.lower()} a las {clase.horario.strftime('%H:%M')} hs. Las clases del próximo mes quedaron reservadas pendientes de pago."
                if fechas_sin_cupo:
                    mensaje_sin_cupo = (
                        f"La próxima clase de {clase.actividad.nombre} de los {clase.dia_semana_plural.lower()} "
                        f"a las {clase.horario.strftime('%H:%M')} hs no tiene cupo disponible. "
                        f"Tu mensualidad comenzará a partir de la próxima semana."
                    )
                    mensaje_notificacion += f" {mensaje_sin_cupo}"
                    request.session['mensualidad_sin_cupo'] = mensaje_sin_cupo
            
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
                    modalidad='individual' # <--- AGREGA ESTA LÍNEA
                )
                if datos['tipo_pago'] == 'senia':
                    mensaje_notificacion = f"Se realizó con éxito el pago de la seña para la clase: {clase.actividad.nombre} del {fecha_inicial.strftime('%d/%m/%Y')}"
                else:
                    mensaje_notificacion = f"Se realizó con éxito tu pago para la clase: {clase.actividad.nombre} del {fecha_inicial.strftime('%d/%m/%Y')}"

            Notificacion.objects.create(
                usuario=request.user,
                mensaje=mensaje_notificacion
            )

        threading.Thread(target=enviar_confirmacion, args=(request.user, clase, reserva), kwargs={'monto_total': Decimal(datos['monto']), 'mensaje_extra': mensaje_sin_cupo}).start()
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

    # Defensa en profundidad: mismo chequeo que en inscribirse_clase.
    if request.user.rol == 'cliente' and not request.user.tiene_apto_vigente():
        messages.error(
            request,
            "Tu apto médico se encuentra vencido. Debes cargar uno nuevo para continuar "
            "utilizando las funciones de reserva e inscripción."
        )
        request.session.pop('inscripcion_pendiente', None)
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
    Destino cuando el pago es aprobado. Usa get_or_create y el modelo 
    de usuario personalizado para evitar colisiones en la base de datos.
    """
    print("🟢 ENTRÓ A PAGO ÉXITO - PROCESANDO RESERVA")
    datos = request.session.get('inscripcion_pendiente')
    
    if not datos:
        messages.warning(request, 'La sesión de tu pago expiró o ya fue procesada.')
        return redirect('grilla_actividades')
        
    from .models import Clase, Reserva, Notificacion
    from reservas.models import Mensualidad
    
    clase = get_object_or_404(Clase, id=datos['clase_id'])
    fecha_clase = datetime.strptime(datos['fecha_clase'], '%Y-%m-%d').date()
    usuario_id = datos.get('usuario_id')
    usuario_reserva = get_object_or_404(Usuario, id=usuario_id) if usuario_id else request.user

    # Defensa en profundidad: aunque este flujo solo se alcanza después de
    # pasar por inscribirse_clase (que ya valida el apto), volvemos a
    # chequear acá porque esta vista confirma la creación real de la Reserva.
    if not usuario_reserva.tiene_apto_vigente():
        messages.error(
            request,
            "Tu apto médico se encuentra vencido. Debes cargar uno nuevo para continuar "
            "utilizando las funciones de reserva e inscripción."
        )
        request.session.pop('inscripcion_pendiente', None)
        return redirect('grilla_actividades')

    if datos.get('tipo_operacion') == 'completar_senia':
        reserva = get_object_or_404(Reserva, id=datos['reserva_id'])
        reserva.estado_pago = 'total'
        reserva.monto_pagado = Decimal(datos['monto'])
        reserva.medio_pago = 'Mercado Pago'
        reserva.save()
        
        mensaje_notificacion = f"Se completó con éxito el pago de tu clase: {reserva.clase.actividad.nombre} del {reserva.fecha_clase.strftime('%d/%m/%Y')}"
        
        Notificacion.objects.create(
            usuario=usuario_reserva,
            mensaje=mensaje_notificacion
        )

        if 'inscripcion_pendiente' in request.session:
            del request.session['inscripcion_pendiente']

        # =========================================================
    # LIMPIEZA DE PENALIZACIÓN TRAS PAGO EXITOSO
    # =========================================================
    if usuario_reserva.penalizacion_pendiente_individual:
        usuario_reserva.penalizacion_pendiente_individual = False
        usuario_reserva.save()
        print(f"✅ Penalización individual removida para {usuario_reserva.dni}")

    if usuario_reserva.penalizacion_pendiente_mensual:
        usuario_reserva.penalizacion_pendiente_mensual = False
        usuario_reserva.save()
        print(f"✅ Penalización mensual removida para {usuario_reserva.dni}")
        response = redirect('pago_confirmacion', reserva_id=reserva.id)
        response["ngrok-skip-browser-warning"] = "true"
        return response

    elif datos.get('tipo_operacion') == 'renovar_mensualidad':
        reserva_ids = datos['reserva_ids']
        cant = len(reserva_ids)
        monto_unitario = Decimal(datos['monto']) / cant
        Reserva.objects.filter(
            id__in=reserva_ids
        ).update(
            estado_pago='total',
            monto_pagado=monto_unitario,
            medio_pago='Mercado Pago',
            fecha_reserva=timezone.now()
        )

        Mensualidad.objects.update_or_create(
            usuario=usuario_reserva,
            clase=clase,
            actividad=clase.actividad,
            mes=datos['mes'],
            anio=datos['anio'],
            defaults={'fecha_pago': date.today(), 'estado': 'pagada'}
        )
        reserva = Reserva.objects.filter(id__in=datos['reserva_ids']).first()
        mensaje_notificacion = f"Se renovó tu mensualidad de {clase.actividad.nombre} los {clase.dia_semana_plural.lower()} a las {clase.horario.strftime('%H:%M')} hs correctamente."
        Notificacion.objects.create(
            usuario=usuario_reserva,
            mensaje=mensaje_notificacion
        )

        threading.Thread(target=enviar_confirmacion, args=(usuario_reserva, clase, reserva), kwargs={'monto_total': Decimal(datos['monto'])}).start()

        if 'inscripcion_pendiente' in request.session:
            del request.session['inscripcion_pendiente']
        response = redirect('pago_confirmacion', reserva_id=reserva.id)
        response["ngrok-skip-browser-warning"] = "true"
        return response

    elif datos.get('flujo_tipo') == 'mensualidad':
        with transaction.atomic():
            mes_current = fecha_clase.month
            anio_actual = fecha_clase.year
            dia_semana_objetivo = fecha_clase.weekday()

            reserva_principal = None

            # Fase A: Mes actual (pagado)
            fechas_con_cupo = datos.get('fechas_con_cupo', [])
            cant_fechas_mes_actual = len(fechas_con_cupo)

            for f_str in fechas_con_cupo:
                fecha_evaluar = datetime.strptime(f_str, '%Y-%m-%d').date()
                if Reserva.objects.filter(
                    usuario=usuario_reserva,
                    fecha_clase=fecha_evaluar,
                    clase__horario=clase.horario,
                    clase__actividad=clase.actividad,
                    en_lista_de_espera=False
                ).exists():
                    continue
                nueva_reserva = Reserva.objects.create(
                    usuario=usuario_reserva,
                    clase=clase,
                    fecha_clase=fecha_evaluar,
                    monto_pagado=Decimal(datos['monto']) / max(cant_fechas_mes_actual, 1),
                    estado_pago='total',
                    medio_pago='Mercado Pago',
                    en_lista_de_espera=False,
                    modalidad='mensual'
                )
                if not reserva_principal:
                    reserva_principal = nueva_reserva

            # Fase B: Mes siguiente completo (pendiente de pago)
            if mes_current == 12:
                mes_siguiente = 1
                anio_siguiente = anio_actual + 1
            else:
                mes_siguiente = mes_current + 1
                anio_siguiente = anio_actual

            _, ultimo_dia_mes_sig = monthrange(anio_siguiente, mes_siguiente)
            for d in range(1, ultimo_dia_mes_sig + 1):
                f_sig = date(anio_siguiente, mes_siguiente, d)
                if f_sig.weekday() != dia_semana_objetivo:
                    continue
                if Reserva.objects.filter(
                    usuario=usuario_reserva,
                    fecha_clase=f_sig,
                    clase__horario=clase.horario,
                    clase__actividad=clase.actividad,
                    en_lista_de_espera=False
                ).exists():
                    continue
                Reserva.objects.create(
                    usuario=usuario_reserva,
                    clase=clase,
                    fecha_clase=f_sig,
                    monto_pagado=0,
                    estado_pago='pendiente',
                    medio_pago='Mercado Pago',
                    en_lista_de_espera=False,
                    modalidad='mensual'
                )

            # Registrar la mensualidad
            Mensualidad.objects.update_or_create(
                usuario=usuario_reserva,
                clase=clase,
                actividad=clase.actividad,
                mes=mes_current,
                anio=anio_actual,
                defaults={
                    'fecha_pago': date.today(),
                    'estado': 'pagada'
                }
            )

        reserva = reserva_principal

        # Notificación
        fechas_sin_cupo = datos.get('fechas_sin_cupo', [])
        mensaje_notificacion = f"Se realizó con éxito el pago de tu MENSUALIDAD para: {clase.actividad.nombre} los {clase.dia_semana_plural.lower()} a las {clase.horario.strftime('%H:%M')} hs. Las clases del próximo mes quedaron reservadas pendientes de pago."
        mensaje_extra = None
        if fechas_sin_cupo:
            mensaje_extra = (
                f"La próxima clase de {clase.actividad.nombre} de los {clase.dia_semana_plural.lower()} "
                f"a las {clase.horario.strftime('%H:%M')} hs no tiene cupo disponible. "
                f"Tu mensualidad comenzará a partir de la próxima semana."
            )
            mensaje_notificacion += f" {mensaje_extra}"

        Notificacion.objects.create(
            usuario=usuario_reserva,
            mensaje=mensaje_notificacion
        )

        threading.Thread(target=enviar_confirmacion, args=(usuario_reserva, clase, reserva), kwargs={'monto_total': Decimal(datos['monto']), 'mensaje_extra': mensaje_extra}).start()

    else:
        # Flujo individual con Mercado Pago
        with transaction.atomic():
            reserva, creado = Reserva.objects.get_or_create(
                usuario=usuario_reserva,
                clase=clase,
                fecha_clase=fecha_clase,
                defaults={
                    'monto_pagado': datos['monto'],
                    'estado_pago': 'seña' if datos['tipo_pago'] == 'senia' else 'total',
                    'medio_pago': 'Mercado Pago',
                    'modalidad': 'individual'
                }
            )
            if not creado:
                reserva.modalidad = 'individual'
                reserva.save()

        if creado:
            print(f"✅ Reserva {reserva.id} creada con éxito en la base de datos.")

            if datos['tipo_pago'] == 'senia':
                mensaje_notificacion = f"Se realizó con éxito el pago de la seña para la clase: {clase.actividad.nombre} del {fecha_clase.strftime('%d/%m/%Y')}"
            else:
                mensaje_notificacion = f"Se realizó con éxito tu pago para la clase: {clase.actividad.nombre} del {fecha_clase.strftime('%d/%m/%Y')}"

            Notificacion.objects.create(
                usuario=usuario_reserva,
                mensaje=mensaje_notificacion
            )

            threading.Thread(target=enviar_confirmacion, args=(usuario_reserva, clase, reserva)).start()

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
    translation.activate('es')
    if reserva_id == 0:
        return render(request, 'pago_confirmacion.html', {'exito': False})
    reserva = get_object_or_404(Reserva, id=reserva_id, usuario=request.user)
    context = {
        'exito': True,
        'reserva': reserva,
        'clase': reserva.clase,
        'mensaje_sin_cupo': request.session.pop('mensualidad_sin_cupo', None),
    }
    if reserva.modalidad == 'mensual':
        dia_semana = (reserva.fecha_clase.weekday() + 1) % 7 + 1
        fechas = Reserva.objects.filter(
            usuario=request.user,
            clase__actividad=reserva.clase.actividad,
            clase__horario=reserva.clase.horario,
            fecha_clase__month=reserva.fecha_clase.month,
            fecha_clase__year=reserva.fecha_clase.year,
            fecha_clase__week_day=dia_semana,
            modalidad='mensual',
        ).order_by('fecha_clase')
        context['es_mensualidad'] = True
        context['total_mensualidad'] = sum(r.monto_pagado for r in fechas)
    return render(request, 'pago_confirmacion.html', context)


@login_required
def completar_pago_senia(request, reserva_id):
    reserva = get_object_or_404(Reserva, id=reserva_id, usuario=request.user)
    if reserva.estado_pago != 'seña':
        messages.error(request, 'Esta reserva no tiene una seña pendiente de pago.')
        return redirect('mis_reservas')

    monto_restante = reserva.clase.actividad.precio_clase / 2

    if request.method == 'POST':
        medio_pago = request.POST.get('medio_pago')
        if medio_pago not in ('Tarjeta', 'Mercado Pago'):
            messages.error(request, 'Seleccioná un método de pago válido.')
            return render(request, 'pago_metodo.html', {
                'titulo': 'Completar pago de seña',
                'subtitulo': 'Falta pagar el 50% restante para confirmar tu clase',
                'monto': monto_restante,
                'action_url': request.path,
            })

        request.session['inscripcion_pendiente'] = {
            'tipo_operacion': 'completar_senia',
            'reserva_id': reserva.id,
            'monto': str(monto_restante),
            'medio_pago': medio_pago,
            'clase_id': reserva.clase.id,
            'fecha_clase': reserva.fecha_clase.strftime('%Y-%m-%d'),
            'usuario_id': request.user.id,
        }

        if medio_pago == 'Tarjeta':
            return redirect('pago_tarjeta')
        else:
            return redirect('pago_mercadopago')

    return render(request, 'pago_metodo.html', {
        'titulo': 'Completar pago de seña',
        'subtitulo': 'Falta pagar el 50% restante para confirmar tu clase',
        'monto': monto_restante,
        'action_url': request.path,
    })


@login_required
def renovar_mensualidad(request, clase_id):
    clase = get_object_or_404(Clase, id=clase_id)

    reservas_pendientes = Reserva.objects.filter(
        usuario=request.user,
        clase=clase,
        modalidad='mensual',
        estado_pago='pendiente',
        fecha_clase__gte=date.today(),
    ).order_by('fecha_clase')

    if not reservas_pendientes.exists():
        messages.error(request, 'No hay reservas pendientes para renovar esta mensualidad.')
        return redirect('mis_reservas')

    target_month = reservas_pendientes.first().fecha_clase.month
    target_year = reservas_pendientes.first().fecha_clase.year
    monto = clase.actividad.precio_mensualidad

    if request.method == 'POST':
        medio_pago = request.POST.get('medio_pago')
        if medio_pago not in ('Tarjeta', 'Mercado Pago'):
            messages.error(request, 'Seleccioná un método de pago válido.')
            return render(request, 'pago_metodo.html', {
                'titulo': 'Renovar mensualidad',
                'subtitulo': f'{clase.actividad.nombre} - {clase.dia_semana_plural} {clase.horario.strftime("%H:%M")} hs',
                'monto': monto,
                'action_url': request.path,
            })

        request.session['inscripcion_pendiente'] = {
            'tipo_operacion': 'renovar_mensualidad',
            'clase_id': clase.id,
            'reserva_ids': [r.id for r in reservas_pendientes],
            'monto': str(monto),
            'medio_pago': medio_pago,
            'fecha_clase': reservas_pendientes.first().fecha_clase.strftime('%Y-%m-%d'),
            'mes': target_month,
            'anio': target_year,
            'usuario_id': request.user.id,
        }

        if medio_pago == 'Tarjeta':
            return redirect('pago_tarjeta')
        else:
            return redirect('pago_mercadopago')

    return render(request, 'pago_metodo.html', {
        'titulo': 'Renovar mensualidad',
        'subtitulo': f'{clase.actividad.nombre} - {clase.dia_semana_plural} {clase.horario.strftime("%H:%M")} hs',
        'monto': monto,
        'action_url': request.path,
    })


def enviar_confirmacion(usuario, clase, reserva, monto_total=None, mensaje_extra=None):
    try:
        fecha_clase = reserva.fecha_clase
        if isinstance(fecha_clase, str):
            fecha_clase = datetime.strptime(fecha_clase, '%Y-%m-%d').date()

        monto_mostrar = monto_total if monto_total is not None else reserva.monto_pagado

        if reserva.modalidad == 'mensual':
            meses = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                     'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
            subject = f"Sportify - Mensualidad confirmada: {clase.actividad.nombre}"
            message = (
                f"Hola {usuario.first_name},\n\n"
                f"Te inscribiste a la mensualidad de {clase.actividad.nombre} "
                f"los {clase.dia_semana_plural.lower()} a las {clase.horario.strftime('%H:%M')} hs "
                f"para el mes de {meses[fecha_clase.month]}.\n"
                f"Monto pagado: ${monto_mostrar}\n"
                f"Medio de pago: {reserva.medio_pago}\n"
            )
            if mensaje_extra:
                message += f"\n{mensaje_extra}\n"
            message += f"\n¡Gracias por elegir Sportify!"
        else:
            subject = f"Sportify - Inscripción confirmada: {clase.actividad.nombre}"
            message = (
                f"Hola {usuario.first_name},\n\n"
                f"Te inscribiste a la clase de {clase.actividad.nombre} del "
                f"{fecha_clase.strftime('%d-%m-%Y')} a las {clase.horario}.\n"
                f"Monto pagado: ${monto_mostrar}\n"
                f"Medio de pago: {reserva.medio_pago}\n\n"
                f"¡Gracias por elegir Sportify!"
            )

        send_mail(
            subject=subject,
            message=message,
            from_email='sportifygymapp@gmail.com',
            recipient_list=[usuario.email],
            fail_silently=True,
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
    valores_clase = request.session.pop('valores_clase', {})
    
    # Tomamos la pestaña activa: primero del GET, luego de la sesión, sino 'clases'
    pestania_activa = request.GET.get('pestania') or request.session.pop('pestania_activa', 'clases')

    ahora = date.today()

    if request.method == 'POST':
        # Limpiar mensajes previos para evitar mezclas entre formularios
        storage = messages.get_messages(request)
        storage.used = True 
    
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

        # --- B. PROCESAR PROGRAMAR CLASE (RECURSIVA CON CUPO AJUSTADO) ---
        elif action == 'crear_clase':
            pestania_activa = 'clases'
            actividad_id = request.POST.get('actividad')
            profesor_id = request.POST.get('profesor')
            dia_semana_str = request.POST.get('dia_semana') # '0'=Lunes, '1'=Martes, etc.
            fecha_str = request.POST.get('fecha')           # Puede venir vacío ''
            horario_str = request.POST.get('horario')
            cupo_str = request.POST.get('cupo')

            # 💾 Función auxiliar para guardar el estado actual del formulario ante fallos
            # 💾 Nueva función con casteo explícito a String para el HTML
            def persistir_formulario_clase():
                request.session['valores_clase'] = {
                    'actividad': str(request.POST.get('actividad', '')), # 🌟 Forzamos String
                    'profesor': str(request.POST.get('profesor', '')),   # 🌟 Forzamos String
                    'dia_semana': str(request.POST.get('dia_semana', '')), # 🌟 Forzamos String
                    'cupo': request.POST.get('cupo', '30'),
                    'fecha': request.POST.get('fecha', ''),
                    'horario': request.POST.get('horario', ''),
                }
                request.session['pestania_activa'] = 'clases'
                request.session.modified = True
            if not profesor_id or not actividad_id or not horario_str or not cupo_str or not dia_semana_str:
                persistir_formulario_clase() # 👈 Agregado acá
                messages.error(request, "Por favor, complete todos los campos obligatorios (Actividad, Profesor, Día y Cupo).")
                return redirect('panel_admin') # 👈 Redirección limpia
            else:
                try:
                    horario_obj = datetime.strptime(horario_str, "%H:%M").time()
                except ValueError:
                    horario_obj = datetime.strptime(horario_str, "%H:%M:%S").time()

                cupo_nuevo = int(cupo_str)
                dia_semana_target = int(dia_semana_str) # 0=Lunes, 1=Martes...

                # --- CÁLCULO DE FECHA DE INICIO SI VIENE VACÍA ---
                if not fecha_str or fecha_str == "":
                    dias_faltantes = (dia_semana_target - ahora.weekday()) % 7
                    fecha_obj = ahora + timedelta(days=dias_faltantes)
                else:
                    fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()

                # === VALIDACIONES DE NEGOCIO (Con persistencia agregada) ===
                if horario_obj.minute != 0 or horario_obj.second != 0:
                    persistir_formulario_clase() # 👈 Copiar los datos a la sesión
                    messages.error(request, "Error: Las clases deben comenzar estrictamente en punto (Ej: 19:00).")
                    return redirect('panel_admin')
                
                elif horario_obj.hour < 8 or horario_obj.hour > 20:
                    persistir_formulario_clase() # 👈 Copiar los datos a la sesión
                    messages.error(request, "Error: El gimnasio se encuentra cerrado. Las clases se dictan únicamente de 08 a 20 hs.")
                    return redirect('panel_admin')
                
                elif fecha_obj < ahora - timedelta(days=7):
                    persistir_formulario_clase() # 👈 Copiar los datos a la sesión
                    messages.error(request, "Error: No se pueden programar clases en una fecha que ya pasó.")
                    return redirect('panel_admin')
                
                
                elif cupo_nuevo < 1 or cupo_nuevo > 30:
                    persistir_formulario_clase() # 👈 Copiar los datos a la sesión
                    messages.error(request, "Error: El cupo de la clase debe estar entre 1 y 30.")
                    return redirect('panel_admin')
                
                else:
                    fin_de_anio = date(fecha_obj.year, 12, 31)

                    # 1. Generar lista de fechas recursivas
                    fechas_a_crear = []
                    curr = fecha_obj
                    while curr <= fin_de_anio:
                        if curr.weekday() == dia_semana_target:
                            fechas_a_crear.append(curr)
                        curr += timedelta(days=1)

                    if not fechas_a_crear:
                        persistir_formulario_clase()
                        messages.error(request, "Error: No se encontraron fechas válidas para crear clases en este año.")
                        return redirect('panel_admin')

                    # 2. VALIDACIÓN MATEMÁTICA DE CAPACIDAD DEL GIMNASIO
                    from django.db.models import Sum
                    cupo_excedido = False
                    fecha_conflicto = None
                    cupos_ya_asignados = 0

                    for f in fechas_a_crear:
                        datos_cupo = Clase.objects.filter(
                            fecha=f,
                            horario=horario_obj
                        ).aggregate(total=Sum('cupo_maximo'))
                        
                        cupos_existentes = datos_cupo['total'] or 0
                        
                        if (cupos_existentes + cupo_nuevo) > 30:
                            cupo_excedido = True
                            fecha_conflicto = f
                            cupos_ya_asignados = cupos_existentes
                            break

                    if cupo_excedido:
                        persistir_formulario_clase()
                        cupos_restantes = 30 - cupos_ya_asignados
                        messages.error(
                            request, 
                            f"Error: No se pueden asignar {cupo_nuevo} cupos. "
                            f"El día {fecha_conflicto.strftime('%d/%m/%Y')} a las {horario_obj.strftime('%H:%M')} hs "
                            f"ya tenés {cupos_ya_asignados} cupos tomados por otras clases. "
                            f"Solo podés asignar un cupo de hasta {cupos_restantes} para esta franja."
                        )
                        return redirect('panel_admin')
                    
                    else:
                        # 3. VERIFICACIÓN DE DISPONIBILIDAD DEL PROFESOR Y CHOQUE DE LA MISMA ACTIVIDAD
                        profesor_ocupado = False
                        ya_existe_choque = False

                        for f in fechas_a_crear:
                            if Clase.objects.filter(profesor_id=profesor_id, horario=horario_obj, fecha=f).exists():
                                profesor_ocupado = True
                                fecha_conflicto = f
                                break
                            if Clase.objects.filter(actividad_id=actividad_id, horario=horario_obj, fecha=f).exists():
                                ya_existe_choque = True
                                fecha_conflicto = f
                                break

                        if profesor_ocupado:
                            persistir_formulario_clase()
                            messages.error(request, f"Error: El profesor ya se encuentra asignado a otra clase en ese mismo día y horario.")
                            return redirect('panel_admin')
                        
                        elif ya_existe_choque:
                            persistir_formulario_clase() # 👈 Guardamos datos ante choque de actividad
                            messages.error(request, f"Error: ya existen clases de esa actividad en el horario y dia seleccionado.")
                            return redirect('panel_admin') # 👈 Agregado el return para que no intente crear clases si hay choque
                        
                        else:
                            # 4. CREACIÓN ATÓMICA DE LA SERIE
                            actividad = Actividad.objects.get(id=actividad_id)
                            profesor = Profesor.objects.get(id=profesor_id)

                            try:
                                with transaction.atomic():
                                    for f in fechas_a_crear:
                                        Clase.objects.create(
                                            actividad=actividad,
                                            profesor=profesor,
                                            fecha=f,
                                            horario=horario_obj,
                                            cupo_maximo=cupo_nuevo
                                        )
                                    
                                    # Notificación interna
                                    Notificacion.objects.create(
                                        usuario=profesor.usuario,
                                        mensaje=(
                                            f"Nueva serie de clases de {actividad.nombre} asignada para los "
                                            f"días {fecha_obj.strftime('%A')} a las {horario_obj.strftime('%H:%M')} hs."
                                        ),
                                        leida=False
                                    )
                                    
                                    # Envío de Correo (Tus bloques de email quedan igual...)
                                    asunto = "Nueva serie de clases asignada - Sportify"
                                    mensaje_texto = f"Hola {profesor.nombre},\nSe te ha asignado una serie de clases de {actividad.nombre} desde el {fecha_obj.strftime('%d/%m/%Y')} hasta fin de año."
                                    mensaje_html = f"""
                                    <div style="background-color:#000000;padding:40px;font-family:Poppins,sans-serif; text-align:center;">
                                        <h1 style="color:#00ff88;">SPORTIFY</h1>
                                        <h2 style="color:white;">Nueva serie de clases asignada</h2>
                                        <div style="background:#1c1c1e; padding:20px; border-radius:10px; margin:20px auto; max-width:400px; color:white;">
                                            <p><b>Actividad:</b> {actividad.nombre}</p>
                                            <p><b>Horario:</b> {horario_obj.strftime('%H:%M')} hs</p>
                                            <p><b>Inicio:</b> {fecha_obj.strftime('%d/%m/%Y')} hasta el 31/12</p>
                                            <p><b>Cupo Asignado:</b> {cupo_nuevo} alumnos</p>
                                        </div>
                                    </div>
                                    """
                                    email_message = EmailMultiAlternatives(asunto, mensaje_texto, settings.EMAIL_HOST_USER, [profesor.correo])
                                    email_message.attach_alternative(mensaje_html, "text/html")
                                    email_message.send()

                                messages.success(request, f"Clases creadas con exito")
                                return redirect('panel_admin')
                            
                            except Exception as e:
                                persistir_formulario_clase() # 👈 Guardamos si falla la base de datos o el mail
                                messages.error(request, f"Error al procesar la creación masiva: {e}")
                                return redirect('panel_admin')
                            
        # --- C. PROCESAR REGISTRAR PROFESOR ---
        elif action == 'registrar_profesor':
            pestania_activa = 'profesores'
            
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

            if errores:
                request.session['errores_profesor'] = errores
                request.session['valores_profesor'] = request.POST.dict()
                request.session['mostrar_modal_profesor'] = True
                request.session['pestania_activa'] = 'profesores'
                return redirect('panel_admin')

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

                    email_message = EmailMultiAlternatives(asunto, mensaje_texto, settings.EMAIL_HOST_USER, [correo])
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
                return redirect('panel_admin')
                
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

        # --- E. DAR DE BAJA PROFESOR ---
        elif action == 'dar_de_baja_profesor':
            pestania_activa = 'profesores'
            profesor = Profesor.objects.get(id=request.POST.get('profesor_id'))
            profesor.usuario.is_active = False
            profesor.usuario.save()
            messages.success(request, f"El profesor {profesor.nombre} ha sido dado de baja correctamente.")
            return redirect('panel_admin')

    # =========================================================
    # ARMADO DE DATOS (MÉTODO GET Y RENDERIZADO)
    # =========================================================
    año = int(request.GET.get('anio', ahora.year))
    mes = int(request.GET.get('mes', ahora.month))
    
    todas_las_clases = Clase.objects.all()

    cal = calendar.Calendar(firstweekday=0)
    semanas_matriz = cal.monthdayscalendar(año, mes)
    meses_nombres = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    clases_por_dia = {}
    import django.db.models as django_models
    
    for semana in semanas_matriz:
        for dia in semana:
            if dia != 0:
                fecha_casillero = date(año, mes, dia)
                
                clases_por_dia[dia] = []
                for clase in todas_las_clases:
                    if clase.fecha == fecha_casillero:
                        # Si usás un método para ver cupos, se mantiene igual
                        if hasattr(clase, 'cupos_para_fecha'):
                            clase.cupos_mostrar = clase.cupos_para_fecha(fecha_casillero)
                            
                        clases_por_dia[dia].append(clase)

    # Cálculo de ganancias en tiempo real
    resultado_ganancias = Reserva.objects.aggregate(total=django_models.Sum('monto_pagado'))
    total_ganancias = resultado_ganancias['total'] if resultado_ganancias['total'] is not None else 0.0

    context = {
        'actividades': Actividad.objects.all(),
        'profesores': Profesor.objects.filter(usuario__is_active=True),
        'semanas_matriz': semanas_matriz,
        'mes_nombre': meses_nombres[mes],
        'mes_actual': mes,
        'anio_actual': año,
        'clases_por_dia': clases_por_dia,
        'hoy': ahora,
        'pestania_activa': pestania_activa,
        'total_ganancias': total_ganancias, 
        'errores_profesor': errores_profesor,
        'valores_profesor': valores_profesor,
        'mostrar_modal_profesor': mostrar_modal_profesor,
        'valores_clase': valores_clase,
        'usuarios': Usuario.objects.exclude(rol='admin').order_by('last_name', 'first_name'),
    }
    return render(request, 'panel_admin.html', context)


@login_required
def actividad_usuario(request, user_id):
    if request.user.rol != 'admin':
        return redirect('grilla_actividades')

    usuario = get_object_or_404(Usuario, id=user_id)

    # Notificaciones recientes (últimas 10) — aplica a cualquier rol
    notificaciones = Notificacion.objects.filter(usuario=usuario).order_by('-fecha')[:10]

    # Datos específicos según el rol
    reservas = []
    mensualidades = []
    vouchers = []
    clases_profesor = []
    suspension_set = set()

    if usuario.rol == 'profesor':
        # Buscar el registro Profesor asociado a este usuario
        try:
            profesor = Profesor.objects.get(usuario=usuario)
        except Profesor.DoesNotExist:
            profesor = None

        if profesor:
            # Clases que dicta el profesor (más antigua primero)
            clases_profesor = Clase.objects.filter(
                profesor=profesor
            ).select_related('actividad').order_by('fecha', 'horario')

            # Suspensiones de estas clases
            clases_ids = [c.id for c in clases_profesor]
            suspensiones_prof = SuspensionClase.objects.filter(
                clase_id__in=clases_ids
            ).values_list('clase_id', 'fecha')
            suspension_set_prof = {(s[0], s[1]) for s in suspensiones_prof}

            # Para cada clase, contar cuántos inscriptos tiene y si está suspendida
            for c in clases_profesor:
                c.cantidad_inscriptos = Reserva.objects.filter(
                    clase=c,
                    fecha_clase=c.fecha,
                    en_lista_de_espera=False,
                ).count()
                c.suspendida = (c.id, c.fecha) in suspension_set_prof

    elif usuario.rol == 'cliente':
        # Reservas del usuario (más antigua primero)
        reservas = Reserva.objects.filter(usuario=usuario).select_related('clase', 'clase__actividad').order_by('fecha_clase')

        # Mensualidades del usuario
        mensualidades = Mensualidad.objects.filter(usuario=usuario).select_related('actividad', 'clase').order_by('-anio', '-mes')

        # Vouchers del usuario
        vouchers = Voucher.objects.filter(cliente=usuario).order_by('-fecha_otorgado')

        # Suspensiones de las clases donde este usuario tiene reservas
        if reservas.exists():
            clases_ids = reservas.values_list('clase_id', flat=True).distinct()
            fechas_clases = reservas.values_list('fecha_clase', flat=True).distinct()
            suspensiones = SuspensionClase.objects.filter(
                clase_id__in=list(clases_ids),
                fecha__in=list(fechas_clases),
            )
            suspension_set = {(s.clase_id, s.fecha) for s in suspensiones}

            ahora = timezone.now()
            for r in reservas:
                r.suspendida = (r.clase_id, r.fecha_clase) in suspension_set
                r.clase_eliminada = not r.clase.activa
                # Verificar si la clase ya pasó (hora de clase + 1h15m de duración)
                clase_datetime = timezone.make_aware(
                    datetime.combine(r.fecha_clase, r.clase.horario)
                )
                r.ya_finalizo = ahora > (clase_datetime + timedelta(hours=1, minutes=15))

    context = {
        'usuario': usuario,
        'reservas': reservas,
        'mensualidades': mensualidades,
        'vouchers': vouchers,
        'clases_profesor': clases_profesor,
        'notificaciones': notificaciones,
    }
    return render(request, 'actividad_usuario.html', context)


def validar_baja(request):
    profesor_id = request.POST.get('profesor_id')
    profesor = Profesor.objects.get(id=profesor_id)
    
    # Verificamos si tiene clases futuras ACTIVAS
    tiene_clases = Clase.objects.filter(
        profesor=profesor, 
        fecha__gte=timezone.now().date(),
        activa=True,
    ).exists()
    
    # Devolvemos un JSON que JavaScript entenderá
    return JsonResponse({'es_valido': not tiene_clases})


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
    pagos = Reserva.objects.filter(usuario=request.user).order_by('-fecha_reserva').exclude(estado_pago='pendiente')
    
    for pago in pagos:
        # Obtenemos mes y año de la clase reservada
        mes_clase = pago.fecha_clase.month
        anio_clase = pago.fecha_clase.year
        
        # Lógica para detectar si esta reserva pertenece a una mensualidad pagada
        # Buscamos si existe una mensualidad para el mismo mes de la clase
        # O para el mes anterior (que es donde se suele pagar la mensualidad del mes siguiente)
        mes_anterior = mes_clase - 1 if mes_clase > 1 else 12
        anio_anterior = anio_clase if mes_clase > 1 else anio_clase - 1
        
        es_mensual = Mensualidad.objects.filter(
            usuario=request.user,
            clase=pago.clase,
            estado='pagada'
        ).filter(
            models.Q(mes=mes_clase, anio=anio_clase) | 
            models.Q(mes=mes_anterior, anio=anio_anterior)
        ).exists()
        
        pago.es_mensual = es_mensual
        
        # Asignación de fechas reales para la tabla
        if es_mensual:
            mensualidad = Mensualidad.objects.filter(
                usuario=request.user,
                clase=pago.clase,
                mes=pago.fecha_clase.month,
                anio=pago.fecha_clase.year,
                estado='pagada'
            ).first()
            pago.fecha_pago_real = mensualidad.fecha_pago if mensualidad and mensualidad.fecha_pago else pago.fecha_reserva
        else:
            pago.fecha_pago_real = pago.fecha_reserva
        pago.fecha_clase_real = pago.fecha_clase
    
    '''for pago in pagos:
        # Buscamos si existe una mensualidad pagada para esa actividad, mes y año
        # y que además haya sido creada ANTES o EL MISMO DÍA que la reserva.
        mensualidad = Mensualidad.objects.filter(
            usuario=request.user,
            actividad=pago.clase.actividad,
            mes=pago.fecha_clase.month,
            anio=pago.fecha_clase.year,
            estado='pagada'
        ).first() # Obtenemos la primera coincidencia

        if mensualidad:
            # Comparamos: Si la reserva ocurrió el mismo día o después de que se 
            # generó la mensualidad, entonces es parte de la mensualidad.
            # (Nota: 'fecha_pago' es el campo estándar. Si tu modelo usa otro nombre, cámbialo)
            pago.es_mensual = (pago.fecha_reserva.date() >= mensualidad.fecha_pago)
        else:
            pago.es_mensual = False
        
        # Fechas para la tabla
        pago.fecha_pago_real = pago.fecha_reserva
        pago.fecha_clase_real = pago.fecha_clase'''
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

    if mes_hoy == 12:
        mes_siguiente = 1
        anio_siguiente = anio_hoy + 1
    else:
        mes_siguiente = mes_hoy + 1
        anio_siguiente = anio_hoy

    mensualidades_siguientes = Mensualidad.objects.filter(
        usuario=request.user,
        mes=mes_siguiente,
        anio=anio_siguiente,
        estado='pagada'
    )

    def _info_clase(m):
        if m.clase:
            return m.clase.dia_semana_nombre, m.clase.horario.strftime('%H:%M')
        return None, None

    resultados_mensualidad = []
    procesados = set()

    for m in mensualidades_actuales:
        key = (m.actividad.id, m.clase_id)
        if key in procesados:
            continue
        procesados.add(key)
        dia, horario = _info_clase(m)
        
        if m.estado == 'pagada':
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'clase_dia': dia,
                'clase_horario': horario,
                'estado': 'pagada',
                'mensaje': f'Su mensualidad de {m.actividad.nombre} está paga. ¡Puede disfrutar de su actividad!'
            })
        elif m.estado == 'pendiente' and dia_hoy <= 10:
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'clase_dia': dia,
                'clase_horario': horario,
                'estado': 'pendiente',
                'mensaje': f'Su mensualidad de {m.actividad.nombre} está pendiente de pago. Por favor abone antes del día 11.'
            })
        elif m.estado == 'vencida' or (m.estado == 'pendiente' and dia_hoy > 10):
            resultados_mensualidad.append({
                'actividad': m.actividad.nombre,
                'clase_dia': dia,
                'clase_horario': horario,
                'estado': 'vencida',
                'mensaje': f'Tu mensualidad de {m.actividad.nombre} ha sido suspendida por falta de pago. El vencimiento fue el día 10 del corriente mes.'
            })

    if dia_hoy <= 10:
        for m_ant in mensualidades_anteriores:
            key = (m_ant.actividad.id, m_ant.clase_id)
            if key in procesados:
                continue
            procesados.add(key)
            dia, horario = _info_clase(m_ant)
            resultados_mensualidad.append({
                'actividad': m_ant.actividad.nombre,
                'clase_dia': dia,
                'clase_horario': horario,
                'estado': 'pagada',
                'mensaje': f'Su mensualidad de {m_ant.actividad.nombre} se encuentra vigente (Período de gracia de renovación activo hasta el 10/{mes_hoy}).'
            })

    for m_sig in mensualidades_siguientes:
        key = (m_sig.actividad.id, m_sig.clase_id)
        if key in procesados:
            continue
        procesados.add(key)
        dia, horario = _info_clase(m_sig)
        resultados_mensualidad.append({
            'actividad': m_sig.actividad.nombre,
            'clase_dia': dia,
            'clase_horario': horario,
            'estado': 'pagada',
            'mensaje': f'Su mensualidad de {m_sig.actividad.nombre} para el próximo mes se encuentra pagada.'
        })

    if not resultados_mensualidad:
        resultados_mensualidad.append({
            'actividad': None,
            'estado': 'sin_mensualidad',
            'mensaje': 'Usted no posee ninguna mensualidad vigente. Puede solicitar su mensualidad desde el cronograma.'
        })
    cantidad_no_leidas=Notificacion.objects.filter(usuario=request.user,leida=False).count()

    context = {
        'pagos': pagos,
        'resultados_mensualidad': resultados_mensualidad,
        "cantidad_no_leidas":cantidad_no_leidas,
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
    
    suspendida = False
    motivo_suspension = ''

    if fecha_str:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        clase_finalizada=fecha<date.today()
        cupos = clase.cupos_para_fecha(fecha)
        cantidad_inscriptos=Reserva.objects.filter(
            fecha_clase=fecha,
            clase__horario=clase.horario,
            clase__actividad=clase.actividad,
            en_lista_de_espera=False,
        ).count()
        if request.user.is_authenticated:
            reserva_user = Reserva.objects.filter(
                usuario=request.user,
                fecha_clase=fecha,
                clase__horario=clase.horario,
                clase__actividad=clase.actividad,
            ).first()
            if reserva_user:
                ya_inscripto = True
                en_espera = reserva_user.en_lista_de_espera

            # Mensualidad mes actual
            mensualidad_mes_actual = Mensualidad.objects.filter(
                usuario=request.user,
                clase=clase,
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
                    clase=clase,
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
            ).exclude(clase__actividad=clase.actividad).select_related('clase__actividad').first()

            if reserva_choque:
                actividad_choque_nombre = reserva_choque.clase.actividad.nombre
                choque_horario = True

        suspension = SuspensionClase.objects.filter(clase=clase, fecha=fecha).first()
        if suspension:
            suspendida = True
            motivo_suspension = suspension.get_motivo_display()
            if suspension.otro_motivo:
                motivo_suspension += f' - {suspension.otro_motivo}'
    else:
        cupos = getattr(clase.actividad, 'capacidad_maxima', 30)

    # Verificar si la mensualidad es viable (al menos una fecha con cupo en el mes)
    mensualidad_viable = True
    mensualidad_mensaje = None
    if fecha_str and request.user.is_authenticated and not ya_mensualizado:
        dia_semana = fecha.weekday()
        mes = fecha.month
        anio = fecha.year
        hoy = date.today()
        dia_inicio = hoy.day if (hoy.month == mes and hoy.year == anio) else 1
        _, ultimo_dia = monthrange(anio, mes)
        fechas_con_cupo = 0
        fechas_con_conflicto = 0
        for d in range(dia_inicio, ultimo_dia + 1):
            f = date(anio, mes, d)
            if f.weekday() == dia_semana:
                if f == hoy:
                    clase_datetime = timezone.make_aware(
                        timezone.datetime.combine(f, clase.horario)
                    )
                    if timezone.now() > clase_datetime:
                        continue
                if Reserva.objects.filter(
                    usuario=request.user,
                    fecha_clase=f,
                    clase__horario=clase.horario,
                    en_lista_de_espera=False
                ).exclude(clase__actividad=clase.actividad).exists():
                    fechas_con_conflicto += 1
                    continue
                if clase.cupos_para_fecha(f) > 0:
                    fechas_con_cupo += 1
        if fechas_con_cupo == 0:
            mensualidad_viable = False
            if fechas_con_conflicto > 0:
                mensualidad_mensaje = (
                    f"No podés contratar la mensualidad de {clase.actividad.nombre} "
                    f"de los {clase.dia_semana_plural.lower()} a las {clase.horario.strftime('%H:%M')} hs "
                    f"porque ya tenés reservas en otra actividad que se superponen en el mismo horario."
                )
            else:
                mensualidad_mensaje = (
                    f"No hay cupos disponibles para ninguna de las clases "
                    f"de {clase.actividad.nombre} de los {clase.dia_semana_plural.lower()} "
                    f"a las {clase.horario.strftime('%H:%M')} hs de este mes."
                )

        # Check: otra mensualidad en el mismo horario/día de la semana
        if mensualidad_viable:
            otras_mensualidades = Mensualidad.objects.filter(
                usuario=request.user, mes=mes, anio=anio,
                estado='pagada', clase__horario=clase.horario,
            ).exclude(actividad=clase.actividad).select_related('clase')

            if any(m.clase and m.clase.fecha.weekday() == dia_semana for m in otras_mensualidades):
                mensualidad_viable = False
                mensualidad_mensaje = (
                    f"Ya tenés una mensualidad activa de otra actividad los "
                    f"{clase.dia_semana_plural.lower()} a las {clase.horario.strftime('%H:%M')} hs. "
                    f"No podés contratar otra mensualidad en el mismo horario."
                )

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
        'cupos_disponibles': (
            cantidad_inscriptos if es_admin and clase_finalizada else cupos
        ),
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
        'apto_vigente': (True if request.user.rol != 'cliente' else request.user.tiene_apto_vigente()) if request.user.is_authenticated else False,
        'es_admin':es_admin,
        'suspendida': suspendida,
        'motivo_suspension': motivo_suspension,
        'clase_finalizada':clase_finalizada if fecha_str else False,
        'mensualidad_viable': mensualidad_viable,
        'mensualidad_mensaje': mensualidad_mensaje,
        'tiene_penalizacion_individual': request.user.penalizacion_pendiente_individual,
        'tiene_penalizacion_mensual': request.user.penalizacion_pendiente_mensual,
    }
    return JsonResponse(data)