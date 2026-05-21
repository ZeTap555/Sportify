from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Usuario
from datetime import date
from django.core.mail import send_mail, EmailMultiAlternatives
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.conf import settings
import uuid

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
            errores['general'] = 'Se deben ingresar todos los datos.'
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
            errores['general'] = 'Error en el registro. Verifique los datos ingresados.'
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

            return redirect('/login/?success=register')

        except Exception as e:
            print(f"\n❌ ERROR CRÍTICO EN REGISTRO: {e}\n")
            errores['general'] = f'Error al registrar: {e}'

    return render(request, 'register.html', {'errores': errores})

def login_view(request):
    mensaje_exito=None
    if request.GET.get('success')=='password-reset':
        mensaje_exito=(
            'Contraseña reestablecida con éxito'
        )
    elif request.GET.get('success')=='register':
        mensaje_exito='Registro exitoso. Ahora puedes iniciar sesión.'

        

    error = None

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
            error = "DNI o contraseña incorrectos."

    return render(
        request, 
        'login.html',
        {
            'mensaje_exito': mensaje_exito,
            'error': error,
        }
    )

def logout_view(request):
    logout(request)
    return redirect('login')

def forgot_password_view(request):

 errores = {}

 mensaje_exito = None

 if request.method == 'POST':

     email = request.POST.get(
         'email',
         ''
     ).strip()

     # =========================
     # VALIDAR FORMATO
     # =========================

     try:

         validate_email(email)

     except ValidationError:

         errores['email'] = (
             'Por favor, ingrese un mail válido.'
         )

     # =========================
     # VALIDAR EXISTENCIA
     # =========================

     if not errores:
 
         if not Usuario.objects.filter(
             email=email
         ).exists():

             errores['email'] = (
                 'Por favor, ingrese un mail asignado a una cuenta.'
             )

     # =========================
     # GENERAR TOKEN
     # =========================

     if not errores:

         user = Usuario.objects.get(
             email=email
         )

         token = str(
             uuid.uuid4()
         )

         user.reset_token = token

         user.save()

         reset_link = (
             f'http://127.0.0.1:8000/reset-password/{token}/'
         )

         # =========================
         # MAIL
         # =========================

         asunto = (
             'Recuperación de contraseña - Sportify'
         )

         mensaje_texto = f'''
 

 Recibimos una solicitud para recuperar tu contraseña.

 Ingresá al siguiente enlace:

 {reset_link}
 '''
         mensaje_html = f'''

 <div style="
     background-color:#000000;
     padding:40px;
     font-family:Poppins,sans-serif;
     text-align:center;
  ">

  <h1 style="
      color:#00ff88;
      margin-bottom:10px;
 ">
     SPORTIFY
 </h1>

 <h2 style="
     color:white;
     margin-bottom:25px;
 ">
     Recuperación de contraseña
 </h2>

 <p style="
     color:#cccccc;
     margin-bottom:35px;
     font-size:15px;
 ">
     Recibimos una solicitud para recuperar tu contraseña.
 </p>

 <a
     href="{reset_link}"
     style="
         background-color:#00ff88;
         color:black;
         padding:14px 28px;
         border-radius:10px;
         text-decoration:none;
         font-weight:700;
         display:inline-block;
         font-size:15px;
     "
 >
     Cambiar contraseña
 </a>

 <p style="
     color:#777777;
     margin-top:35px;
     font-size:13px;
 ">
     Si no realizaste esta solicitud,
     puedes ignorar este correo.
 </p>


 </div>
 '''



         email_message = EmailMultiAlternatives(
             asunto,
             mensaje_texto,
             settings.EMAIL_HOST_USER,
             [email]
         )

         email_message.attach_alternative(
             mensaje_html,
             "text/html"
         )

         email_message.send()

         mensaje_exito = (
             'Se ha enviado un correo para el cambio de contraseña. Por favor, revise su casilla'
         )

 return render(
     request,
     'forgot_password.html',
     {
         'errores': errores,
         'mensaje_exito': mensaje_exito
     }
 )


def reset_password_view(request, token):

 errores = {}

 try:

     user = Usuario.objects.get(
         reset_token=token
     )

 except Usuario.DoesNotExist:

     return render(
         request,
         'reset_password_invalid.html'
     )

 if request.method == 'POST':
     print("ENTRO AL POST")

     password = request.POST.get(
         'password',
         ''
     )

     confirmar = request.POST.get(
         'confirmar_password',
         ''
     )

     # VALIDAR COINCIDENCIA

     if password != confirmar:

         errores['password'] = (
             'Las contraseñas no coinciden'
         )

     # GUARDAR PASSWORD

     if not errores:
         print("Entro al guardado")

         user.set_password(password )
         user.save(update_fields=['password'])
        

         # INVALIDAR TOKEN

         user.reset_token = None

         user.save(update_fields=['reset_token'])

        
         logout(request)

         return redirect( '/login/?success=password-reset' )

 return render(
     request,
     'reset_password.html',
     {
         'errores': errores
     }
 )

@login_required
def perfil_view(request):

    return render(
        request,
        'perfil.html'
    )

@login_required
def editar_perfil_view(request):

    user = request.user

    errores = {}

    if request.method == 'POST':

        email = request.POST.get('email', '').strip()

        telefono = request.POST.get('telefono', '').strip()

        fecha_nacimiento_str = request.POST.get(
            'fecha_nacimiento',
            ''
        ).strip()

        password_actual = request.POST.get(
            'password_actual',
            ''
        )

        password_nueva = request.POST.get(
            'password_nueva',
            ''
        )

        # =========================
        # VALIDAR EMAIL DUPLICADO
        # =========================

        if Usuario.objects.filter(email=email).exclude(id=user.id).exists():

            errores['email'] = (
                'Modificación sin éxito - '
                'Email ya asociado a otra cuenta'
            )

        # =========================
        # VALIDAR MAYOR DE 16
        # =========================

        try:

            dia, mes, anio = fecha_nacimiento_str.split('/')

            fecha_nacimiento = date(
                int(anio),
                int(mes),
                int(dia)
            )

            hoy = date.today()

            edad = (
                hoy.year - fecha_nacimiento.year
                -
                (
                    (hoy.month, hoy.day)
                    <
                    (
                        fecha_nacimiento.month,
                        fecha_nacimiento.day
                    )
                )
            )

            if edad < 16:

                errores['fecha_nacimiento'] = (
                    'Modificación fallida - '
                    'El usuario debe ser mayor a 16 años'
                )

        except ValueError:

            errores['fecha_nacimiento'] = (
                'Fecha inválida'
            )

        # =========================
        # VALIDAR PASSWORD
        # =========================

        if password_nueva:

            if not user.check_password(password_actual):

                errores['password'] = (
                    'Contraseña incorrecta - '
                    'Volver a intentar'
                )

        # =========================
        # SI HAY ERRORES
        # =========================

        if errores:

            return render(
                request,
                'editar_perfil.html',
                {
                    'errores': errores
                }
            )

        # =========================
        # GUARDAR CAMBIOS
        # =========================

        user.email = email

        user.telefono = telefono

        user.fecha_nacimiento = fecha_nacimiento

        if password_nueva:

            user.set_password(password_nueva)

        user.save()

        messages.success(
            request,
            'Modificación exitosa'
        )

        # IMPORTANTE:
        # vuelve a loguear al usuario
        # despues de cambiar password

        login(request, user)

        return redirect('perfil')

    return render(
        request,
        'editar_perfil.html'
    )