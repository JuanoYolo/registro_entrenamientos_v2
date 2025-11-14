# auth.py — Login sencillo con código de acceso (sin Google, sin Supabase)
import os
import streamlit as st


def require_login():
    """
    Gate de acceso muy simple:
    - Pide un "correo/nombre" solo para identificar quién está usando la app.
    - Pide un código de acceso (ACCESS_CODE en secrets).
    - Si el código es correcto, marca la sesión como autenticada en st.session_state.
    """
    # 1) ¿Ya está logueado en esta sesión?
    if st.session_state.get("logged_in"):
        email = st.session_state.get("user_email", "entrenadora@app")
        # Esto se usa para filtrar datos si el backend es Supabase
        os.environ["OWNER_EMAIL"] = email
        return {"email": email}

    # 2) Configuración: código de acceso
    access_code_conf = st.secrets.get("ACCESS_CODE", "").strip()

    st.subheader("Acceso privado")
    st.write("Esta app es solo para la entrenadora y sus registros de clases.")

    email = st.text_input(
        "Correo o nombre para identificar la sesión",
        key="login_email",
        placeholder="ej. tu_correo@gmail.com",
    )
    code = st.text_input(
        "Código de acceso",
        type="password",
        key="login_code",
        placeholder="Escribe el código que definiste en secrets",
    )

    if st.button("Entrar", use_container_width=True):
        # Si no hay ACCESS_CODE definido en secrets, dejamos pasar a cualquiera
        if access_code_conf and code != access_code_conf:
            st.error("Código de acceso incorrecto.")
            return None

        if not email:
            email = "entrenadora@app"

        st.session_state["logged_in"] = True
        st.session_state["user_email"] = email
        os.environ["OWNER_EMAIL"] = email
        st.rerun()

    return None


def sign_out():
    """Cerrar sesión sencilla: limpiar estado y recargar."""
    for k in ("logged_in", "user_email", "pkce_verifier", "access_token"):
        st.session_state.pop(k, None)
    os.environ.pop("OWNER_EMAIL", None)
    st.query_params.clear()
    st.rerun()
