# gestion/urls.py
from django.urls import path
from . import views


urlpatterns = [
    path('', views.grilla_actividades, name='grilla_actividades'), # <-- ¡AHORA ES EL HOME! (vacío)
    path('actividad/nueva/', views.crear_actividad, name='crear_actividad'),
    path('clase/nueva/', views.crear_clase, name='crear_clase'),
]