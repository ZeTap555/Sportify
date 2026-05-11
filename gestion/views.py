from django.shortcuts import render
from .models import Clase

def grilla_actividades(request):
    # Traemos todas las clases y las pasamos al HTML
    clases = Clase.objects.all().order_by('hora')
    return render(request, 'gestion/grilla.html', {'clases': clases})