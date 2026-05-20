import calendar
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from django.shortcuts import render, redirect 
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.hashers import make_password
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

def panel_admin(request):
    if not request.user.is_authenticated or request.user.rol != 'admin':
        return redirect('login')

    ahora = date.today()
    pestania_activa = 'clases'  # Por defecto abre la de clases

    if request.method == 'POST':
        action = request.POST.get('action')

        # --- A. PROCESAR NUEVA ACTIVIDAD (Ignora Mayúsculas y Minúsculas) ---
        if action == 'crear_actividad':
            pestania_activa = 'clases'
            nombre = request.POST.get('nombre')
            
            if nombre:
                nombre_limpio = nombre.strip() 
                if Actividad.objects.filter(nombre__iexact=nombre_limpio).exists():
                    messages.error(request, "Error: La actividad ya se encuentra registrada en el sistema (ya existe con ese nombre).")
                else:
                    Actividad.objects.create(nombre=nombre_limpio.capitalize())
                    messages.success(request, f"Actividad '{nombre_limpio.capitalize()}' creada con éxito.")
            else:
                messages.error(request, "El nombre de la actividad no puede estar vacío.")

        # --- B. PROCESAR PROGRAMAR CLASE (Validación recursiva infinita) ---
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
                # Convertimos el string a un objeto date real para calcular su día de la semana
                fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                dia_semana_nuevo = fecha_obj.weekday()

                # Buscamos colisiones: clases de la misma actividad a la misma hora
                colision = Clase.objects.filter(
                    actividad_id=actividad_id,
                    horario=horario_str
                )

                ya_existe_choque = False
                for c in colision:
                    # Comparamos usando la nueva propiedad matemática del modelo
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