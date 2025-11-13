# auth.py
# Login con Google vía Supabase (PKCE) sin loops en Streamlit Cloud.
# - En Cloud NO forzamos redirect_to (Supabase usa su Site URL).
# - En local SÍ usamos redirect_to=http://localhost:8501.
# Requiere: supabase-py (v2).

import os
import base64
import hashlib
from urllib.parse import quote

import streamlit as st
from supabase import create_client, Client


# -----------------------
# Helpers de configuración
# -----------------------
def _supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)


def _app_url() -> str:
    # En Cloud coloca en secrets: APP_URL="https://tuapp.streamlit.app"
    # En local puedes dejarlo vacío (cae en http://localhost:8501)
    return st.secrets.get("APP_URL", "http://localhost:8501")


# -----------------------
# Helpers de PKCE
# -----------------------
def _new_pkce_pair() -> tuple[str, str]:
    """Devuelve (verifier, challenge) URL-safe base64 sin '=' """
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _authorize_url(supabase_url: str, code_challenge: str, state: str, redirect_to: str | None) -> str:
    """
    Arma la URL /auth/v1/authorize de Supabase para Google.
    Sólo incluimos redirect_to cuando NO estamos en Cloud.
    """
    base = f"{supabase_url}/auth/v1/authorize"
    params = [
        ("provider", "google"),
        ("code_challenge", code_challenge),
        ("code_challenge_method", "S256"),
        ("prompt", "select_account"),
        ("state", state),  # usamos el verifier como state para correlacionar
    ]
    if redirect_to:
        params.insert(1, ("redirect_to", redirect_to))
    q = "&".join(f"{k}={quote(v, safe='')}" for k, v in params)
    return f"{base}?{q}"


# -----------------------
# API pública para app.py
# -----------------------
def require_google_login():
    """
    Si no hay sesión, muestra botón 'Entrar con Google' y retorna None.
    Si hay sesión válida, retorna dict con {'email','access_token'}.
    """
    supa = _supabase_client()

    # 1) ¿Ya tengo sesión en memoria?
    if st.session_state.get("user_email") and st.session_state.get("access_token"):
        os.environ["OWNER_EMAIL"] = st.session_state["user_email"]
        return {
            "email": st.session_state["user_email"],
            "access_token": st.session_state["access_token"],
        }

    # 2) ¿Volvimos del IdP con ?code=... ?
    qs = st.query_params
    code = qs.get("code")
    if code:
        verifier = st.session_state.get("pkce_verifier") or qs.get("state")
        if not verifier:
            st.error("No se pudo completar el login: falta el code_verifier (PKCE). Vuelve a iniciar sesión.")
        else:
            try:
                # Intercambio del auth_code por la sesión
                resp = supa.auth.exchange_code_for_session(
                    {"auth_code": code, "code_verifier": verifier}
                )
                # En v2, la sesión puede quedar en resp.session o en el cliente
                session = getattr(resp, "session", None) or supa.auth.get_session()
                if session and getattr(session, "user", None):
                    email = session.user.email
                    token = session.access_token
                    st.session_state["user_email"] = email
                    st.session_state["access_token"] = token
                    os.environ["OWNER_EMAIL"] = email
                    # Limpiamos la URL para evitar re-intentos con el mismo code
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error("No llegó la sesión desde Supabase tras el intercambio.")
            except Exception as e:
                st.error(f"No se pudo completar el login: {e}")

    # 3) Construir URL de autorización (cuando aún no hay sesión)
    verifier, challenge = _new_pkce_pair()
    st.session_state["pkce_verifier"] = verifier

    supabase_url = st.secrets["SUPABASE_URL"]
    app_url = _app_url()

    # ⚠️ En Streamlit Cloud NO enviamos redirect_to (evita loops); Supabase usará su Site URL.
    redirect_to = None if "streamlit.app" in app_url else app_url

    auth_url = _authorize_url(supabase_url, challenge, verifier, redirect_to)

    # (Opcional de debug)
    # st.caption(f"APP_URL: {app_url}")
    # st.caption(f"QS: {dict(st.query_params)}")
    # st.caption(f"Auth to: {auth_url}")

    st.info("Inicia sesión con Google para continuar")
    st.link_button("Entrar con Google", auth_url, use_container_width=True)
    return None


def sign_out():
    """Cierra sesión en Supabase y limpia el estado local."""
    try:
        _supabase_client().auth.sign_out()
    except Exception:
        pass
    for k in ("user_email", "access_token", "pkce_verifier"):
        st.session_state.pop(k, None)
    st.query_params.clear()
    st.rerun()
