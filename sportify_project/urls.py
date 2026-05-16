from django.contrib import admin
from django.urls import include, path
from django.shortcuts import render


def minimal_login_view(request):
    return render(request, 'login.html')


def register_view(request):
    return render(request, 'register.html')


urlpatterns = [

   path('admin/', admin.site.urls),
   path('', include('gestion.urls')), # Tus vistas de actividades siguen en /gestion/
    path('', include('usuarios.urls')),
]
