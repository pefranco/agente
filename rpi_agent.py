#pip install --user requests paramiko colorama
#!/usr/bin/env python3
import json
import getpass
import requests
import paramiko
import time
import re

# Colores y estilos (con fallback si no hay colorama)
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    CYAN = Fore.CYAN + Style.BRIGHT
    GREEN = Fore.GREEN + Style.BRIGHT
    YELLOW = Fore.YELLOW + Style.BRIGHT
    RED = Fore.RED + Style.BRIGHT
    MAGENTA = Fore.MAGENTA + Style.BRIGHT
    BLUE = Fore.BLUE + Style.BRIGHT
    WHITE = Fore.WHITE + Style.BRIGHT
    RESET = Style.RESET_ALL
except ImportError:
    CYAN = GREEN = YELLOW = RED = MAGENTA = BLUE = WHITE = RESET = ""


# ==========================
# CONFIGURACIÓN BÁSICA
# ==========================

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "deepseek-coder:6.7b"

# Datos de la Raspberry Pi
RPI_HOST = "192.168.1.96"
RPI_USER = "pfranco"

USE_SSH_KEY = False          # True = llave privada, False = password
SSH_KEY_PATH = r"C:\Users\opi\.ssh\id_ed25519"  # ruta a la clave si USE_SSH_KEY=True


# ==========================
# PROMPT DEL AGENTE
# ==========================

SYSTEM_PROMPT = """
Eres un asistente DevSecOps experto en Linux.

INSTRUCCIÓN CRÍTICA SOBRE EL FORMATO:
- Tu respuesta debe ser EXCLUSIVAMENTE un objeto JSON con esta estructura exacta:
{
  "command": "comando linux aquí",
  "explanation": "explicación breve en español",
  "dangerous": false
}

Tu única tarea:
- A partir de una instrucción del usuario, debes devolver UN SOLO comando Linux.
- NO escribas texto fuera del JSON.
- NO incluyas ningún otro campo como "output", "note", "warning", etc.
- NO incluyas explicaciones antes o después.
- NO uses código markdown, NO uses ```json, NO uses ```bash.
- NO des pasos ni recomendaciones.
- NO respondas "no puedo", ni "aquí hay pasos", ni nada fuera del JSON.
- Tu respuesta debe ser SOLO el JSON, nada más.
"""


# ==========================
# UTILIDADES DE FORMATO MEJORADAS - ESPAÑOL
# ==========================

def print_banner():
    """Banner más profesional y minimalista en español"""
    print(f"\n{BLUE}{'═' * 70}{RESET}")
    print(f"{BLUE}║{WHITE}{'🤖 AGENTE RASPBERRY PI':^68}{BLUE}║{RESET}")
    print(f"{BLUE}║{WHITE}{'Asistente Remoto DevOps':^68}{BLUE}║{RESET}")
    print(f"{BLUE}{'═' * 70}{RESET}")
    print(f"{CYAN}│ {WHITE}Modelo: {GREEN}{OLLAMA_MODEL:<40}{CYAN}│{RESET}")
    print(f"{CYAN}│ {WHITE}Objetivo: {GREEN}{RPI_USER}@{RPI_HOST:<37}{CYAN}│{RESET}")
    print(f"{CYAN}│ {WHITE}Autenticación: {GREEN}{'Clave SSH' if USE_SSH_KEY else 'Contraseña':<33}{CYAN}│{RESET}")
    print(f"{BLUE}{'═' * 70}{RESET}")
    print(f"{YELLOW}💡 Consejo: Escribe 'salir' para terminar | Usa comandos claros{RESET}\n")


def print_section(title: str, emoji: str = "📋"):
    """Secciones más limpias y profesionales en español"""
    print(f"\n{BLUE}┌{emoji} {WHITE}{title}{RESET}")
    print(f"{BLUE}│{RESET}")


def print_command_header(command: str):
    """Presentación elegante del comando a ejecutar"""
    print(f"\n{BLUE}┌{WHITE} EJECUCIÓN DE COMANDO {'─' * 45}{RESET}")
    print(f"{BLUE}│{GREEN} $ {command}{RESET}")
    print(f"{BLUE}│{RESET}")


def print_result_header():
    """Header para resultados"""
    print(f"{BLUE}├{WHITE} RESULTADOS DE EJECUCIÓN {'─' * 43}{RESET}")
    print(f"{BLUE}│{RESET}")


def print_footer(exit_code: int, execution_time: float):
    """Footer con estado de ejecución y tiempo"""
    status = f"{GREEN}ÉXITO" if exit_code == 0 else f"{RED}FALLÓ"
    tiempo = f"{execution_time:.2f}s"
    print(f"{BLUE}│{RESET}")
    print(f"{BLUE}└{WHITE} ESTADO: {status} {WHITE}(código: {exit_code}) | Tiempo: {tiempo}{' ' * 15}{RESET}")


def print_kv(label: str, value: str, color=WHITE, indent=0):
    """Líneas clave-valor mejoradas"""
    indent_str = "  " * indent
    print(f"{BLUE}│{RESET}{indent_str} {color}{label:<18}{RESET} {value}")


def print_info(message: str, emoji: str = "ℹ️ "):
    """Mensajes informativos"""
    print(f"{BLUE}│{RESET} {CYAN}{emoji} {message}{RESET}")


def print_warning(message: str):
    """Mensajes de advertencia"""
    print(f"{BLUE}│{RESET} {YELLOW}⚠  {message}{RESET}")


def print_error(message: str):
    """Mensajes de error"""
    print(f"{BLUE}│{RESET} {RED}✗ {message}{RESET}")


def print_success(message: str):
    """Mensajes de éxito"""
    print(f"{BLUE}│{RESET} {GREEN}✓ {message}{RESET}")


def extract_important_log_lines(log_content: str, max_lines: int = 15) -> list:
    """
    Extrae las líneas más importantes de un log, eliminando líneas repetitivas
    y manteniendo información crítica.
    """
    lines = log_content.strip().split('\n')
    
    # Filtrar líneas importantes (errores, advertencias, cambios de estado)
    important_lines = []
    seen_patterns = set()
    
    for line in lines:
        line_lower = line.lower()
        
        # Patrones importantes a mantener
        is_important = any([
            'error' in line_lower,
            'warn' in line_lower,
            'fail' in line_lower,
            'start' in line_lower,
            'stop' in line_lower,
            'status' in line_lower,
            'registered' in line_lower,
            'connection' in line_lower,
            'tunnel' in line_lower,
            'service' in line_lower,
            'active:' in line_lower,
            'main pid' in line_lower,
        ])
        
        # Evitar líneas muy repetitivas (logs de conexión continuos)
        is_repetitive = any([
            'curve preferences' in line_lower,
            'heartbeat' in line_lower,
        ])
        
        # Crear un patrón único para esta línea (primeras 40 chars)
        pattern = line[:40] if len(line) > 40 else line
        
        if is_important and not is_repetitive and pattern not in seen_patterns:
            important_lines.append(line)
            seen_patterns.add(pattern)
    
    # Si no hay líneas importantes, tomar las primeras y últimas
    if not important_lines and len(lines) > max_lines:
        return lines[:max_lines//2] + [f"{CYAN}... [{len(lines) - max_lines} líneas omitidas] ...{RESET}"] + lines[-(max_lines//2):]
    
    # Limitar el número de líneas
    if len(important_lines) > max_lines:
        return important_lines[:max_lines] + [f"{CYAN}... [{len(important_lines) - max_lines} líneas adicionales omitidas] ...{RESET}"]
    
    return important_lines


def print_output_block(content: str, title: str = "SALIDA", max_lines: int = 20, is_log: bool = False):
    """Bloque de output con procesamiento inteligente"""
    if not content.strip():
        return
    
    if is_log:
        # Para logs, usar extracción inteligente
        lines = extract_important_log_lines(content, max_lines)
    else:
        # Para output normal, usar truncamiento simple
        lines = content.strip().split('\n')
        if len(lines) > max_lines:
            lines = lines[:max_lines//2] + [f"{CYAN}... [{len(lines) - max_lines} líneas omitidas] ...{RESET}"] + lines[-(max_lines//2):]
    
    print(f"{BLUE}│{RESET}")
    print(f"{BLUE}│{WHITE} {title}:{RESET}")
    
    for line in lines:
        if isinstance(line, str) and line.startswith(f"{CYAN}... ["):
            print(f"{BLUE}│{RESET}   {line}")
        else:
            print(f"{BLUE}│{RESET}   {line}")


def user_prompt() -> str:
    """Prompt de usuario más profesional en español"""
    return input(f"\n{BLUE}➜{WHITE} ").strip()


def yes_no_prompt(msg: str, default_no: bool = True) -> bool:
    """Prompt de confirmación mejorado en español"""
    options = f"{WHITE}[{GREEN}s{RESET}/{WHITE}N]{RESET}" if default_no else f"{WHITE}[{GREEN}S{RESET}/{WHITE}n]{RESET}"
    ans = input(f"{BLUE}?{WHITE} {msg} {options}{WHITE} ➜ {RESET}").strip().lower()
    
    if default_no:
        return ans in ("s", "si", "sí", "y", "yes")
    else:
        return ans not in ("n", "no")


# ==========================
# FUNCIONES LÓGICAS MEJORADAS
# ==========================

def ask_ollama_for_command(user_request: str) -> dict:
    """Pide a Ollama que genere el comando a ejecutar."""

    def call_ollama(extra_system: str = "") -> str:
        system_msg = SYSTEM_PROMPT + extra_system
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": (
                        "Instrucción del usuario:\n"
                        f"{user_request}\n\n"
                        "Recuerda: debes devolver SOLO un JSON con la estructura indicada."
                    ),
                },
            ],
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()

    def try_parse(content: str) -> dict | None:
        # 1) buscar bloque entre <json>...</json>
        if "<json>" in content and "</json>" in content:
            start = content.find("<json>") + len("<json>")
            end = content.rfind("</json>")
            content = content[start:end].strip()

        # 2) quitar fences si trae accidentalmente ```
        if content.startswith("```"):
            lines = content.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        # 3) intento directo
        try:
            obj = json.loads(content)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        # 4) fallback: recortar el primer { y último }
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(content[start:end+1])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                return None

        return None

    # Primer intento
    content1 = call_ollama()
    cmd_obj = try_parse(content1)
    if cmd_obj is not None:
        return cmd_obj

    print_warning("Primer intento falló, contenido recibido:")
    print_output_block(content1, "RESPUESTA DEL MODELO")
    print_info("Reintentando con instrucciones más estrictas...")

    # Segundo intento, más estricto
    extra_system = """

ESTO ES CRÍTICO:
- Si devuelves algo que no sea EXACTAMENTE un JSON, el sistema fallará.
- No expliques nada fuera del JSON.
- No uses backticks ni bloques de código.
- No escribas pasos ni instrucciones humanas.
"""
    content2 = call_ollama(extra_system=extra_system)
    cmd_obj = try_parse(content2)
    if cmd_obj is not None:
        return cmd_obj

    print_error("Error al parsear JSON del modelo (segundo intento).")
    print_output_block(content2, "RESPUESTA DEL MODELO")
    raise ValueError("No se pudo parsear el JSON devuelto por el modelo")


def connect_ssh(password: str | None = None) -> paramiko.SSHClient:
    """Abre una conexión SSH a la Raspberry Pi."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if USE_SSH_KEY:
        print_info(f"Conectando a {RPI_USER}@{RPI_HOST} con clave SSH...")
        client.connect(
            RPI_HOST,
            username=RPI_USER,
            key_filename=SSH_KEY_PATH,
            look_for_keys=False,
            allow_agent=True,
        )
    else:
        print_info(f"Conectando a {RPI_USER}@{RPI_HOST} con contraseña...")
        if password is None:
            password = getpass.getpass(f"{BLUE}?{WHITE} Contraseña SSH ➜ {RESET}")
        client.connect(RPI_HOST, username=RPI_USER, password=password)

    print_success("Conexión SSH establecida")
    return client


def run_remote_command(client: paramiko.SSHClient, command: str) -> tuple[str, str, int, float]:
    """Ejecuta un comando en la Raspberry y devuelve stdout, stderr, código de salida y tiempo"""
    print_command_header(command)
    
    start_time = time.time()
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    exit_code = stdout.channel.recv_exit_status()
    execution_time = time.time() - start_time
    
    return out, err, exit_code, execution_time


def explain_output_with_ollama(command: str, stdout: str, stderr: str) -> str:
    """Pide a Ollama que explique el resultado del comando de manera más inteligente"""
    user_msg = f"""
He ejecutado el siguiente comando en una Raspberry Pi y necesito que analices los resultados:

COMANDO EJECUTADO:
{command}

SALIDA PRINCIPAL (STDOUT):
{stdout}

MENSAJES DE ERROR (STDERR):
{stderr}

Por favor analiza:
1. ¿El comando cumplió su objetivo?
2. ¿Hay algún problema o advertencia importante?
3. ¿El estado del servicio/sistema es correcto?
4. Recomendaciones específicas si es necesario

Responde en español de manera concisa pero completa, enfocándote en lo más relevante.
"""

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": "Eres un experto en Linux, DevOps y administración de sistemas. Analiza resultados técnicos de manera objetiva y proporciona recomendaciones prácticas en español."},
            {"role": "user", "content": user_msg},
        ],
    }

    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"].strip()


# ==========================
# PROGRAMA PRINCIPAL
# ==========================

def main():
    print_banner()

    ssh_password = None
    if not USE_SSH_KEY:
        ssh_password = getpass.getpass(f"{BLUE}?{WHITE} Contraseña SSH para {RPI_USER}@{RPI_HOST} ➜ {RESET}")

    client = connect_ssh(password=ssh_password)

    try:
        while True:
            user_request = user_prompt()
            if user_request.lower() in ("salir", "exit", "quit", "q"):
                print(f"\n{BLUE}┌{WHITE} SESIÓN TERMINADA {'─' * 48}{RESET}")
                print(f"{BLUE}│{RESET}")
                print(f"{BLUE}│{GREEN} ✓ Gracias por usar el Agente Raspberry Pi{RESET}")
                print(f"{BLUE}└{'─' * 70}{RESET}")
                break

            # Pedir a Ollama que genere el comando
            try:
                cmd_obj = ask_ollama_for_command(user_request)
            except Exception:
                print_error("No se pudo obtener un comando válido del modelo.")
                continue

            command = cmd_obj.get("command", "").strip()
            explanation = cmd_obj.get("explanation", "").strip()
            dangerous = bool(cmd_obj.get("dangerous", False))

            print_section("PROPUESTA DE COMANDO", "🎯")
            print_kv("Comando", command, GREEN)
            print_kv("Explicación", explanation, WHITE)
            print_kv("Peligroso", 
                    f"{RED}ALTO RIESGO - Requiere precaución" if dangerous else 
                    f"{GREEN}SEGURO - Operación estándar", WHITE)

            if not command:
                print_error("El modelo no proporcionó un comando válido. Intenta reformular tu petición.")
                continue

            # Confirmación del usuario
            if not yes_no_prompt("¿Ejecutar este comando en la Raspberry Pi?"):
                print_warning("Ejecución de comando cancelada.")
                continue

            # Ejecutar comando remotamente
            print_info("Ejecutando comando... ⏳")
            stdout, stderr, exit_code, exec_time = run_remote_command(client, command)

            # Mostrar resultados
            print_result_header()
            
            stdout_clean = stdout.strip()
            stderr_clean = stderr.strip()

            # Determinar si es un log para procesamiento especial
            is_log_output = any(keyword in command.lower() for keyword in ['log', 'journal', 'status', 'systemctl'])
            
            if stdout_clean:
                print_output_block(stdout_clean, "SALIDA PRINCIPAL", is_log=is_log_output)
            elif not stderr_clean:
                print_info("Comando ejecutado exitosamente (sin salida)")

            if stderr_clean:
                print_output_block(stderr_clean, "ERRORES", is_log=is_log_output)

            print_footer(exit_code, exec_time)

            # Preguntar si quiere explicación del resultado
            if yes_no_prompt("¿Obtener análisis de los resultados?", default_no=False):
                print_info("Analizando resultados... 🔍")
                try:
                    explanation = explain_output_with_ollama(command, stdout, stderr)
                    print_section("ANÁLISIS DE IA", "🧠")
                    print_output_block(explanation, "ANÁLISIS")
                except Exception as e:
                    print_error(f"Error al obtener análisis: {e}")

    except KeyboardInterrupt:
        print(f"\n{BLUE}┌{WHITE} SESIÓN INTERRUMPIDA {'─' * 46}{RESET}")
        print(f"{BLUE}│{RESET}")
        print(f"{BLUE}│{YELLOW} ⚠ Sesión terminada por el usuario{RESET}")
        print(f"{BLUE}└{'─' * 70}{RESET}")
    finally:
        client.close()
        print(f"\n{BLUE}{'═' * 70}{RESET}")
        print(f"{BLUE}║{WHITE}{'Conexión SSH cerrada':^68}{BLUE}║{RESET}")
        print(f"{BLUE}{'═' * 70}{RESET}")


if __name__ == "__main__":
    main()