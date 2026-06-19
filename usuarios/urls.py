from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),          # <-- Ahora es /login/
    path('register/', views.register_view, name='register'), # /register/
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('perfil/', views.perfil_view, name='perfil'),
    path('perfil/editar/',views.editar_perfil_view,name='editar_perfil'),
    path('perfil/actualizar-apto/', views.actualizar_apto_medico_view, name='actualizar_apto_medico'),path('perfil/actualizar-apto/', views.actualizar_apto_medico_view, name='actualizar_apto_medico'),
    path('reset-password/<str:token>/',views.reset_password_view,name='reset_password'),

]