import os
import json
import requests
import paramiko
import gradio as gr
import time
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========= Config desde entorno =========
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434/api/chat") 
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "deepseek-coder:6.7b")

# Suprimir warnings de cryptography (son solo deprecation warnings)
import warnings
warnings.filterwarnings("ignore", message=".*TripleDES.*")

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

def wait_for_ollama():
    """Espera a que Ollama esté listo antes de iniciar la app"""
    max_retries = 30
    retry_delay = 5
    
    logger.info("🕐 Esperando a que Ollama esté listo...")
    
    for i in range(max_retries):
        try:
            # Verificar si Ollama responde
            health_url = OLLAMA_URL.replace('/api/chat', '/api/tags')
            resp = requests.get(health_url, timeout=10)
            if resp.status_code == 200:
                logger.info("✅ Ollama está listo!")
                return True
        except Exception as e:
            if i < max_retries - 1:
                logger.info(f"🔄 Ollama no está listo aún (intento {i+1}/{max_retries}), esperando...")
                time.sleep(retry_delay)
            else:
                logger.error(f"❌ Ollama no está disponible después de {max_retries} intentos: {e}")
                return False
    return False

# ========= Lógica de modelo =========

def call_ollama(user_request: str, extra_system: str = "") -> str:
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
    
    logger.info(f"🔍 Llamando a Ollama en: {OLLAMA_URL}")
    logger.info(f"🔍 Modelo: {OLLAMA_MODEL}")
    
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ Error HTTP: {e}")
        logger.error(f"🔍 Respuesta: {resp.text if 'resp' in locals() else 'No response'}")
        raise
    except Exception as e:
        logger.error(f"❌ Error general: {e}")
        raise


def try_parse_command(content: str) -> dict | None:
    # 1) bloque <json>...</json>
    if "<json>" in content and "</json>" in content:
        start = content.find("<json>") + len("<json>")
        end = content.rfind("</json>")
        content = content[start:end].strip()

    # 2) quitar ``` si los trae
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

    # 4) recortar primer { y último }
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


def ask_ollama_for_command(user_request: str) -> dict:
    # Primer intento
    content1 = call_ollama(user_request)
    cmd_obj = try_parse_command(content1)
    if cmd_obj is not None:
        return cmd_obj

    # Segundo intento más estricto
    extra_system = """

ESTO ES CRÍTICO:
- Si devuelves algo que no sea EXACTAMENTE un JSON, el sistema fallará.
- No expliques nada fuera del JSON.
- No uses backticks ni bloques de código.
- No escribas pasos ni instrucciones humanas.
"""
    content2 = call_ollama(user_request, extra_system=extra_system)
    cmd_obj = try_parse_command(content2)
    if cmd_obj is not None:
        return cmd_obj

    raise ValueError("No se pudo obtener JSON válido desde el modelo")

# ========= SSH / Ejecución remota =========

def connect_ssh(host: str, user: str, use_ssh_key: bool,
                ssh_key_path: str | None, password: str | None) -> paramiko.SSHClient:
    if not host or not user:
        raise RuntimeError("Debes indicar host y usuario de la Raspberry.")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if use_ssh_key:
        if not ssh_key_path:
            raise RuntimeError("Seleccionaste clave SSH pero no indicaste la ruta.")
        client.connect(
            host,
            username=user,
            key_filename=ssh_key_path,
            look_for_keys=False,
            allow_agent=True,
        )
    else:
        if not password:
            raise RuntimeError("Seleccionaste password pero no ingresaste la contraseña.")
        client.connect(host, username=user, password=password)

    return client


def run_remote_command(host: str, user: str, use_ssh_key: bool,
                       ssh_key_path: str | None, password: str | None,
                       command: str) -> tuple[str, str, int]:
    client = connect_ssh(host, user, use_ssh_key, ssh_key_path, password)
    try:
        stdin, stdout, stderr = client.exec_command(command)
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        exit_code = stdout.channel.recv_exit_status()
        return out, err, exit_code
    finally:
        client.close()


def explain_output(command: str, stdout: str, stderr: str) -> str:
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
            {"role": "system", "content": "Eres un experto en Linux y administración de sistemas. Explica de forma clara y concisa en español."},
            {"role": "user", "content": user_msg},
        ],
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"].strip()

# ========= Helpers para la UI =========

def test_connection(host: str, user: str, use_ssh_key: bool,
                    ssh_key_path: str, password: str):
    try:
        client = connect_ssh(
            host=host,
            user=user,
            use_ssh_key=use_ssh_key,
            ssh_key_path=ssh_key_path if use_ssh_key else None,
            password=password if not use_ssh_key else None,
        )
        client.close()
        return "✅ Conexión SSH exitosa"
    except Exception as e:
        return f"❌ Error de conexión: {e}"


def chat_agent(chat_history, user_request: str,
               host: str, user: str, use_ssh_key: bool,
               ssh_key_path: str, password: str):

    user_request = (user_request or "").strip()
    if not user_request:
        return chat_history, ""

    chat_history = chat_history or []
    chat_history.append((user_request, None))

    if not host or not user:
        chat_history[-1] = (user_request, "❌ Configura host y usuario en el panel izquierdo.")
        return chat_history, ""

    if not use_ssh_key and not password:
        chat_history[-1] = (user_request, "❌ Seleccionaste password pero no ingresaste la contraseña.")
        return chat_history, ""

    try:
        cmd_obj = ask_ollama_for_command(user_request)
    except Exception as e:
        chat_history[-1] = (user_request, f"❌ Error al generar comando: {e}")
        return chat_history, ""

    command = cmd_obj.get("command", "").strip()
    explanation = cmd_obj.get("explanation", "").strip()
    dangerous = bool(cmd_obj.get("dangerous", False))

    if not command:
        chat_history[-1] = (user_request, "❌ El modelo no devolvió un comando.")
        return chat_history, ""

    try:
        stdout, stderr, exit_code = run_remote_command(
            host=host,
            user=user,
            use_ssh_key=use_ssh_key,
            ssh_key_path=ssh_key_path if use_ssh_key else None,
            password=password if not use_ssh_key else None,
            command=command,
        )
    except Exception as e:
        chat_history[-1] = (user_request, f"❌ Error ejecutando por SSH: {e}")
        return chat_history, ""

    if exit_code == 0:
        exit_text = "0 (éxito)"
        exit_icon = "✅"
    else:
        exit_text = f"{exit_code} (error)"
        exit_icon = "⚠️"

    result_text = stdout.strip() or "(sin salida)"
    error_text = stderr.strip()

    try:
        explanation_detail = explain_output(command, stdout, stderr)
    except Exception as e:
        explanation_detail = f"⚠️ No se pudo obtener explicación detallada: {e}"

    # Mejor formato para la respuesta
    danger_icon = "🔴" if dangerous else "🟢"
    danger_text = "SÍ - Comando potencialmente peligroso" if dangerous else "NO - Comando seguro"
    
    respuesta_md = f"""
<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 15px; margin-bottom: 15px;">
    <h3 style="margin: 0; color: white;">🤖 Comando Ejecutado</h3>
</div>

<div style="background: #1a1a1a; padding: 15px; border-radius: 10px; margin: 10px 0;">
    <code style="color: #00ff88; font-size: 14px;">{command}</code>
</div>

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0;">
    <div style="background: #2d2d2d; padding: 12px; border-radius: 8px; text-align: center;">
        <div style="font-size: 24px;">{danger_icon}</div>
        <div style="font-size: 12px; color: #ccc;">Peligroso</div>
        <div style="font-size: 14px; font-weight: bold;">{danger_text}</div>
    </div>
    <div style="background: #2d2d2d; padding: 12px; border-radius: 8px; text-align: center;">
        <div style="font-size: 24px;">{exit_icon}</div>
        <div style="font-size: 12px; color: #ccc;">Código Salida</div>
        <div style="font-size: 14px; font-weight: bold;">{exit_text}</div>
    </div>
</div>

<div style="background: #1e3a5f; padding: 15px; border-radius: 10px; margin: 10px 0;">
    <h4 style="margin: 0 0 10px 0; color: #89c2ff;">📝 Explicación Breve</h4>
    <p style="margin: 0; color: #e0e0e0;">{explanation}</p>
</div>

{ f'<div style="background: #1a1a1a; padding: 15px; border-radius: 10px; margin: 10px 0; border-left: 4px solid #00ff88;"><h4 style="margin: 0 0 10px 0; color: #00ff88;">📤 Salida del Comando</h4><pre style="background: #000; padding: 10px; border-radius: 5px; overflow-x: auto; color: #00ff88; font-size: 12px;">{result_text}</pre></div>' if result_text != "(sin salida)" else '' }

{ f'<div style="background: #1a1a1a; padding: 15px; border-radius: 10px; margin: 10px 0; border-left: 4px solid #ff4444;"><h4 style="margin: 0 0 10px 0; color: #ff4444;">❌ Errores</h4><pre style="background: #000; padding: 10px; border-radius: 5px; overflow-x: auto; color: #ff6b6b; font-size: 12px;">{error_text}</pre></div>' if error_text else '' }

<div style="background: linear-gradient(135deg, #2c3e50 0%, #3498db 100%); padding: 15px; border-radius: 10px; margin: 15px 0;">
    <h4 style="margin: 0 0 10px 0; color: white;">🧠 Análisis Detallado</h4>
    <div style="background: rgba(255,255,255,0.1); padding: 12px; border-radius: 8px;">
        <p style="margin: 0; color: #e0e0e0; line-height: 1.4;">{explanation_detail}</p>
    </div>
</div>
"""

    chat_history[-1] = (user_request, respuesta_md)
    return chat_history, ""


def toggle_auth_fields(use_ssh_key: bool):
    if use_ssh_key:
        return gr.Textbox(interactive=True), gr.Textbox(interactive=False, value="", visible=False)
    else:
        return gr.Textbox(interactive=False, value=""), gr.Textbox(interactive=True, visible=True)

# ========= UI Mejorada =========

css = """
:root {
    --primary: #6366f1;
    --primary-dark: #4338ca;
    --secondary: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --background: #0f0f23;
    --surface: #1a1a2e;
    --card: #16213e;
    --text: #e2e8f0;
    --text-muted: #94a3b8;
}

.gradio-container {
    background: var(--background) !important;
    color: var(--text) !important;
    font-family: 'Segoe UI', system-ui, sans-serif;
}

#main-column {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    min-height: 100vh;
    padding: 20px;
    background: var(--background);
}

#chat-container {
    width: min(1000px, 100%);
    background: var(--surface);
    border-radius: 20px;
    padding: 0;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
    border: 1px solid rgba(255,255,255,0.1);
    overflow: hidden;
}

#header {
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
    padding: 25px 30px;
    color: white;
    text-align: center;
}

#header h1 {
    margin: 0;
    font-size: 28px;
    font-weight: 700;
}

#header p {
    margin: 8px 0 0 0;
    opacity: 0.9;
    font-size: 16px;
}

#chatbot {
    height: 500px;
    background: var(--card);
    border: none;
    border-radius: 0;
}

#chatbot .wrap {
    background: transparent !important;
}

#chatbot .message {
    padding: 16px 20px;
    margin: 8px 0;
    border-radius: 18px !important;
    border: none !important;
    max-width: 85%;
}

#chatbot .message.user {
    background: var(--primary) !important;
    color: white;
    margin-left: auto;
    border-bottom-right-radius: 4px !important;
}

#chatbot .message.bot {
    background: var(--surface) !important;
    color: var(--text);
    border: 1px solid rgba(255,255,255,0.1) !important;
    margin-right: auto;
    border-bottom-left-radius: 4px !important;
}

#input-section {
    padding: 20px;
    background: var(--surface);
    border-top: 1px solid rgba(255,255,255,0.1);
}

#user-input {
    background: var(--card) !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    border-radius: 12px !important;
    color: var(--text) !important;
    padding: 15px !important;
    font-size: 14px;
}

#user-input:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2) !important;
}

#sidebar {
    background: var(--surface);
    border-radius: 15px;
    padding: 20px;
    border: 1px solid rgba(255,255,255,0.1);
    margin-bottom: 20px;
}

#sidebar h3 {
    margin: 0 0 20px 0;
    color: var(--text);
    font-size: 18px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.config-group {
    background: var(--card);
    padding: 15px;
    border-radius: 10px;
    margin-bottom: 15px;
    border: 1px solid rgba(255,255,255,0.05);
}

.config-group label {
    color: var(--text-muted) !important;
    font-weight: 500;
}

.test-btn {
    background: linear-gradient(135deg, var(--secondary) 0%, #059669 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 12px 20px !important;
    font-weight: 600 !important;
}

.test-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 5px 15px rgba(16, 185, 129, 0.3) !important;
}

.primary-btn {
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 12px 30px !important;
    font-weight: 600 !important;
}

.secondary-btn {
    background: var(--card) !important;
    color: var(--text) !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    border-radius: 12px !important;
    padding: 12px 20px !important;
}

.buttons-row {
    display: flex;
    gap: 10px;
    margin-top: 15px;
}

.status-indicator {
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    text-align: center;
}

.status-success {
    background: rgba(16, 185, 129, 0.2);
    color: var(--secondary);
    border: 1px solid var(--secondary);
}

.status-error {
    background: rgba(239, 68, 68, 0.2);
    color: var(--danger);
    border: 1px solid var(--danger);
}

/* Scrollbar personalizado */
::-webkit-scrollbar {
    width: 6px;
}

::-webkit-scrollbar-track {
    background: var(--surface);
}

::-webkit-scrollbar-thumb {
    background: var(--primary);
    border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--primary-dark);
}
"""

with gr.Blocks(title="Agente Raspberry Pi IA", theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate"), css=css) as demo:
    
    with gr.Column(elem_id="main-column"):
        # Header moderno
        with gr.Column(elem_id="chat-container"):
            with gr.Column(elem_id="header"):
                gr.Markdown("""
                # 🤖 Agente Raspberry Pi IA
                ### Asistente inteligente para administración remota
                """)
            
            # Chatbot
            chatbot = gr.Chatbot(
                label="",
                height=500,
                show_copy_button=True,
                bubble_full_width=False,
                show_label=False,
                elem_id="chatbot"
            )
            
            # Input section
            with gr.Column(elem_id="input-section"):
                user_input = gr.Textbox(
                    placeholder="💡 ¿Qué quieres que haga en tu Raspberry Pi? Ej: 'Revisa el uso de disco', 'Muestra los contenedores Docker corriendo', 'Reinicia el servicio de red'...",
                    label="",
                    lines=2,
                    max_lines=4,
                    elem_id="user-input"
                )
                
                with gr.Row(elem_classes="buttons-row"):
                    send_btn = gr.Button("🚀 Ejecutar Comando", variant="primary", elem_classes="primary-btn")
                    clear_btn = gr.Button("🗑️ Limpiar Chat", variant="secondary", elem_classes="secondary-btn")
        
        # Sidebar de configuración
        with gr.Column(elem_id="sidebar"):
            gr.Markdown("### ⚙️ Configuración de Conexión")
            
            with gr.Group(elem_classes="config-group"):
                host_input = gr.Textbox(
                    label="🔗 Host / IP de la Raspberry",
                    value="192.168.1.94",
                    placeholder="ej: 192.168.1.100"
                )
                user_box = gr.Textbox(
                    label="👤 Usuario SSH",
                    value="pi",
                    placeholder="ej: pi, ubuntu, etc."
                )
            
            with gr.Group(elem_classes="config-group"):
                use_key_checkbox = gr.Checkbox(
                    label="🔑 Usar autenticación por clave SSH",
                    value=True,
                    info="Desmarca para usar contraseña"
                )
                
                ssh_key_path_box = gr.Textbox(
                    label="🗝️ Ruta de la clave SSH",
                    value="/app/.ssh/id_ed25519",
                    placeholder="/app/.ssh/id_rsa",
                    interactive=True,
                )
                password_box = gr.Textbox(
                    label="🔒 Contraseña SSH",
                    type="password",
                    placeholder="Ingresa la contraseña si no usas clave",
                    interactive=False,
                    visible=False
                )
            
            with gr.Group(elem_classes="config-group"):
                test_btn = gr.Button("🔌 Probar Conexión", variant="primary", elem_classes="test-btn")
                test_result = gr.Markdown("", elem_id="test-result")

    # Estado del chat
    chat_state = gr.State([])

    # Event handlers
    test_btn.click(
        fn=test_connection,
        inputs=[host_input, user_box, use_key_checkbox, ssh_key_path_box, password_box],
        outputs=test_result,
    )

    use_key_checkbox.change(
        fn=lambda x: (gr.Textbox(interactive=x), gr.Textbox(interactive=not x, visible=not x)),
        inputs=[use_key_checkbox],
        outputs=[ssh_key_path_box, password_box],
    )

    send_btn.click(
        fn=chat_agent,
        inputs=[
            chat_state,
            user_input,
            host_input,
            user_box,
            use_key_checkbox,
            ssh_key_path_box,
            password_box,
        ],
        outputs=[chatbot, user_input],
    )

    clear_btn.click(
        lambda: ([], ""),
        inputs=None,
        outputs=[chatbot, user_input],
    )

    # Enter para enviar
    user_input.submit(
        fn=chat_agent,
        inputs=[
            chat_state,
            user_input,
            host_input,
            user_box,
            use_key_checkbox,
            ssh_key_path_box,
            password_box,
        ],
        outputs=[chatbot, user_input],
    )

if __name__ == "__main__":
    logger.info("🚀 Iniciando Agente Raspberry Pi IA...")
    
    # Esperar a que Ollama esté listo
    if wait_for_ollama():
        logger.info("🌐 Iniciando servidor Gradio...")
        demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
    else:
        logger.error("❌ No se pudo conectar con Ollama. Saliendo...")
        exit(1)