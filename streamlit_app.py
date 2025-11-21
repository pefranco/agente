import streamlit as st
import requests
import paramiko
import json
import os

# Configuración
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "deepseek-coder:6.7b"

st.set_page_config(
    page_title="Raspberry Pi Agent",
    page_icon="🤖",
    layout="centered"
)

# Estilos CSS personalizados
st.markdown("""
<style>
    .main {
        background-color: #0f0f23;
        color: white;
    }
    .stTextInput textarea {
        background-color: #1a1a2e !important;
        color: white !important;
    }
    .command-box {
        background-color: #1a1a2e;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #6366f1;
        margin: 1rem 0;
    }
    .output-box {
        background-color: #16213e;
        padding: 1rem;
        border-radius: 0.5rem;
        font-family: 'Courier New', monospace;
        margin: 0.5rem 0;
    }
    .success-box {
        border-left: 4px solid #10b981;
    }
    .error-box {
        border-left: 4px solid #ef4444;
    }
</style>
""", unsafe_allow_html=True)

def main():
    st.title("🤖 Raspberry Pi Agent")
    st.markdown("---")
    
    # Sidebar para configuración
    with st.sidebar:
        st.header("Configuración SSH")
        host = st.text_input("Host", value="192.168.1.96")
        user = st.text_input("Usuario", value="pfranco")
        use_key = st.checkbox("Usar clave SSH", value=True)
        
        if use_key:
            key_path = st.text_input("Ruta clave SSH", value="/app/.ssh/id_ed25519")
            password = None
        else:
            key_path = None
            password = st.text_input("Contraseña", type="password")
    
    # Chat principal
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Mostrar historial de chat
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Input del usuario
    if prompt := st.chat_input("¿Qué quieres ejecutar en la Raspberry Pi?"):
        # Agregar mensaje del usuario
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Procesar comando
        with st.chat_message("assistant"):
            with st.spinner("Generando comando..."):
                try:
                    # Aquí iría la lógica para generar y ejecutar comandos
                    # (similar a la del código CLI)
                    st.info("Esta funcionalidad requiere integrar la lógica del agente")
                    st.code("docker ps", language="bash")
                    
                except Exception as e:
                    st.error(f"Error: {e}")

if __name__ == "__main__":
    main()