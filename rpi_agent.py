#!/usr/bin/env python3
import json
import getpass
import requests
import paramiko

# Colores y estilos (con fallback si no hay colorama)
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    CYAN = Fore.CYAN + Style.BRIGHT
    GREEN = Fore.GREEN + Style.BRIGHT
    YELLOW = Fore.YELLOW + Style.BRIGHT
    RED = Fore.RED + Style.BRIGHT
    MAGENTA = Fore.MAGENTA + Style.BRIGHT
    RESET = Style.RESET_ALL
except ImportError:
    CYAN = GREEN = YELLOW = RED = MAGENTA = RESET = ""


# ==========================
# CONFIGURACIÓN BÁSICA
# ==========================

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "deepseek-coder:6.7b"

# Datos de la Raspberry Pi
RPI_HOST = "192.168.1.94"
RPI_USER = "pfranco"

USE_SSH_KEY = False          # True = llave privada, False = password
SSH_KEY_PATH = r"C:\Users\opi\.ssh\id_ed25519"  # ruta a la clave si USE_SSH_KEY=True


# ==========================
# PROMPT DEL AGENTE
# ==========================

SYSTEM_PROMPT = """
Eres un asistente DevOps experto en Linux y Raspberry Pi.

Tu única tarea:
- A partir de una instrucción del usuario, debes devolver UN SOLO comando Linux.
- NO escribas texto fuera del JSON.
- NO incluyas explicaciones antes o después.
- NO uses código markdown, NO uses ```json, NO uses ```bash.
- NO des pasos ni recomendaciones.
- NO respondas "no puedo", ni "aquí hay pasos", ni nada fuera del JSON.

INSTRUCCIÓN CRÍTICA:
Debes devolver la respuesta SIEMPRE DENTRO de:

<json>
{
  "command": "<comando>",
  "explanation": "<explicación breve en español>",
  "dangerous": true o false
}
</json>

- Nada fuera de <json>...</json>
- Nada después de </json>
- Nada antes de <json>
"""


# ==========================
# UTILIDADES DE FORMATO
# ==========================

def print_banner():
    title = " Agente Raspberry Pi + Ollama "
    line = "═" * len(title)
    print(f"{CYAN}╔{line}╗{RESET}")
    print(f"{CYAN}║{title}║{RESET}")
    print(f"{CYAN}╚{line}╝{RESET}")
    print(f"{MAGENTA}Modelo:{RESET} {OLLAMA_MODEL}")
    print(f"{MAGENTA}Host  :{RESET} {RPI_USER}@{RPI_HOST}")
    print(f"{MAGENTA}Tip   :{RESET} escribe 'salir' para terminar.\n")


def print_section(title: str):
    line = "─" * (len(title) + 2)
    print(f"{CYAN}┌{line}┐{RESET}")
    print(f"{CYAN}│ {title} │{RESET}")
    print(f"{CYAN}└{line}┘{RESET}")


def print_kv(label: str, value: str, color=GREEN):
    print(f"{color}{label:<18}{RESET}: {value}")


def user_prompt() -> str:
    return input(f"{YELLOW}🧑‍💻 Tú > {RESET}").strip()


def yes_no_prompt(msg: str, default_no: bool = True) -> bool:
    ans = input(f"{YELLOW}{msg} [s/N]{RESET} ").strip().lower()
    return ans in ("s", "si", "sí", "y", "yes")


# ==========================
# FUNCIONES LÓGICAS
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

    print(f"{YELLOW}⚠ Primer intento falló, contenido recibido:{RESET}")
    print(content1)
    print(f"{YELLOW}Reintentando con instrucciones más estrictas...\n{RESET}")

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

    print(f"{RED}⚠ Error al parsear JSON devuelto por el modelo (segundo intento).{RESET}")
    print("Contenido recibido (tras limpieza):")
    print(content2)
    raise ValueError("No se pudo parsear el JSON devuelto por el modelo")


def connect_ssh(password: str | None = None) -> paramiko.SSHClient:
    """Abre una conexión SSH a la Raspberry Pi."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if USE_SSH_KEY:
        print(f"{CYAN}🔐 Conectando a {RPI_USER}@{RPI_HOST} con clave SSH...{RESET}")
        client.connect(
            RPI_HOST,
            username=RPI_USER,
            key_filename=SSH_KEY_PATH,
            look_for_keys=False,
            allow_agent=True,
        )
    else:
        print(f"{CYAN}🔐 Conectando a {RPI_USER}@{RPI_HOST} con contraseña...{RESET}")
        if password is None:
            password = getpass.getpass("Contraseña SSH: ")
        client.connect(RPI_HOST, username=RPI_USER, password=password)

    print(f"{GREEN}✅ Conexión SSH establecida.\n{RESET}")
    return client


def run_remote_command(client: paramiko.SSHClient, command: str) -> tuple[str, str, int]:
    """Ejecuta un comando en la Raspberry y devuelve stdout, stderr y código de salida."""
    print(f"{CYAN}▶ Ejecutando en Raspberry:{RESET} {command}\n")
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    exit_code = stdout.channel.recv_exit_status()
    return out, err, exit_code


def explain_output_with_ollama(command: str, stdout: str, stderr: str) -> str:
    """Pide a Ollama que explique el resultado del comando."""
    user_msg = f"""
He ejecutado el siguiente comando en una Raspberry Pi:

COMANDO:
{command}

SALIDA STDOUT:
{stdout}

SALIDA STDERR:
{stderr}

Explícame en español qué significa este resultado y si hay algo que deba corregir o revisar.
"""

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": "Eres un experto en Linux y administración de sistemas."},
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
        ssh_password = getpass.getpass(f"{YELLOW}🔑 Contraseña SSH para la Raspberry: {RESET}")

    client = connect_ssh(password=ssh_password)

    try:
        while True:
            user_request = user_prompt()
            if user_request.lower() in ("salir", "exit", "quit"):
                print(f"\n{CYAN}👋 Saliendo del agente...{RESET}")
                break

            # Pedir a Ollama que genere el comando
            try:
                cmd_obj = ask_ollama_for_command(user_request)
            except Exception:
                print(f"{RED}❌ No se pudo obtener un comando válido desde el modelo.\n{RESET}")
                continue

            command = cmd_obj.get("command", "").strip()
            explanation = cmd_obj.get("explanation", "").strip()
            dangerous = bool(cmd_obj.get("dangerous", False))

            print_section("🎯 Propuesta del agente")
            print_kv("Comando sugerido", command)
            print_kv("Explicación", explanation)
            print_kv("¿Peligroso?", "SÍ" if dangerous else "no",
                     color=YELLOW if dangerous else GREEN)
            print()

            if not command:
                print(f"{RED}❌ El modelo no entregó un comando. Intenta reformular la instrucción.\n{RESET}")
                continue

            # Confirmación del usuario
            if not yes_no_prompt("¿Ejecutar este comando en la Raspberry?"):
                print(f"{YELLOW}⏭ Comando cancelado.\n{RESET}")
                continue

            # Ejecutar comando remotamente
            stdout, stderr, exit_code = run_remote_command(client, command)

            # ---- Resultado / errores más amigable ----
            stdout_clean = stdout.strip()
            stderr_clean = stderr.strip()

            if stdout_clean:
                print_section("📄 Resultado del comando")
                print(stdout_clean + "\n")

            if stderr_clean:
                print_section("⚠ Mensajes de error")
                print(f"{RED}{stderr_clean}{RESET}\n")

            if not stdout_clean and not stderr_clean:
                print_section("📄 Resultado del comando")
                print(f"{MAGENTA}(sin salida: el comando no devolvió texto){RESET}\n")

            # Interpretación amigable del código de salida
            if exit_code == 0:
                code_msg = "0 (éxito: el comando terminó correctamente)"
                code_color = GREEN
            else:
                code_msg = f"{exit_code} (hubo algún error; revisa los mensajes anteriores)"
                code_color = RED

            print_kv("Código de salida", code_msg, color=code_color)
            print()

            # Preguntar si quiere explicación del resultado
            if yes_no_prompt("¿Quieres que el modelo explique el resultado?"):
                explanation = explain_output_with_ollama(command, stdout, stderr)
                print_section("🧠 Explicación del modelo")

                # Le damos un poquito de formato a la explicación:
                lines = explanation.splitlines()
                if lines:
                    # Primera línea como “resumen”
                    print(f"{GREEN}{lines[0]}{RESET}")
                    for line in lines[1:]:
                        # Bullet points un poco más vistosos
                        if line.strip().startswith(("-", "•")):
                            print(f"{MAGENTA}{line}{RESET}")
                        else:
                            print(line)
                else:
                    print(explanation)

                print()

    finally:
        client.close()
        print(f"{CYAN}🔌 Conexión SSH cerrada.{RESET}")


if __name__ == "__main__":
    main()
