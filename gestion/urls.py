# gestion/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Tu vista de la grilla que arreglamos antes
    path('grilla/', views.grilla_actividades, name='grilla_actividades'),
    
    # Si ya tenías la vista de crear actividad, deserializá esta línea:
    # path('actividad/nueva/', views.crear_actividad, name='crear_actividad'),
]