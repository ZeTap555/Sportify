import calendar
from datetime import datetime, date
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
from django.contrib.auth.decorators import login_required

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

        if tipo_pago not in ('senia', 'total'):
            return redirect('grilla_actividades')

        if medio_pago not in ('Tarjeta', 'Mercado Pago'):
            return redirect('grilla_actividades')

        # Ya inscripto en esta fecha
        if Reserva.objects.filter(usuario=request.user, clase=clase, fecha_clase=fecha_clase).exists():
            return redirect('grilla_actividades')

        # Sin cupo -> lista de espera
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

        # Calcular monto
        precio = clase.actividad.precio_clase
        if tipo_pago == 'senia':
            monto = precio * Decimal('0.50')
        else:
            monto = precio

        # Guardar en sesión para el próximo paso
        request.session['inscripcion_pendiente'] = {
            'clase_id': clase.id,
            'fecha_clase': fecha_clase_str,
            'tipo_pago': tipo_pago,
            'monto': str(monto),
            'medio_pago': medio_pago,
        }

        if medio_pago == 'Tarjeta':
            return redirect('pago_tarjeta')
        else:
            return redirect('pago_mercadopago')

    return redirect('grilla_actividades')


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

    return render(request, 'pago_tarjeta.html', {'monto': datos['monto']})


@login_required
def pago_mercadopago(request):
    datos = request.session.get('inscripcion_pendiente')
    if not datos:
        return redirect('grilla_actividades')

    clase = get_object_or_404(Clase, id=datos['clase_id'])

    # Simular redirección a MP - en producción usar SDK mercadopago
    with transaction.atomic():
        reserva = Reserva.objects.create(
            usuario=request.user,
            clase=clase,
            fecha_clase=datos['fecha_clase'],
            monto_pagado=datos['monto'],
            estado_pago='seña' if datos['tipo_pago'] == 'senia' else 'total',
            medio_pago='Mercado Pago',
        )

    enviar_confirmacion(request.user, clase, reserva)
    del request.session['inscripcion_pendiente']
    return redirect('pago_confirmacion', reserva_id=reserva.id)


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
    data = {
        'id': clase.id,
        'actividad': clase.actividad.nombre,
        'actividad_id': clase.actividad.id,
        'fecha': fecha_str or clase.fecha.strftime('%d/%m/%Y'),
        'horario': clase.horario.strftime('%H:%M'),
        'profesor': f"{clase.profesor.nombre} {clase.profesor.apellido}" if clase.profesor else None,
        'cupos_disponibles': cupos,
        'precio_clase': float(clase.actividad.precio_clase),
        'precio_mensualidad': float(clase.actividad.precio_mensualidad),
        'logueado': request.user.is_authenticated,
        'ya_inscripto': ya_inscripto,
        'en_espera': en_espera,
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

        # --- B. PROCESAR PROGRAMAR CLASE ---
        elif action == 'crear_clase':
            pestania_activa = 'clases'
            actividad_id = request.POST.get('actividad')
            profesor_id = request.POST.get('profesor')
            fecha_str = request.POST.get('fecha')
            horario_str = request.POST.get('horario')

            if horario_str and not horario_str.endswith(':00'):
                messages.error(request, "Error: Las clases deben comenzar en punto (Ej: 19:00).")
            elif not fecha_str or not actividad_id:
                messages.error(request, "Por favor, complete todos los campos obligatorios.")
            else:
                fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                dia_semana_nuevo = fecha_obj.weekday()

                colision = Clase.objects.filter(
                    actividad_id=actividad_id,
                    horario=horario_str
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
                    profesor = None
                    if profesor_id and profesor_id != "":
                        profesor = Profesor.objects.get(id=profesor_id)

                    Clase.objects.create(
                        actividad=actividad,
                        profesor=profesor,
                        fecha=fecha_obj,
                        horario=horario_str
                    )
                    messages.success(request, "Clases creadas con éxito.")

        # --- C. PROCESAR REGISTRAR PROFESOR (¡Ahora bien tabulado!) ---
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
                        usuario=user,                # El enlace OneToOne que agregamos
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
        """"
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
                        email=correo,
                        first_name=nombre,
                        last_name=apellido,
                        rol='profesor',
                        password=make_password(contrasenia)
                    )
                    Profesor.objects.create(
                        nombre=nombre,
                        apellido=apellido,
                        dni=dni,
                        telefono=telefono,
                        correo=correo
                    )
                    messages.success(request, f"Profesor {apellido}, {nombre} dado de alta con éxito.")
            except Exception as e:
                messages.error(request, f"Error en los datos: {e}")
"""

    # --- GENERACIÓN DEL CONTEXTO (GET) (Corregido para repetición infinita) ---
    año = int(request.GET.get('anio', ahora.year))
    mes = int(request.GET.get('mes', ahora.month))
    
    # Traemos todos los moldes de clases del sistema sin importar el mes
    todas_las_clases = Clase.objects.all()

    cal = calendar.Calendar(firstweekday=0)
    semanas_matriz = cal.monthdayscalendar(año, mes)
    meses_nombres = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    # 🧠 MACHACADO MATEMÁTICO: Mapeamos qué clases fijas caen en cada casillero del mini calendario
    clases_por_dia = {}
    for semana in semanas_matriz:
        for dia in semana:
            if dia != 0:
                fecha_casillero = date(año, mes, dia)
                dia_semana_casillero = fecha_casillero.weekday() # 0=Lunes, 1=Martes, etc.
                
                clases_por_dia[dia] = []
                for clase in todas_las_clases:
                    # Se dibuja si coincide el día de la semana y el casillero no es anterior a su fecha de inicio
                    if clase.dia_semana_num == dia_semana_casillero and fecha_casillero >= clase.fecha:
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