#pip install --user requests paramiko colorama
#!/usr/bin/env python3
import json
import getpass
import requests
import paramiko
import time
import re
import sys
import threading
from typing import List, Dict, Any

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

# Datos del servidor
RPI_HOST = "192.168.1.96"
RPI_USER = "pfranco"
USE_SUDO = False
SUDO_PASSWORD = None

USE_SSH_KEY = False
SSH_KEY_PATH = r"C:\Users\opi\.ssh\id_ed25519"

# Memoria de contexto
conversation_context = {
    "last_command": "",
    "last_output": "",
    "last_analysis": "",
    "follow_up_count": 0,
    "discovered_containers": [],
    "discovered_services": [],
    "extracted_info": {}
}


# ==========================
# ANIMACIONES Y EFECTOS VISUALES
# ==========================

class Spinner:
    """Animación de spinner para operaciones en progreso"""
    def __init__(self, message="Cargando"):
        self.message = message
        self.spinner_chars = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        self.done = False
        self.thread = None

    def _animate(self):
        i = 0
        while not self.done:
            sys.stdout.write(f"\r{BLUE}│{RESET} {CYAN}{self.spinner_chars[i]} {self.message}{RESET}")
            sys.stdout.flush()
            time.sleep(0.1)
            i = (i + 1) % len(self.spinner_chars)

    def start(self):
        self.done = False
        self.thread = threading.Thread(target=self._animate)
        self.thread.daemon = True
        self.thread.start()

    def stop(self, message=None):
        self.done = True
        if self.thread:
            self.thread.join()
        sys.stdout.write("\r" + " " * 80 + "\r")
        if message:
            print(f"{BLUE}│{RESET} {GREEN}✓ {message}{RESET}")


def print_loading(message, func, *args, **kwargs):
    """Ejecuta una función con animación de carga"""
    spinner = Spinner(message)
    spinner.start()
    try:
        result = func(*args, **kwargs)
        spinner.stop("Listo!")
        return result
    except Exception as e:
        spinner.stop("Error!")
        raise e


def highlight_important_text(text: str) -> str:
    """Resalta texto importante en el análisis con colores"""
    highlight_patterns = {
        r'\b(error|fail|failed|failure|crash)\b': RED,
        r'\b(warn|warning|attention|careful)\b': YELLOW,
        r'\b(success|ok|correct|healthy|running)\b': GREEN,
        r'\b(important|critical|urgent|priority)\b': MAGENTA,
        r'\b(recommend|suggest|advise|should)\b': CYAN,
        r'\b(\d+\.\d+\.\d+\.\d+|[a-f0-9:]+)\b': BLUE,
        r'\b(\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2})\b': BLUE,
    }
    
    highlighted = text
    for pattern, color in highlight_patterns.items():
        highlighted = re.sub(
            pattern, 
            lambda m: f"{color}{m.group(0)}{RESET}", 
            highlighted, 
            flags=re.IGNORECASE
        )
    
    return highlighted


def print_banner():
    """Banner mejorado con más estilo"""
    banner = f"""
{BLUE}{'╔' + '═' * 68 + '╗'}{RESET}
{BLUE}║{MAGENTA}{'🚀 AGENTE DEVOPRO AI':^68}{BLUE}║{RESET}
{BLUE}║{WHITE}{'Asistente Inteligente de Operaciones':^68}{BLUE}║{RESET}
{BLUE}{'╠' + '═' * 68 + '╣'}{RESET}
{BLUE}║ {CYAN}► Modelo: {GREEN}{OLLAMA_MODEL:<46}{BLUE}║{RESET}
{BLUE}║ {CYAN}► Objetivo: {GREEN}{RPI_USER}@{RPI_HOST:<43}{BLUE}║{RESET}
{BLUE}║ {CYAN}► Autenticación: {GREEN}{'Clave SSH' if USE_SSH_KEY else 'Contraseña':<39}{BLUE}║{RESET}
{BLUE}║ {CYAN}► Privilegios: {GREEN}{'Sudo' if USE_SUDO else 'Root/Directo':<41}{BLUE}║{RESET}
{BLUE}{'╚' + '═' * 68 + '╝'}{RESET}

{YELLOW}✨ Consejos:{RESET}
{YELLOW}  • Escribe 'salir' para terminar la sesión{RESET}
{YELLOW}  • Usa comandos claros y específicos{RESET}
{YELLOW}  • Puedes hacer preguntas de seguimiento{RESET}
{YELLOW}  • Los comandos peligrosos requieren confirmación{RESET}
"""
    print(banner)


def print_section(title: str, emoji: str = "📋"):
    """Secciones con mejor diseño"""
    print(f"\n{BLUE}┌{MAGENTA}{emoji} {WHITE}{title}{'─' * (65 - len(title))}{RESET}")
    print(f"{BLUE}│{RESET}")


def print_command_header(command: str):
    """Presentación mejorada del comando"""
    print(f"\n{BLUE}┌{GREEN} 🚀 EJECUTANDO COMANDO {'─' * 45}{RESET}")
    print(f"{BLUE}│{GREEN} $ {command}{RESET}")
    print(f"{BLUE}│{RESET}")


def print_result_header():
    """Header para resultados con mejor diseño"""
    print(f"{BLUE}├{CYAN} 📊 RESULTADOS {'─' * 52}{RESET}")
    print(f"{BLUE}│{RESET}")


def print_footer(exit_code: int, execution_time: float):
    """Footer mejorado"""
    status_emoji = "✅" if exit_code == 0 else "❌"
    status = f"{GREEN}ÉXITO{status_emoji}" if exit_code == 0 else f"{RED}FALLÓ{status_emoji}"
    tiempo = f"{execution_time:.2f}s"
    
    print(f"{BLUE}│{RESET}")
    print(f"{BLUE}└{WHITE} {status} {WHITE}| Código: {exit_code} | Tiempo: {tiempo} {' ' * 20}{RESET}")


def print_kv(label: str, value: str, color=WHITE, indent=0):
    """Líneas clave-valor mejoradas"""
    indent_str = "  " * indent
    print(f"{BLUE}│{RESET}{indent_str} {CYAN}{label:<16}{RESET} {color}{value}{RESET}")


def print_info(message: str, emoji: str = "ℹ️ "):
    """Mensajes informativos mejorados"""
    print(f"{BLUE}│{RESET} {CYAN}{emoji} {message}{RESET}")


def print_warning(message: str):
    """Mensajes de advertencia mejorados"""
    print(f"{BLUE}│{RESET} {YELLOW}⚠️  {message}{RESET}")


def print_error(message: str):
    """Mensajes de error mejorados"""
    print(f"{BLUE}│{RESET} {RED}❌ {message}{RESET}")


def print_success(message: str):
    """Mensajes de éxito mejorados"""
    print(f"{BLUE}│{RESET} {GREEN}✅ {message}{RESET}")


def format_output_with_sections(content: str, title: str = "SALIDA") -> List[str]:
    """Formatea la salida con mejoras visuales"""
    lines = content.strip().split('\n')
    formatted_lines = []
    
    current_section = None
    in_yaml_block = False
    yaml_lines = []
    
    for line in lines:
        if line.strip().endswith('.yml:') or line.strip() in ['cloudflare-tunnel.yml', 'production-tunnel.yml']:
            if yaml_lines and current_section:
                formatted_lines.extend(yaml_lines)
                yaml_lines = []
            current_section = line.strip()
            formatted_lines.append(f"{BLUE}│{RESET}")
            formatted_lines.append(f"{BLUE}│{WHITE} 📄 {current_section}{RESET}")
            continue
            
        if 'systemctl status' in content and any(x in line for x in ['●', 'Loaded:', 'Active:', 'Main PID:']):
            if yaml_lines:
                formatted_lines.extend(yaml_lines)
                yaml_lines = []
            if '●' in line and current_section != 'ESTADO DEL SERVICIO':
                current_section = 'ESTADO DEL SERVICIO'
                formatted_lines.append(f"{BLUE}│{RESET}")
                formatted_lines.append(f"{BLUE}│{WHITE} ⚙️  {current_section}{RESET}")
            formatted_lines.append(f"{BLUE}│{RESET}   {line}")
            continue
            
        if line.strip() and (':' in line or line.strip().startswith('- ') or line.strip().startswith('  ')):
            yaml_lines.append(f"{BLUE}│{RESET}   {line}")
        else:
            if yaml_lines:
                formatted_lines.extend(yaml_lines)
                yaml_lines = []
            if line.strip():
                formatted_lines.append(f"{BLUE}│{RESET}   {line}")
    
    if yaml_lines:
        formatted_lines.extend(yaml_lines)
    
    return formatted_lines


def print_output_block(content: str, title: str = "SALIDA", max_lines: int = 50):
    """Bloque de output con mejoras visuales"""
    if not content.strip():
        return
    
    lines = content.strip().split('\n')
    
    if len(lines) > max_lines:
        important_lines = []
        for line in lines:
            if any(keyword in line.lower() for keyword in [
                'error', 'warn', 'fail', 'active:', 'loaded:', 'main pid', 
                'tunnel:', 'ingress:', 'hostname:', 'service:'
            ]):
                important_lines.append(line)
        
        if important_lines:
            lines = important_lines[:max_lines]
            if len(important_lines) > max_lines:
                lines.append(f"{CYAN}... [{len(important_lines) - max_lines} líneas adicionales omitidas] ...{RESET}")
        else:
            lines = lines[:max_lines//2] + [f"{CYAN}... [{len(lines) - max_lines} líneas omitidas] ...{RESET}"] + lines[-(max_lines//2):]
    
    print(f"{BLUE}│{RESET}")
    print(f"{BLUE}│{WHITE} 📋 {title}:{RESET}")
    
    formatted_lines = format_output_with_sections(content)
    for line in formatted_lines[:max_lines + 10]:
        print(line)


def print_analysis_block(content: str, title: str = "ANÁLISIS"):
    """Bloque de análisis con texto resaltado"""
    if not content.strip():
        return
    
    highlighted_content = highlight_important_text(content)
    lines = highlighted_content.strip().split('\n')
    
    print(f"{BLUE}│{RESET}")
    print(f"{BLUE}│{MAGENTA} 🧠 {title}:{RESET}")
    print(f"{BLUE}│{RESET}")
    
    for line in lines:
        if line.strip():
            if line.strip().startswith('**') and line.strip().endswith('**'):
                clean_line = line.strip('* ').strip()
                print(f"{BLUE}│{RESET}   {CYAN}🔹 {clean_line}{RESET}")
            elif line.strip().startswith('- **'):
                clean_line = line.strip('-* ').strip()
                print(f"{BLUE}│{RESET}     {GREEN}• {clean_line}{RESET}")
            elif line.strip().startswith('-'):
                clean_line = line.strip('- ').strip()
                print(f"{BLUE}│{RESET}     {WHITE}• {clean_line}{RESET}")
            elif re.match(r'^\d+\.', line.strip()):
                print(f"{BLUE}│{RESET}     {WHITE}{line.strip()}{RESET}")
            else:
                print(f"{BLUE}│{RESET}   {line}")


def user_prompt() -> str:
    """Prompt de usuario mejorado"""
    return input(f"\n{BLUE}➜{WHITE} ").strip()


def yes_no_prompt(msg: str, default_no: bool = True) -> bool:
    """Prompt de confirmación mejorado"""
    options = f"{WHITE}[{GREEN}s{RESET}/{WHITE}N]{RESET}" if default_no else f"{WHITE}[{GREEN}S{RESET}/{WHITE}n]{RESET}"
    ans = input(f"{BLUE}?{WHITE} {msg} {options}{WHITE} ➜ {RESET}").strip().lower()
    
    if default_no:
        return ans in ("s", "si", "sí", "y", "yes")
    else:
        return ans not in ("n", "no")


# ==========================
# FUNCIONES DE EXTRACCIÓN DE INFORMACIÓN
# ==========================

def extract_container_info(output: str) -> Dict[str, str]:
    """Extrae información de contenedores de la salida de docker ps"""
    containers = {}
    lines = output.strip().split('\n')
    
    header_line = None
    for i, line in enumerate(lines):
        if 'CONTAINER ID' in line and 'IMAGE' in line and 'NAMES' in line:
            header_line = line
            data_start = i + 1
            break
    
    if not header_line:
        return containers
    
    for line in lines[data_start:]:
        if not line.strip():
            continue
            
        parts = line.split()
        if len(parts) >= 2:
            container_name = parts[-1]
            image_parts = []
            for part in parts:
                if '/' in part or ':' in part:
                    image_parts.append(part)
            
            image_name = ' '.join(image_parts) if image_parts else parts[1]
            
            container_type = "unknown"
            if 'postgres' in container_name.lower() or 'postgres' in image_name.lower():
                container_type = "postgres"
            elif 'frontend' in container_name.lower() or '3000' in line:
                container_type = "frontend"
            elif 'backend' in container_name.lower():
                container_type = "backend"
            elif 'nginx' in container_name.lower() or 'nginx' in image_name.lower():
                container_type = "nginx"
            elif 'redis' in container_name.lower() or 'redis' in image_name.lower():
                container_type = "redis"
            elif 'gateway' in container_name.lower():
                container_type = "gateway"
            elif 'cloudflare' in container_name.lower():
                container_type = "cloudflared"
            
            containers[container_type] = container_name
    
    return containers


def update_context_with_extracted_info(output: str, command: str):
    """Actualiza el contexto con información extraída"""
    if 'docker ps' in command:
        containers = extract_container_info(output)
        conversation_context["extracted_info"]["containers"] = containers
        print_info(f"Extraídos {len(containers)} contenedores del contexto")


# ==========================
# MANEJO DE SUDO
# ==========================

def wrap_command_with_sudo(command: str) -> str:
    """Envuelve el comando con sudo si es necesario"""
    if not USE_SUDO:
        return command
    
    sudo_commands = [
        'apt', 'dnf', 'yum', 'systemctl', 'service', 'journalctl',
        'docker', 'kubectl', 'kubeadm', 'iptables', 'ufw',
        'useradd', 'userdel', 'groupadd', 'chown', 'chmod',
        'mount', 'umount', 'fdisk', 'lsblk', 'blkid'
    ]
    
    first_word = command.split()[0] if command.split() else ""
    needs_sudo = any(first_word.startswith(cmd) for cmd in sudo_commands)
    
    if needs_sudo:
        return f"sudo -S {command}"
    else:
        return command


def handle_sudo_password(client: paramiko.SSHClient, command: str) -> tuple[str, str, int, float]:
    """Maneja la ejecución de comandos con sudo"""
    if not USE_SUDO or not SUDO_PASSWORD:
        return run_remote_command_basic(client, command)
    
    sudo_command = wrap_command_with_sudo(command)
    
    if 'sudo' not in sudo_command:
        return run_remote_command_basic(client, command)
    
    print_command_header(sudo_command)
    
    start_time = time.time()
    stdin, stdout, stderr = client.exec_command(sudo_command)
    
    time.sleep(0.5)
    if stdout.channel.recv_ready():
        stdin.write(SUDO_PASSWORD + '\n')
        stdin.flush()
    
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    exit_code = stdout.channel.recv_exit_status()
    execution_time = time.time() - start_time
    
    return out, err, exit_code, execution_time


def run_remote_command_basic(client: paramiko.SSHClient, command: str) -> tuple[str, str, int, float]:
    """Ejecuta comando básico sin manejo de sudo"""
    print_command_header(command)
    
    start_time = time.time()
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    exit_code = stdout.channel.recv_exit_status()
    execution_time = time.time() - start_time
    
    return out, err, exit_code, execution_time


def run_remote_command(client: paramiko.SSHClient, command: str) -> tuple[str, str, int, float]:
    """Ejecuta comando con soporte para sudo"""
    return handle_sudo_password(client, command)


# ==========================
# PROMPT DEL AGENTE MEJORADO - VERSIÓN MÁS ESTRICTA
# ==========================

def get_system_prompt():
    """Construye el prompt del sistema dinámicamente"""
    
    sudo_section = """
**MANEJO DE PRIVILEGIOS:**
El usuario tiene privilegios root, no es necesario usar sudo.
- Ejecuta los comandos directamente sin 'sudo'
""" if not USE_SUDO else """
**MANEJO DE PRIVILEGIOS:**
El usuario actual necesita usar sudo para algunos comandos.
- Comandos que requieren sudo: systemctl, docker, apt, journalctl, etc.
- El sistema automáticamente agregará 'sudo' cuando sea necesario
- NO agregues 'sudo' manualmente en tus comandos
"""
    
    return f"""
Eres un asistente DevSecOps experto en Linux. Tu ÚNICA tarea es generar comandos Linux específicos.

**FORMATO OBLIGATORIO:**
Tu respuesta debe ser EXCLUSIVAMENTE un objeto JSON válido con esta estructura exacta:
{{
  "command": "comando linux aquí",
  "explanation": "explicación breve en español",
  "dangerous": false,
  "reasoning": "razonamiento paso a paso en español"
}}

**REGLAS ESTRICTAS:**
1. SOLO JSON - nada de texto antes o después
2. SIN placeholders - usa nombres REALES del contexto
3. SIN markdown - no uses ```json o bloques de código
4. SIN explicaciones adicionales fuera del JSON
5. UN SOLO comando por respuesta

**CONTEXTO DE CONTENEDORES DISPONIBLES:**
Sabemos que existe un contenedor frontend en puerto 3000 llamado 'arkanops-frontend'
Sabemos que existe un contenedor gateway llamado 'arkanops-gateway'
Sabemos que existe cloudflared configurado

**EJEMPLOS CORRECTOS:**
Usuario: "revisa el log del contenedor frontend"
Respuesta: {{"command": "docker logs arkanops-frontend", "explanation": "Revisa los logs del contenedor frontend", "dangerous": false, "reasoning": "El contenedor frontend está en puerto 3000 según el contexto"}}

Usuario: "verifica si el servicio está corriendo"
Respuesta: {{"command": "docker ps | grep arkanops-frontend", "explanation": "Verifica si el contenedor frontend está ejecutándose", "dangerous": false, "reasoning": "Necesito confirmar el estado del contenedor que sirve la aplicación en puerto 3000"}}

{sudo_section}

**SI EL USUARIO REPORTA ERRORES DE CONEXIÓN:**
- Primero verifica el estado de los contenedores relevantes
- Luego revisa logs para diagnosticar problemas
- Usa nombres específicos como 'arkanops-frontend', 'arkanops-gateway'

Tu respuesta debe ser SOLO el JSON, sin ningún otro texto.
"""


# ==========================
# FUNCIONES LÓGICAS MEJORADAS CON PARSING ROBUSTO
# ==========================

def clean_json_response(content: str) -> str:
    """Limpia la respuesta del modelo para extraer solo el JSON"""
    content = content.strip()
    
    # Caso 1: Ya es JSON válido
    if content.startswith('{') and content.endswith('}'):
        return content
    
    # Caso 2: Contiene ```json ... ```
    if '```json' in content:
        start = content.find('```json') + 7
        end = content.find('```', start)
        if end != -1:
            return content[start:end].strip()
    
    # Caso 3: Contiene ``` ... ```
    if '```' in content:
        start = content.find('```') + 3
        end = content.find('```', start)
        if end != -1:
            candidate = content[start:end].strip()
            if candidate.startswith('{') and candidate.endswith('}'):
                return candidate
    
    # Caso 4: Buscar el primer { y último }
    start = content.find('{')
    end = content.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidate = content[start:end+1]
        # Verificar que sea JSON válido
        try:
            json.loads(candidate)
            return candidate
        except:
            pass
    
    return content


def ask_ollama_for_command(user_request: str) -> dict:
    """Pide a Ollama que genere el comando a ejecutar"""

    def build_context_prompt():
        """Construye el prompt considerando el contexto de conversación"""
        base_prompt = get_system_prompt()
        
        # Agregar información extraída del contexto
        context_info = ""
        if conversation_context["extracted_info"].get("containers"):
            containers = conversation_context["extracted_info"]["containers"]
            context_info += f"\n\n**CONTENEDORES CONOCIDOS:**\n"
            for container_type, container_name in containers.items():
                context_info += f"- {container_type}: {container_name}\n"
        
        if conversation_context["last_output"]:
            context_info += f"\n**ÚLTIMA SALIDA (resumen):**\n{conversation_context['last_output'][:500]}..."
        
        if context_info:
            base_prompt += f"""

**INFORMACIÓN ACTUAL DEL SISTEMA:**{context_info}

**RECUERDA:** Usa los nombres EXACTOS de los contenedores mostrados arriba.
"""

        return base_prompt

    def call_ollama() -> str:
        system_msg = build_context_prompt()
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_msg},
                {
                    "role": "user", 
                    "content": f"Instrucción: {user_request}\n\nResponde SOLO con el JSON requerido:"
                },
            ],
        }
        
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"].strip()
        except Exception as e:
            print_error(f"Error al llamar a Ollama: {e}")
            raise

    def parse_response(content: str) -> dict | None:
        """Intenta parsear la respuesta del modelo"""
        if not content:
            return None
            
        # Limpiar la respuesta
        cleaned = clean_json_response(content)
        
        # Intentar parsear como JSON
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict) and 'command' in obj:
                # Validar que no use placeholders
                command = obj.get('command', '')
                if any(placeholder in command for placeholder in 
                       ['[nombre]', '[id]', '[ruta]', 'container_name', 'nombre-del-contenedor']):
                    return None
                return obj
        except json.JSONDecodeError:
            pass
            
        return None

    # Primer intento
    try:
        content1 = call_ollama()
        cmd_obj = parse_response(content1)
        
        if cmd_obj is not None:
            return cmd_obj

        print_warning("Primer intento falló - respuesta no válida")
        print_output_block(content1, "RESPUESTA CRUDA")
        
        # Segundo intento con instrucciones más estrictas
        print_info("Reintentando con instrucciones más estrictas...")
        strict_prompt = get_system_prompt() + """

**ERROR CRÍTICO - SEGUNDO INTENTO:**
Tu respuesta anterior fue rechazada porque:
- NO era JSON válido O
- Usaba placeholders como [nombre] O  
- Incluía texto adicional fuera del JSON

**RESPONDE EXACTAMENTE ASÍ:**
{"command": "comando específico", "explanation": "breve explicación", "dangerous": false, "reasoning": "razonamiento"}
"""
        
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": [
                {"role": "system", "content": strict_prompt},
                {"role": "user", "content": f"Instrucción: {user_request}\n\nRESPONDE SOLO CON JSON:"},
            ],
        }
        
        content2 = requests.post(OLLAMA_URL, json=payload, timeout=120).json()["message"]["content"].strip()
        cmd_obj = parse_response(content2)
        
        if cmd_obj is not None:
            return cmd_obj

        print_error("Segundo intento también falló")
        return None

    except Exception as e:
        print_error(f"Error en la comunicación: {e}")
        return None


def connect_ssh(password: str | None = None) -> paramiko.SSHClient:
    """Abre una conexión SSH al servidor."""
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


def explain_output_with_ollama(command: str, stdout: str, stderr: str) -> str:
    """Pide a Ollama que explique el resultado del comando"""
    user_msg = f"""
Analiza estos resultados técnicos:

COMANDO: {command}

SALIDA: {stdout}

ERRORES: {stderr}

Proporciona un análisis técnico estructurado enfocado en:
- Estado actual del sistema
- Problemas identificados  
- Recomendaciones específicas
- Información técnica relevante

Sé conciso y técnico.
"""

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": "Eres un experto DevOps. Analiza resultados técnicos de forma estructurada y práctica."},
            {"role": "user", "content": user_msg},
        ],
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()
    except Exception as e:
        return f"Error al generar análisis: {e}"


def ask_followup_question(question: str, context: dict) -> str:
    """Permite hacer preguntas de seguimiento"""
    user_msg = f"""
Contexto anterior:
- Comando: {context['last_command']}
- Salida: {context['last_output'][:800]}...
- Análisis: {context['last_analysis'][:400]}...

Pregunta: {question}

Responde basándote en el contexto anterior.
"""

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": "Responde preguntas técnicas basándote en el contexto proporcionado."},
            {"role": "user", "content": user_msg},
        ],
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()
    except Exception as e:
        return f"Error: {e}"


# ==========================
# PROGRAMA PRINCIPAL
# ==========================

def main():
    global SUDO_PASSWORD
    
    print_banner()

    # Configurar credenciales
    ssh_password = None
    if not USE_SSH_KEY:
        ssh_password = getpass.getpass(f"{BLUE}?{WHITE} Contraseña SSH para {RPI_USER}@{RPI_HOST} ➜ {RESET}")

    if USE_SUDO:
        SUDO_PASSWORD = getpass.getpass(f"{BLUE}?{WHITE} Contraseña sudo para {RPI_USER} ➜ {RESET}")

    # Conectar SSH
    try:
        client = print_loading("Conectando SSH...", connect_ssh, ssh_password)
    except Exception as e:
        print_error(f"Error al conectar SSH: {e}")
        return

    try:
        while True:
            user_request = user_prompt()
            if user_request.lower() in ("salir", "exit", "quit", "q"):
                print(f"\n{BLUE}┌{WHITE} 🏁 SESIÓN TERMINADA {'─' * 45}{RESET}")
                print(f"{BLUE}│{RESET}")
                print(f"{BLUE}│{GREEN} ✅ Gracias por usar el Agente DevOps AI{RESET}")
                print(f"{BLUE}└{'─' * 70}{RESET}")
                break

            # Preguntas de seguimiento
            is_followup = (conversation_context["last_analysis"] and 
                          any(keyword in user_request.lower() for keyword in 
                              ['cómo', 'por qué', 'qué', 'cuándo', 'dónde', 'explica', 'analiza', '?']))
            
            if is_followup:
                print_info("Procesando pregunta de seguimiento...")
                try:
                    followup_response = ask_followup_question(user_request, conversation_context)
                    print_section("RESPUESTA DE SEGUIMIENTO", "💬")
                    print_analysis_block(followup_response, "ANÁLISIS")
                    conversation_context["follow_up_count"] += 1
                    continue
                except Exception as e:
                    print_error(f"Error: {e}")

            conversation_context["follow_up_count"] = 0

            # Obtener comando
            try:
                cmd_obj = print_loading("Generando comando...", ask_ollama_for_command, user_request)
            except Exception as e:
                print_error(f"Error: {e}")
                continue

            if not cmd_obj:
                print_error("No se pudo generar un comando válido.")
                continue

            command = cmd_obj.get("command", "").strip()
            explanation = cmd_obj.get("explanation", "").strip()
            dangerous = bool(cmd_obj.get("dangerous", False))
            reasoning = cmd_obj.get("reasoning", "").strip()

            print_section("PROPUESTA DE COMANDO", "🎯")
            print_kv("Comando", command, GREEN)
            print_kv("Explicación", explanation, WHITE)
            print_kv("Peligroso", f"{RED}🚨 ALTO RIESGO" if dangerous else f"{GREEN}✅ SEGURO", WHITE)
            
            if reasoning:
                print(f"{BLUE}│{RESET}")
                print(f"{BLUE}│{CYAN} 🧠 Razonamiento:{RESET}")
                for line in reasoning.split('\n'):
                    if line.strip():
                        print(f"{BLUE}│{RESET}   {CYAN}{line.strip()}{RESET}")

            if not command:
                print_error("Comando vacío.")
                continue

            # Confirmación
            if dangerous and not yes_no_prompt("⚠️  ALTO RIESGO. ¿Continuar?"):
                print_warning("Cancelado.")
                continue
            elif not dangerous and not yes_no_prompt("¿Ejecutar comando?"):
                print_warning("Cancelado.")
                continue

            # Ejecutar
            try:
                stdout, stderr, exit_code, exec_time = print_loading(
                    "Ejecutando...", run_remote_command, client, command
                )
            except Exception as e:
                print_error(f"Error ejecutando: {e}")
                continue

            # Actualizar contexto
            conversation_context["last_command"] = command
            conversation_context["last_output"] = stdout + "\n" + stderr
            update_context_with_extracted_info(stdout + stderr, command)

            # Mostrar resultados
            print_result_header()
            
            if stdout.strip():
                print_output_block(stdout.strip(), "SALIDA")
            elif not stderr.strip():
                print_info("Comando ejecutado (sin salida)")

            if stderr.strip():
                print_output_block(stderr.strip(), "ERRORES")

            print_footer(exit_code, exec_time)

            # Análisis
            if yes_no_prompt("¿Análisis IA?", default_no=False):
                try:
                    analysis = print_loading("Analizando...", explain_output_with_ollama, command, stdout, stderr)
                    conversation_context["last_analysis"] = analysis
                    print_section("ANÁLISIS IA", "🧠")
                    print_analysis_block(analysis, "ANÁLISIS")
                except Exception as e:
                    print_error(f"Error en análisis: {e}")

    except KeyboardInterrupt:
        print(f"\n{BLUE}┌{WHITE} ⚠️  SESIÓN INTERRUMPIDA {'─' * 42}{RESET}")
        print(f"{BLUE}│{RESET}")
        print(f"{BLUE}│{YELLOW} Sesión terminada{RESET}")
        print(f"{BLUE}└{'─' * 70}{RESET}")
    except Exception as e:
        print_error(f"Error: {e}")
    finally:
        try:
            client.close()
            print(f"\n{BLUE}{'═' * 70}{RESET}")
            print(f"{BLUE}║{WHITE}{'🔌 Conexión cerrada':^68}{BLUE}║{RESET}")
            print(f"{BLUE}{'═' * 70}{RESET}")
        except:
            pass


if __name__ == "__main__":
    main()