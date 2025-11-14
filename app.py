# app.py
# -----------------------------------------
# Entrenamientos TyH — Registro simple
# -----------------------------------------
import io
import json
import math
import datetime as dt
from typing import List, Dict

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from auth import require_login, sign_out
from db import get_backend
from pdf_utils import build_invoice_pdf  # debe devolver bytes (PDF)

# ---------------------------
# Utilidades de formato/fechas
# ---------------------------
MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]
MES_TO_NUM = {m: i + 1 for i, m in enumerate(MESES_ES)}

def format_cop(n: int) -> str:
    try:
        v = int(n)
    except Exception:
        return "$0"
    s = f"{v:,}".replace(",", ".")
    return f"${s}"

def month_start_end(year: int, month: int):
    start = dt.datetime(year, month, 1, 0, 0, 0)
    if month == 12:
        end = dt.datetime(year + 1, 1, 1, 0, 0, 0) - dt.timedelta(seconds=1)
    else:
        end = dt.datetime(year, month + 1, 1, 0, 0, 0) - dt.timedelta(seconds=1)
    return start, end

def normalize_name(raw: str) -> str:
    if not raw:
        return ""
    s = " ".join(raw.strip().split())
    s = s.title()
    return s

def backend_name(b) -> str:
    # best-effort label
    return getattr(b, "label", None) or getattr(b, "name", None) or (
        "Supabase" if "SUPABASE_URL" in st.secrets else "SQLite"
    )

# ---------------
# Carga de datos
# ---------------
def load_clients(backend) -> List[Dict]:
    try:
        return backend.list_clients()  # [{'id','name','payment_method','account','phone','note'}]
    except Exception as e:
        st.error(f"No se pudieron cargar clientes: {e}")
        return []

def load_sessions_month(backend, year: int, month: int) -> List[Dict]:
    start, end = month_start_end(year, month)
    try:
        items = backend.list_sessions_between(
            start.isoformat(), end.isoformat()
        )
        # Se espera [{'id','client_id','client','ts_iso','amount_int'}]
        return items
    except Exception as e:
        st.error(f"No se pudieron cargar clases del mes: {e}")
        return []

def monthly_summary(rows: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Cliente", "Clases", "Monto"])
    # campos esperados: client (str) y amount_int (int)
    df["Cliente"] = df.get("client", "")
    df["Monto"] = df.get("amount_int", 0).astype(int)
    grp = df.groupby("Cliente", dropna=False, as_index=False).agg(
        Clases=("Cliente", "count"),
        Monto=("Monto", "sum")
    )
    grp = grp.sort_values(["Cliente"]).reset_index(drop=True)
    return grp

def to_calendar(rows: List[Dict]) -> Dict[int, List[Dict]]:
    cal = {d: [] for d in range(1, 32)}
    for r in rows:
        ts = r.get("ts_iso")
        try:
            dtm = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(None)
        except Exception:
            # best effort
            dtm = dt.datetime.fromisoformat(ts[:19])
        day = dtm.day
        cal.setdefault(day, []).append(r | {"_dt": dtm})
    return cal

# ----------------
# Export helpers
# ----------------
def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

# ----------------
# UI components
# ----------------
def copy_payment_button(cli: Dict):
    pay_txt = f"{cli.get('payment_method','') or ''} · {cli.get('account','') or ''}".strip(" ·")
    if not pay_txt:
        return
    components.html(f"""
    <button id="copyBtn" style="padding:8px 12px;border-radius:8px;border:1px solid #444;cursor:pointer;">
      Copiar método de pago
    </button>
    <span id="copyOk" style="margin-left:8px;color:#4ade80;display:none;">¡Copiado!</span>
    <script>
      const txt = {pay_txt.__repr__()};
      const btn = document.getElementById("copyBtn");
      if (btn) {{
        btn.onclick = async () => {{
          try {{
            await navigator.clipboard.writeText(txt);
            const ok = document.getElementById("copyOk");
            if (ok) {{
              ok.style.display = "inline";
              setTimeout(()=> ok.style.display = "none", 1500);
            }}
          }} catch (e) {{}}
        }};
      }}
    </script>
    """, height=40)

# =========================
#  APP
# =========================
st.set_page_config(page_title="Entrenamientos TyH", page_icon="💪", layout="wide")

# --- Gate simple con código de acceso ---
user = require_login()
if not user:
    st.stop()

st.sidebar.success(f"Sesión: {user['email']}")
if st.sidebar.button("Salir"):
    sign_out()


# --- Backend ---
backend = get_backend()
st.caption(f"Backend activo: **{backend_name(backend)}** • Moneda: **COP** • Formato: **$30.000**")

# --- Parámetros Año/Mes (query params para persistir) ---
now = dt.datetime.now()
qp = st.query_params
try:
    q_year = int(qp.get("y")) if qp.get("y") else now.year
except Exception:
    q_year = now.year
q_month_name = qp.get("m") if qp.get("m") in MESES_ES else MESES_ES[now.month - 1]

colA, colB = st.columns([1, 2])
with colA:
    year = st.number_input("Año", min_value=2020, max_value=2100, step=1, value=q_year)
with colB:
    mes_name = st.selectbox("Mes", MESES_ES, index=MESES_ES.index(q_month_name))

# Persistimos en URL
st.query_params.update({"y": str(year), "m": mes_name})
month = MES_TO_NUM[mes_name]

# -------------
# Tabs
# -------------
tab1, tab2, tab3 = st.tabs(["📋 Registro & Resumen", "📆 Calendario", "👥 Clientes & cobros"])

# ============
# TAB 1: Registro y Resumen
# ============
with tab1:
    st.subheader("Registrar una clase")

    # --- Clientes: selector + opción de nuevo ---
    clients = load_clients(backend)
    names = ["(Escribir nombre nuevo)"] + [c.get("name", "") for c in clients]
    sel = st.selectbox("Cliente", names, index=0)
    new_name = ""
    if sel == "(Escribir nombre nuevo)":
        new_name = st.text_input("Nuevo nombre", placeholder="Nombre y apellido")
    valor = st.number_input("Valor de la clase (COP)", min_value=0, step=1000, value=30000)
    c1, c2 = st.columns(2)
    with c1:
        f = st.date_input("Fecha", value=now.date())
    with c2:
        t = st.time_input("Hora", value=dt.time(hour=18, minute=0))

    if st.button("Guardar clase", use_container_width=True):
        try:
            # 1) Resolver cliente
            if sel != "(Escribir nombre nuevo)":
                cli_name = normalize_name(sel)
                cli = next((c for c in clients if normalize_name(c.get("name","")) == cli_name), None)
                if not cli:
                    # por si cambiaron lista; creamos
                    backend.upsert_client(cli_name, None, None, None, None)
                    clients = load_clients(backend)
                    cli = next((c for c in clients if normalize_name(c.get("name","")) == cli_name), None)
            else:
                cli_name = normalize_name(new_name)
                if not cli_name:
                    st.warning("Escribe un nombre de cliente.")
                    st.stop()
                backend.upsert_client(cli_name, None, None, None, None)
                clients = load_clients(backend)
                cli = next((c for c in clients if normalize_name(c.get("name","")) == cli_name), None)

            client_id = cli.get("id") if cli else None

            # 2) Timestamp y registro
            ts = dt.datetime.combine(f, t)
            ts_iso = ts.isoformat()

            # diferentes firmas según tu db.py
            try:
                backend.add_session(client_id, ts_iso, int(valor))
            except TypeError:
                backend.add_session(cli_name, ts_iso, int(valor))

            st.success("Clase registrada.")
        except Exception as e:
            st.error(f"No se pudo guardar: {e}")

    st.markdown("---")
    st.subheader(f"Clases del mes: {mes_name} {year}")

    rows = load_sessions_month(backend, year, month)

    # Tabla amigable
    def _rows_to_df(_rows):
        out = []
        for i, r in enumerate(sorted(_rows, key=lambda x: x.get("ts_iso")), start=1):
            ts = r.get("ts_iso")
            try:
                dtt = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(None)
            except Exception:
                dtt = dt.datetime.fromisoformat(ts[:19])
            out.append({
                "N°": i,
                "ID": r.get("id"),
                "Cliente": r.get("client"),
                "Fecha": dtt.strftime("%d/%m/%Y"),
                "Hora": dtt.strftime("%H:%M"),
                "Valor": format_cop(int(r.get("amount_int", 0))),
            })
        return pd.DataFrame(out)

    df_mes = _rows_to_df(rows)
    st.dataframe(df_mes.drop(columns=["ID"], errors="ignore"), use_container_width=True,hide_index=True)


    col_d1, col_d2, col_d3 = st.columns(3)
    with col_d1:
        if not df_mes.empty:
            st.download_button(
                "⭳ Exportar clases del mes (CSV)",
                data=df_to_csv_bytes(df_mes.drop(columns=["ID"])),
                file_name=f"clases_{year}_{month:02d}.csv",
                mime="text/csv",
                use_container_width=True,
            )
    with col_d2:
        if not df_mes.empty:
            st.caption(f"Total clases: **{len(df_mes)}**")
    with col_d3:
        if not df_mes.empty:
            total_mes = sum(int(r.get("amount_int", 0)) for r in rows)
            st.caption(f"Total a cobrar: **{format_cop(total_mes)}**")

    # Borrado (por ID)
    if not df_mes.empty:
        with st.expander("Borrar un registro"):
            id_to_del = st.selectbox("Selecciona el N° de la fila a borrar", df_mes["N°"].tolist())
            if st.button("Borrar", type="primary"):
                try:
                    real_id = df_mes.loc[df_mes["N°"] == id_to_del, "ID"].values[0]
                    backend.delete_session(real_id)
                    st.success("Registro borrado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo borrar: {e}")

    st.markdown("---")
    st.subheader(f"Resumen por persona (mes seleccionado)")

    df_res = monthly_summary(rows)
    if df_res.empty:
        st.info("Sin clases registradas este mes.")
    else:
        df_show = df_res.copy()
        df_show["Monto"] = df_show["Monto"].apply(format_cop)
        st.dataframe(df_show, use_container_width=True, hide_index=True)
        st.download_button(
            "⭳ Exportar resumen (CSV)",
            data=df_to_csv_bytes(df_res),
            file_name=f"resumen_{year}_{month:02d}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("---")
    st.subheader("Actualizar estado de pago mensual")

    clients = load_clients(backend)
    sel_cli = st.selectbox("Cliente", [c.get("name", "") for c in clients]) if clients else None
    if sel_cli:
        cli = next((c for c in clients if c.get("name","") == sel_cli), None)
        client_id = cli.get("id") if cli else None

        # total del cliente en el mes
        total_cli = sum(int(r.get("amount_int", 0)) for r in rows if r.get("client") == sel_cli)
        st.caption(f"Total del mes para **{sel_cli}**: {format_cop(total_cli)}")

        paid = st.checkbox("Pagado")
        paid_on = st.date_input("Fecha de pago", value=now.date())
        if st.button("Guardar estado de pago", use_container_width=True):
            try:
                backend.set_month_payment(client_id, year, month, bool(paid), paid_on.isoformat() if paid else None)
                st.success("Estado de pago actualizado.")
            except Exception as e:
                st.error(f"No se pudo actualizar: {e}")

# ============
# TAB 2: Calendario
# ============
with tab2:
    st.subheader(f"Calendario — {mes_name.capitalize()} {year}")
    rows = load_sessions_month(backend, year, month)
    cal = to_calendar(rows)

    # Render simple: semana Lun-Dom
    start, _ = month_start_end(year, month)
    first_weekday = (start.weekday())  # 0=Lun
    days_in_month = max(d for d in cal.keys() if len(cal[d]) or True)
    grid = []
    week = [""] * first_weekday
    for d in range(1, 32):
        try:
            dt.date(year, month, d)
        except ValueError:
            break
        week.append(d)
        if len(week) == 7:
            grid.append(week)
            week = []
    if week:
        week += [""] * (7 - len(week))
        grid.append(week)

    # Pintamos
    for wk in grid:
        cols = st.columns(7)
        for i, day in enumerate(wk):
            with cols[i]:
                if day == "":
                    st.write("")
                    continue
                st.markdown(f"**{day:02d}**")
                items = sorted(cal.get(day, []), key=lambda r: r.get("ts_iso"))
                tot_day = 0
                for it in items:
                    _dt = it.get("_dt")
                    hhmm = _dt.strftime("%H:%M") if _dt else ""
                    st.caption(f"{hhmm} · {it.get('client','')} · {format_cop(int(it.get('amount_int',0)))}")
                    tot_day += int(it.get("amount_int", 0))
                if tot_day:
                    st.write(f"**Total día: {format_cop(tot_day)}**")

# ============
# TAB 3: Clientes & cobros
# ============
with tab3:
    st.subheader("Gestión de clientes")

    clients = load_clients(backend)
    df_cli = pd.DataFrame(clients)
    if not df_cli.empty:
        show = df_cli[["name", "phone", "payment_method", "account", "note"]].rename(columns={
            "name":"Nombre", "phone":"Teléfono", "payment_method":"Método de pago",
            "account":"Cuenta/Alias", "note":"Nota"
        })
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.download_button(
            "⭳ Exportar clientes (CSV)",
            data=df_to_csv_bytes(show),
            file_name="clientes.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.info("Aún no tienes clientes.")

    st.markdown("---")
    st.subheader("Crear/Editar cliente")

    col1, col2 = st.columns(2)
    with col1:
        cli_name = st.text_input("Nombre (único, normalizado)", "")
        phone = st.text_input("Teléfono (opcional)", "")
        method = st.selectbox("Método de pago", ["", "Nequi", "Bancolombia", "Nu", "Lulo", "Otro"])
    with col2:
        account = st.text_input("Cuenta/Alias", "")
        note = st.text_area("Nota (opcional)", "", height=80)

    if st.button("Guardar cliente", use_container_width=True):
        try:
            backend.upsert_client(normalize_name(cli_name), phone or None, method or None, account or None, note or None)
            st.success("Cliente guardado.")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo guardar el cliente: {e}")

    if clients:
        with st.expander("Borrar cliente"):
            del_name = st.selectbox("Selecciona el cliente a borrar", [c.get("name","") for c in clients])
            if st.button("Borrar cliente definitivamente", type="primary"):
                try:
                    cli = next((c for c in clients if c.get("name","")==del_name), None)
                    backend.delete_client(cli.get("id"))
                    st.success("Cliente borrado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo borrar: {e}")

    st.markdown("---")
    st.subheader("Generar cuenta de cobro mensual")

    clients = load_clients(backend)
    if not clients:
        st.info("Primero crea clientes.")
    else:
        ccol1, ccol2, ccol3 = st.columns(3)
        with ccol1:
            cli_name = st.selectbox("Cliente", [c.get("name","") for c in clients])
        with ccol2:
            inv_year = st.number_input("Año", min_value=2020, max_value=2100, value=year, step=1)
        with ccol3:
            inv_mes_name = st.selectbox("Mes", MESES_ES, index=MESES_ES.index(mes_name), key="mes_invoice")

        inv_month = MES_TO_NUM[inv_mes_name]
        # datos cliente
        cli = next((c for c in clients if c.get("name","")==cli_name), None)
        if cli:
            st.caption(f"Método: **{cli.get('payment_method','')}** — Cuenta/Alias: **{cli.get('account','')}**")
            copy_payment_button(cli)

        # sesiones del mes/cliente
        all_rows = load_sessions_month(backend, inv_year, inv_month)
        items_cli = [r for r in all_rows if r.get("client")==cli_name]
        det = []
        total = 0
        for r in sorted(items_cli, key=lambda x: x.get("ts_iso")):
            ts = r.get("ts_iso")
            try:
                dtt = dt.datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(None)
            except Exception:
                dtt = dt.datetime.fromisoformat(ts[:19])
            det.append({"fecha": dtt.strftime("%d/%m/%Y"), "hora": dtt.strftime("%H:%M"), "valor": int(r.get("amount_int",0))})
            total += int(r.get("amount_int",0))

        if items_cli:
            st.write(f"Total clases: **{len(items_cli)}** — Total a cobrar: **{format_cop(total)}**")
            # CSV detalle
            df_det = pd.DataFrame([{"Fecha":d["fecha"], "Hora":d["hora"], "Valor":format_cop(d["valor"])} for d in det])
            st.download_button(
                "⭳ Descargar detalle (CSV)",
                data=df_to_csv_bytes(df_det),
                file_name=f"cuenta_{cli_name}_{inv_year}_{inv_month:02d}.csv",
                mime="text/csv",
                use_container_width=True,
            )

            # PDF cuenta (plantilla simple en pdf_utils.build_invoice_pdf)
            if st.button("⭳ Descargar cuenta de cobro (PDF)", use_container_width=True):
                try:
                    invoice = {
                        "client": cli_name,
                        "year": inv_year,
                        "month": inv_month,
                        "month_name": inv_mes_name,
                        "items": det,
                        "total": total,
                        "method": cli.get("payment_method",""),
                        "account": cli.get("account",""),
                        "created_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    try:
                        pdf_bytes = build_invoice_pdf(invoice)  # firma recomendada
                    except TypeError:
                        # fallback si tu pdf_utils usa parámetros separados
                        pdf_bytes = build_invoice_pdf(
                            cli_name, inv_year, inv_month, det, total,
                            cli.get("payment_method",""), cli.get("account","")
                        )
                    st.download_button(
                        "Descargar PDF",
                        data=pdf_bytes,
                        file_name=f"cuenta_{cli_name}_{inv_year}_{inv_month:02d}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                except Exception as e:
                    st.error(f"No se pudo generar el PDF: {e}")
        else:
            st.info("Ese cliente no tiene clases registradas en el mes seleccionado.")
