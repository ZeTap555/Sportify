from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import Usuario  # Importamos tu modelo personalizado
from django.contrib.auth.decorators import login_required

def register_view(request):
    if request.method == 'POST':
        # 1. Capturamos los datos del HTML
        nombre = request.POST.get('nombre_apellido')
        dni = request.POST.get('dni')
        fecha_nac = request.POST.get('fecha_nacimiento')
        tel = request.POST.get('telefono')
        email = request.POST.get('email')
        passw = request.POST.get('password')
        apta = request.FILES.get('apta_medica')

        # 2. Validación básica (CORREGIDO: quitamos el 'usuarios/')
        if Usuario.objects.filter(dni=dni).exists():
            messages.error(request, "Ya existe un usuario con ese DNI.")
            return render(request, 'register.html')

        # 3. Creamos el usuario
        try:
            # Le pasamos username=dni para solucionar el conflicto de AbstractUser
            user = Usuario.objects.create_user(
                username=dni, # <-- El salvavidas de Django
                dni=dni,
                email=email,
                password=passw,
                first_name=nombre
            )
            
            # 4. Guardamos los campos extra que no son de AbstractUser
            # user.telefono = tel
            # user.fecha_nacimiento = fecha_nac
            # user.apta_medica = apta
            # user.save()

            messages.success(request, "Registro exitoso. ¡Iniciá sesión!")
            return redirect('login')
            
        except Exception as e:
            # Si algo falla acá adentro, ahora lo vas a ver en la terminal negra
            print(f"\n❌ ERROR CRÍTICO EN REGISTRO: {e}\n")
            messages.error(request, f"Error al registrar: {e}")

    return render(request, 'register.html')

def login_view(request):
    if request.method == 'POST':
        dni_ingresado = request.POST.get('dni')
        pass_ingresada = request.POST.get('password')

        # authenticate busca por el USERNAME_FIELD, que en tu caso es el DNI
        user = authenticate(request, username=dni_ingresado, password=pass_ingresada)

        if user is not None:
            login(request, user)
            # Una vez logueado, lo mandamos a la grilla de actividades
            return redirect('grilla_actividades')
        else:
            messages.error(request, "DNI o contraseña incorrectos.")

    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('login')