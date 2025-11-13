# auth.py — OAuth Google con PKCE, guardando el verifier en "state"
import os
import base64
import hashlib
from urllib.parse import quote
import streamlit as st
from supabase import create_client, Client


def _supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)

def _app_url() -> str:
    app = ""
    try:
        app = st.secrets.get("APP_URL", "")
    except Exception:
        pass
    if not app:
        app = os.getenv("APP_URL", "http://localhost:8501")
    return app

def _pkce_pair():
    # RFC7636: base64url sin '='
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge

def _authorize_url(supabase_url: str, redirect_to: str, code_challenge: str, state: str) -> str:
    base = f"{supabase_url}/auth/v1/authorize"
    return (
        f"{base}?provider=google"
        f"&redirect_to={quote(redirect_to, safe='')}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&prompt=select_account"
        f"&state={quote(state, safe='')}"
    )

def require_google_login():
    supa = _supabase_client()

    # 0) ¿Ya hay sesión?
    if st.session_state.get("user_email") and st.session_state.get("access_token"):
        os.environ["OWNER_EMAIL"] = st.session_state["user_email"]
        return {
            "email": st.session_state["user_email"],
            "access_token": st.session_state["access_token"],
        }

    # 1) ¿Volvimos con code?
    qs = st.query_params
    code = qs.get("code")
    if code:
        # 1a) Intentar tomar el verifier desde session_state y, si no, desde "state"
        verifier = st.session_state.get("pkce_verifier")
        if not verifier:
            verifier = qs.get("state")  # ← fallback clave
        if not verifier:
            st.error("No se pudo completar el login: falta el code_verifier (PKCE). Por favor, vuelve a iniciar sesión.")
        else:
            try:
                resp = supa.auth.exchange_code_for_session(
                    {"auth_code": code, "code_verifier": verifier}
                )
                session = getattr(resp, "session", None)
                if session is None and isinstance(resp, dict):
                    session = resp.get("session")
                if session is None:
                    session = supa.auth.get_session()

                if session and getattr(session, "user", None):
                    email = session.user.email
                    token = session.access_token
                    st.session_state["user_email"] = email
                    st.session_state["access_token"] = token
                    os.environ["OWNER_EMAIL"] = email
                    # limpiar querystring y rerun
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error("No llegó la sesión desde Supabase tras el intercambio.")
            except Exception as e:
                st.error(f"No se pudo completar el login: {e}")

    # 2) Preparar PKCE y botón de login
    verifier, challenge = _pkce_pair()
    st.session_state["pkce_verifier"] = verifier  # por si vuelve en la misma sesión

    supabase_url = st.secrets["SUPABASE_URL"]
    redirect_to = _app_url()
    auth_url = _authorize_url(supabase_url, redirect_to, challenge, state=verifier)

    st.info("Inicia sesión con Google para continuar")
    st.link_button("Entrar con Google", auth_url, use_container_width=True)
    return None

def sign_out():
    try:
        _supabase_client().auth.sign_out()
    except Exception:
        pass
    st.session_state.pop("user_email", None)
    st.session_state.pop("access_token", None)
    st.session_state.pop("pkce_verifier", None)
    os.environ.pop("OWNER_EMAIL", None)
    st.rerun()
