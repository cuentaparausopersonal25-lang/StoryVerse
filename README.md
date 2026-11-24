# RUBEN ASADOR

Proyecto Flask para una web de servicios de asador para eventos.

## Ejecutar en Windows
1. Instalar Python.
2. Abrir CMD dentro de esta carpeta.
3. Ejecutar: `py -m venv venv`
4. Activar: `venv\\Scripts\\activate`
5. Instalar: `py -m pip install -r requirements.txt`
6. Configurar variables de entorno (ver abajo).
7. Ejecutar: `py app.py`
8. Abrir http://127.0.0.1:5000

## Variables privadas necesarias
No publiques estos valores en GitHub:
- `SECRET_KEY`: cadena aleatoria larga.
- `ADMIN_USERNAME`: nombre de usuario elegido.
- `ADMIN_PASSWORD_HASH`: hash generado para tu contraseña.

Para generar el hash, ejecutá en CMD:
`py -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('TU_CONTRASEÑA'))"`
Copiá el resultado como valor de `ADMIN_PASSWORD_HASH`. Reemplazá TU_CONTRASEÑA por una contraseña propia y no compartas el hash.

En Windows, antes de iniciar la app, podés definir variables en CMD:
`set SECRET_KEY=una-clave-larga-y-aleatoria`
`set ADMIN_USERNAME=tu_usuario`
`set ADMIN_PASSWORD_HASH=pega_aqui_el_hash`

## Render
Build Command: `pip install -r requirements.txt`
Start Command: `gunicorn app:app`

Configurá en Render las variables SECRET_KEY, ADMIN_USERNAME y ADMIN_PASSWORD_HASH.
Para que las fotos y la base de datos sobrevivan reinicios y nuevos deploys, configurá almacenamiento persistente en Render y definí:
- `DATA_DIR=/var/data`
- `UPLOAD_FOLDER=/var/data/uploads`
- `DATABASE_PATH=/var/data/ruben_asador.db`

Importante: el disco persistente de Render puede tener costo según el plan vigente. Sin almacenamiento persistente externo, los archivos guardados en el sistema local del servicio gratuito pueden perderse al reiniciar o desplegar. No subas contraseñas ni claves al repositorio.

## Rutas
- Pública: `/`
- Login privado: `/admin/login`
- Panel: `/admin`

No existe registro público de administradores. El acceso se habilita únicamente con las variables privadas del propietario.
