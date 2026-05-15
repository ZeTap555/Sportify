from django.contrib import admin
from django.urls import path
from django.shortcuts import render


def minimal_login_view(request):
    return render(request, 'login.html')


def register_view(request):
    return render(request, 'register.html')


urlpatterns = [

    path('admin/', admin.site.urls),

    path('', minimal_login_view, name='login'),

    path('register/', register_view, name='register'),

]