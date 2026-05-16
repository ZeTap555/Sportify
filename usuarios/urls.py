from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'), # Ruta raíz para el login
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
]