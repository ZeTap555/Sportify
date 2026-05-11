from django.urls import path
from . import views

urlpatterns = [
    path('grilla/', views.grilla_actividades, name='grilla_actividades'),
]