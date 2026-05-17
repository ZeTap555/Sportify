from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import Usuario
from datetime import date

def register_view(request):
    errores = {}

    if request.method == 'POST':
        nombre = request.POST.get('nombre_apellido', '').strip()
        dni = request.POST.get('dni', '').strip()
        fecha_nac_str = request.POST.get('fecha_nacimiento', '').strip()
        tel = request.POST.get('telefono', '').strip()
        email = request.POST.get('email', '').strip()
        passw = request.POST.get('password', '')
        apta = request.FILES.get('apta_medica')

        # Validación: campos requeridos completos
        if not nombre or not dni or not fecha_nac_str or not email or not passw:
            messages.error(request, "Se deben ingresar todos los datos.")
            return render(request, 'register.html', {'errores': errores})

        # Validación: DNI único
        if Usuario.objects.filter(dni=dni).exists():
            errores['dni'] = "Ya existe Usuario con este DNI."

        # Validación: email único
        if Usuario.objects.filter(email=email).exists():
            errores['email'] = "Ya existe usuario con ese email."

        # Validación: mayor de 16 años
        try:
            dia, mes, anio = fecha_nac_str.split('/')
            fecha_nac = date(int(anio), int(mes), int(dia))
            hoy = date.today()
            edad = hoy.year - fecha_nac.year - ((hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day))
            if edad < 16:
                errores['fecha_nacimiento'] = "Debe ser mayor de 16 años para registrarse."
        except (ValueError, IndexError):
            errores['fecha_nacimiento'] = "Fecha de nacimiento inválida."

        # Validación: apta médica adjunta
        if not apta:
            errores['apta_medica'] = "Debe adjuntar el apta médica para continuar con el registro."

        # Si hay errores, mostrar mensaje general y devolver
        if errores:
            messages.error(request, "Error en el registro. Verifique los datos ingresados.")
            return render(request, 'register.html', {'errores': errores})

        # Creamos el usuario
        try:
            user = Usuario.objects.create_user(
                username=dni,
                dni=dni,
                email=email,
                password=passw,
                first_name=nombre
            )

            user.telefono = tel
            user.fecha_nacimiento = fecha_nac
            user.apta_medica = apta
            user.save()

            messages.success(request, "Registro exitoso. Ahora puedes iniciar sesión.")
            return redirect('login')

        except Exception as e:
            print(f"\n❌ ERROR CRÍTICO EN REGISTRO: {e}\n")
            messages.error(request, f"Error al registrar: {e}")

    return render(request, 'register.html', {'errores': errores})

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