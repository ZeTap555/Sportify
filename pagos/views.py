from django.shortcuts import render
from .models import Notificacion

@login_required
def ver_notificaciones(request):
    notificaciones=Notificacion.objects.filter(usuario=request.user).order_by('-fecha')
    return render(request, 'gestion/notificaciones.html', {'notificaciones': notificaciones})
