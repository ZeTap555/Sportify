from django.shortcuts import render, redirect 
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Actividad, Clase

# 1. LA GRILLA REAL (Trae los datos que guardás en la BD)
def grilla_actividades(request):
    # select_related se usa por buena práctica para traer el nombre de la actividad de un solo viaje
    clases_reales = Clase.objects.all().select_related('actividad').order_by('horario')
    return render(request, 'grilla.html', {'clases': clases_reales})


# 2. CREAR ACTIVIDAD (Sigue igual, validando que no se duplique)
def crear_actividad(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre').strip()

        if Actividad.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, "No se puede hacer una actividad que ya existe.")
        else:
            Actividad.objects.create(nombre=nombre)
            messages.success(request, f"Actividad '{nombre}' creada con éxito.")
            return redirect('crear_actividad')

    return render(request, 'crear_actividad.html')


# 3. CREAR CLASE (Valida en punto y colisiones de horarios)
def crear_clase(request):
    actividades = Actividad.objects.all()
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']

    if request.method == 'POST':
        actividad_id = request.POST.get('actividad')
        horario_str = request.POST.get('horario') 
        dia_semana = request.POST.get('dia_semana')

        # Validación: Horario en punto
        if horario_str:
            horas, minutos = horario_str.split(':')
            if minutos != '00':
                messages.error(request, "No se puede crear una clase que no comienze en punto (ej: 18:00, 19:00).")
                return render(request, 'crear_clase.html', {'actividades': actividades, 'dias': dias})
        else:
            messages.error(request, "Por favor, seleccione un horario.")
            return render(request, 'crear_clase.html', {'actividades': actividades, 'dias': dias})

        # Validación: Evitar choques en el cronograma
        colision = Clase.objects.filter(
            actividad_id=actividad_id,
            dia_semana=dia_semana,
            horario=horario_str
        ).exists()

        if colision:
            messages.error(request, "Ya existe una clase de esa actividad en ese mismo día y horario.")
        else:
            actividad_instancia = Actividad.objects.get(id=actividad_id)
            Clase.objects.create(
                actividad=actividad_instancia,
                horario=horario_str,
                dia_semana=dia_semana
            )
            messages.success(request, "Clase añadida al cronograma con éxito.")
            return redirect('grilla_actividades') # Te manda directo a la grilla para ver el cambio

    return render(request, 'crear_clase.html', {'actividades': actividades, 'dias': dias})
@login_required
def panel_admin_view(request):
    # CUIDADO: Si no es admin, lo mandamos derecho al home (grilla)
    if request.user.rol != 'admin':
        return redirect('grilla_actividades')
        
    return render(request, 'panel_admin.html')