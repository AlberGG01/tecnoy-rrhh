import os
import sys
import subprocess
import ctypes
import tempfile
import shutil
import urllib.request


REPO_URL = "https://github.com/AlberGG01/tecnoy-rrhh.git"


def refresh_path():
    """Recarga PATH del registro de Windows en el proceso actual."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment') as k:
            system_path = winreg.QueryValueEx(k, 'PATH')[0]
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment') as k:
                user_path = winreg.QueryValueEx(k, 'PATH')[0]
        except FileNotFoundError:
            user_path = ''
        os.environ['PATH'] = system_path + ';' + user_path
    except Exception:
        pass


def ensure_python():
    print("\n" + "="*60)
    print("  PRE-REQUISITO: PYTHON")
    print("="*60)
    if shutil.which("python") or shutil.which("py"):
        print("[+] Python ya instalado.")
        return
    print("[*] Instalando Python 3.11...")
    url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    installer_path = os.path.join(tempfile.gettempdir(), "python-3.11.9-amd64.exe")
    urllib.request.urlretrieve(url, installer_path)
    subprocess.run(
        [installer_path, "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0"],
        check=True
    )
    refresh_path()
    print("[+] Python instalado correctamente.")


def ensure_git(install_dir):
    print("\n" + "="*60)
    print("  PRE-REQUISITO: GIT")
    print("="*60)
    if shutil.which("git"):
        print("[+] Git ya instalado.")
        return
    print("[*] Instalando Git...")
    url = "https://github.com/git-for-windows/git/releases/download/v2.44.0.windows.1/Git-2.44.0-64-bit.exe"
    installer_path = os.path.join(tempfile.gettempdir(), "Git-2.44.0-64-bit.exe")
    urllib.request.urlretrieve(url, installer_path)
    subprocess.run([installer_path, "/VERYSILENT", "/NORESTART"], check=True)
    refresh_path()
    subprocess.run(["git", "init"], cwd=install_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", REPO_URL], cwd=install_dir, check=True)
    print("[+] Git instalado y repositorio vinculado.")


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def get_install_dir():
    """Directorio donde está el instalador = donde el usuario descomprimió el zip."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def configure_api_key(install_dir):
    print("\n" + "="*60)
    print("  PASO 1: CLAVE DE INTELIGENCIA ARTIFICIAL (OPENAI)")
    print("="*60)
    print("El sistema necesita tu API Key de OpenAI para funcionar.")
    print("Sin ella NO se pueden leer CVs, buscar candidatos ni generar")
    print("informes. La clave empieza siempre por 'sk-'.")
    print()
    print("  Donde obtenerla: https://platform.openai.com/api-keys")
    print("="*60)

    while True:
        api_key = input("\n[>] Introduce tu API KEY de OpenAI (sk-...): ").strip()
        if not api_key:
            print("[!] La clave no puede estar vacia. Intentalo de nuevo.")
            continue
        if not api_key.startswith("sk-"):
            print("[!] La clave debe empezar por 'sk-'. Comprueba que la has copiado completa.")
            retry = input("    ¿Quieres intentarlo de nuevo? (s/n): ").strip().lower()
            if retry == 'n':
                break
            continue
        break

    env_path = os.path.join(install_dir, ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"OPENAI_API_KEY={api_key}\n")
        f.write(f"BASE_DIR={install_dir}\n")

    if os.path.exists(env_path):
        print(f"[+] Clave guardada en {env_path}")
    else:
        print(f"[!] ADVERTENCIA: No se pudo verificar la escritura de {env_path}")


def setup_environment(install_dir):
    print("\n" + "="*60)
    print("  PASO 2: INSTALANDO DEPENDENCIAS")
    print("="*60)

    venv_dir = os.path.join(install_dir, "venv")

    python_cmd = "python"
    try:
        subprocess.run(["python", "--version"], capture_output=True, check=True)
    except Exception:
        python_cmd = "py"

    if not os.path.exists(venv_dir):
        print("[*] Creando entorno virtual...")
        subprocess.run([python_cmd, "-m", "venv", "venv"], cwd=install_dir, check=True)
    else:
        print("[*] Entorno virtual ya existe, reutilizando.")

    pip_exe = os.path.join(venv_dir, "Scripts", "pip.exe")
    print("[*] Instalando paquetes (esto puede tardar varios minutos)...")
    subprocess.run([pip_exe, "install", "-U", "pip"], cwd=install_dir, stdout=subprocess.DEVNULL)
    subprocess.run([pip_exe, "install", "-r", "requirements.txt"], cwd=install_dir, check=True)
    print("[+] Dependencias instaladas correctamente.")


def configure_task_scheduler(install_dir):
    print("\n" + "="*60)
    print("  PASO 3: AUTOMATIZACION SEMANAL")
    print("="*60)
    print("[*] Programando escaner de CVs cada lunes a las 08:00 AM...")

    python_exe = os.path.join(install_dir, "venv", "Scripts", "python.exe")
    script_path = os.path.join(install_dir, "batch_weekly.py")

    cmd = (
        f'schtasks /create /tn "RRHH_Procesamiento_CVs_Semanal"'
        f' /tr "\\"{python_exe}\\" \\"{script_path}\\""'
        f' /sc weekly /d MON /st 08:00 /f'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[!] Aviso al crear tarea programada: {result.stderr.strip()}")
    else:
        print("[+] Tarea programada creada: cada lunes a las 08:00.")


def create_shortcuts(install_dir):
    print("\n" + "="*60)
    print("  PASO 4: ACCESO DIRECTO EN EL ESCRITORIO")
    print("="*60)

    bat_path = os.path.join(install_dir, "Lanzar_RRHH.bat")
    print(f"[*] Escribiendo {bat_path}...")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write('cd /d "%~dp0"\n')
        f.write("call venv\\Scripts\\activate.bat\n")
        f.write("echo Iniciando Centro de Recursos Humanos...\n")
        f.write("streamlit run hr_search_app.py\n")

    if not os.path.exists(bat_path):
        print(f"[!] ERROR: No se pudo crear {bat_path}. Abortando acceso directo.")
        return

    vbs_path = os.path.join(tempfile.gettempdir(), "create_shortcut.vbs")
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write('Set oWS = WScript.CreateObject("WScript.Shell")\n')
        f.write('sLinkFile = oWS.SpecialFolders("Desktop") & "\\RRHH Tecnoy.lnk"\n')
        f.write('Set oLink = oWS.CreateShortcut(sLinkFile)\n')
        f.write(f'oLink.TargetPath = "{bat_path}"\n')
        f.write(f'oLink.WorkingDirectory = "{install_dir}"\n')
        f.write('oLink.Description = "Sistema Inteligente de Seleccion TECNOY"\n')
        f.write('oLink.Save\n')

    result = subprocess.run(["cscript", "//nologo", vbs_path], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[!] Error creando acceso directo: {result.stderr}")
    else:
        print("[+] Acceso directo 'RRHH Tecnoy' creado en el Escritorio.")


def main():
    if not is_admin():
        print("Solicitando permisos de Administrador...")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()

    install_dir = get_install_dir()

    print("="*60)
    print("   INSTALADOR - SISTEMA RRHH TECNOY")
    print("="*60)
    print(f"Directorio de instalacion: {install_dir}")
    print()

    # Verificar que los archivos clave están presentes
    required = ["hr_search_app.py", "requirements.txt", "batch_weekly.py"]
    missing = [f for f in required if not os.path.exists(os.path.join(install_dir, f))]
    if missing:
        print(f"[!] ERROR: Faltan archivos necesarios en {install_dir}:")
        for m in missing:
            print(f"    - {m}")
        print("\nAsegurate de ejecutar el instalador desde la carpeta donde")
        print("descomprimiste el zip del sistema.")
        input("\nPresiona ENTER para salir...")
        sys.exit(1)

    try:
        ensure_python()
        ensure_git(install_dir)

        # Crear carpetas necesarias si no existen
        for folder in ["NUEVOS_INGRESOS", "logs"]:
            folder_path = os.path.join(install_dir, folder)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
                print(f"[+] Carpeta creada: {folder_path}")

        configure_api_key(install_dir)
        setup_environment(install_dir)
        configure_task_scheduler(install_dir)
        create_shortcuts(install_dir)

        print("\n" + "="*60)
        print("   INSTALACION COMPLETADA")
        print("="*60)
        print(f"1. Sistema instalado en: {install_dir}")
        print(f"2. Escaner automatico: cada lunes a las 08:00 AM")
        print(f"   lee la carpeta: {os.path.join(install_dir, 'NUEVOS_INGRESOS')}")
        print(f"3. Icono 'RRHH Tecnoy' creado en el Escritorio")
        print(f"4. Master Files generados en:")
        print(f"   {os.path.join(install_dir, 'TECNOY-Seleccion RRHH', 'MK File Tecnoy')}")
        print("\nPuedes cerrar esta ventana.")
        input("Presiona ENTER para salir...")

    except Exception as e:
        print(f"\n[!] Error critico durante la instalacion: {e}")
        import traceback
        traceback.print_exc()
        input("Presiona ENTER para salir...")


if __name__ == "__main__":
    main()
