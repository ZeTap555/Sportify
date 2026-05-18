from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),          # <-- Ahora es /login/
    path('register/', views.register_view, name='register'), # /register/
    path('logout/', views.logout_view, name='logout'),
    path('perfil/', views.perfil_view, name='perfil'),
]