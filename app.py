import os
from datetime import datetime, date, time, timedelta
from io import BytesIO
import pandas as pd
import streamlit as st

# --- compatibilidad rerun (Streamlit nuevo/antiguo) ---
def _rerun():
    
    try:
        st.rerun()  # versiones nuevas (1.27+)
    except AttributeError:
        # fallback para versiones antiguas
        _rerun()


from db import get_backend
from utils import (
    MESES_ES, MESES_ES_MAP, MESES_NUM_TO_ES,
    PAGO_METODOS, DEFAULT_CLASE_COP,
    normalize_name, name_norm_key, format_cop,
    combine_date_time, ym_to_label
)
from pdf_utils import build_invoice_pdf

st.set_page_config(page_title="Entrenos | Registro y cobros", page_icon="💪", layout="centered")

# --- Protección con código simple (para Cloud/local) ---
import os
import streamlit as st

def require_access_code():
    # 1) Preferir st.secrets en Cloud
    code_secret = ""
    try:
        code_secret = st.secrets.get("ACCESS_CODE", "")
    except Exception:
        code_secret = ""

    # 2) Fallback a variable de entorno
    if not code_secret:
        code_secret = os.getenv("ACCESS_CODE", "")

    # (debug opcional) ver si está activo: quita esta línea al final
    st.caption(f"Protección por código: {'ON' if code_secret else 'OFF'}")

    if not code_secret:
        return  # sin código configurado, no bloquea

    user_code = st.text_input("Código de acceso", type="password", placeholder="Ingresa el código")
    if user_code != code_secret:
        st.stop()

require_access_code()





# ---------- Estado y backend ----------
backend, backend_name = get_backend()

if "year" not in st.session_state:
    today = datetime.now()
    st.session_state.year = today.year
    st.session_state.month = today.month
if "pending_delete_session" not in st.session_state:
    st.session_state.pending_delete_session = None
if "pending_delete_client" not in st.session_state:
    st.session_state.pending_delete_client = None

st.markdown(
    """
    <style>
      /* Inputs un poco más grandes para móvil */
      .stTextInput input, .stNumberInput input, .stDateInput input, .stTimeInput input, .stSelectbox > div > div {
         font-size: 18px !important;
      }
      .stButton>button {
         font-size: 18px !important;
         padding: 0.5rem 1rem;
      }
      .tiny { font-size: 12px; color: #666; }
      .daybox {
        border: 1px solid #e6e6e6; border-radius: 8px; padding: 8px; min-height: 110px;
      }
      .daytotal { text-align:right; font-weight: 600; margin-top:6px;}
      .muted { color:#888; }
    </style>
    """,
    unsafe_allow_html=True
)

st.caption(f"Backend activo: **{backend_name}**  •  Moneda: **COP**  •  Formato: $30.000")

# ---------- Helpers ----------
def month_range(year:int, month:int):
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year+1, 1, 1)
    else:
        end = datetime(year, month+1, 1)
    return start, end

def load_sessions_month(year:int, month:int):
    start, end = month_range(year, month)
    items = backend.list_sessions_between(start.isoformat(), end.isoformat())
    # enriquecer con fecha/hora muestran
    for it in items:
        ts = datetime.fromisoformat(it["ts_iso"])
        it["fecha"] = ts.date()
        it["hora"] = ts.strftime("%H:%M")
        it["fecha_str"] = ts.strftime("%d/%m/%Y")
        it["amount_str"] = format_cop(it["amount_int"])
    return items

def month_summary(year:int, month:int):
    items = load_sessions_month(year, month)
    df = pd.DataFrame(items)
    if df.empty:
        return pd.DataFrame(columns=["Cliente","Clases","Monto","Estado mes"])
    grp = df.groupby("client_name").agg(Clases=("id","count"), Monto=("amount_int","sum")).reset_index()
    # estado de pago por cliente
    estados = []
    # necesitamos ids: mapeo nombre->id
    clients = {c["name"]: c for c in backend.list_clients()}
    for _, row in grp.iterrows():
        c = clients.get(row["client_name"])
        est = backend.get_month_payment(c["id"], year, month) if c else dict(paid=False)
        estados.append("Pagado" if est.get("paid") else "Pendiente")
    grp["Monto"] = grp["Monto"].apply(format_cop)
    grp.rename(columns={"client_name":"Cliente"}, inplace=True)
    grp["Estado mes"] = estados
    return grp

def list_clients_simple():
    return backend.list_clients()

def ensure_client_exists(name_input, phone=None, method=None, account=None, note=None):
    ex = backend.get_client_by_name_ci(name_input)
    if ex:
        return ex["id"], ex
    # crear
    cid = backend.add_client({
        "name": name_input,
        "phone": phone,
        "payment_method": method,
        "account": account,
        "note": note
    })
    c = backend.get_client_by_name_ci(name_input)
    return cid, c

def csv_bytes_from_df(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

# ---------- Filtros globales Año/Mes ----------
coly, colm = st.columns(2)
with coly:
    y = st.number_input("Año", min_value=2020, max_value=2100, value=st.session_state.year, step=1)
with colm:
    m_label = st.selectbox("Mes", options=[MESES_NUM_TO_ES[i] for i in range(1,13)], index=st.session_state.month-1)
m = list(MESES_NUM_TO_ES.keys())[list(MESES_NUM_TO_ES.values()).index(m_label)]
st.session_state.year, st.session_state.month = int(y), int(m)

st.divider()

tab1, tab2, tab3 = st.tabs(["📋 Registro & Resumen", "📆 Calendario", "👥 Clientes & cobros"])

# =========================================================
# TAB 1: Registro & Resumen
# =========================================================
with tab1:
    st.subheader("Registrar una clase")

    clients = list_clients_simple()
    client_names = [c["name"] for c in clients]
    opts = ["(Escribir nombre nuevo)"] + client_names
    sel = st.selectbox("Cliente", options=opts, index=0)
    new_name = ""
    if sel == "(Escribir nombre nuevo)":
        new_name = st.text_input("Nuevo nombre", placeholder="Nombre y apellido")
    value_int = st.number_input("Valor de la clase (COP)", min_value=0, max_value=10_000_000, value=DEFAULT_CLASE_COP, step=1000)
    cold, colt = st.columns(2)
    with cold:
        d = st.date_input("Fecha", value=date.today(), format="DD/MM/YYYY")
    with colt:
        t = st.time_input("Hora", value=time(18,0), step=300)

    if st.button("Guardar clase", use_container_width=True):
        try:
            if sel == "(Escribir nombre nuevo)":
                if not new_name.strip():
                    st.error("Escribe el nombre del cliente.")
                else:
                    name_ok = normalize_name(new_name)
                    cid, _c = ensure_client_exists(name_ok)
            else:
                cid = [c for c in clients if c["name"] == sel][0]["id"]

            ts = combine_date_time(d, t).isoformat()
            backend.log_session(cid, ts, int(value_int))
            st.success("Clase registrada correctamente.")
        except Exception as e:
            st.error(f"Ocurrió un error al guardar: {e}")

    st.markdown("### Clases del mes: " + ym_to_label(st.session_state.year, st.session_state.month))
    items = load_sessions_month(st.session_state.year, st.session_state.month)

    if items:
        df = pd.DataFrame([{
            "N°": i+1,
            "ID": it["id"],
            "Cliente": it["client_name"],
            "Fecha": it["fecha_str"],
            "Hora": it["hora"],
            "Valor": it["amount_str"],
        } for i,it in enumerate(items)])
        st.dataframe(df.drop(columns=["ID"]), use_container_width=True, hide_index=True)

        # Borrado con confirmación
        st.markdown("#### Borrar un registro")
        cols = st.columns(3)
        with cols[0]:
            to_del = st.selectbox("Seleccione N° de la tabla", options=df["N°"].tolist())
        sel_row = df[df["N°"]==to_del].iloc[0]
        with cols[1]:
            if st.button("🗑️ Marcar para borrar"):
                st.session_state.pending_delete_session = int(sel_row["N°"])
        with cols[2]:
            if st.session_state.pending_delete_session == int(sel_row["N°"]):
                if st.button("❗ Confirmar eliminación"):
                    real_id = int(items[to_del-1]["id"])
                    backend.delete_session(real_id)
                    st.session_state.pending_delete_session = None
                    st.success("Registro eliminado.")
                    _rerun()
        # Exportar CSV
        st.download_button("Descargar CSV (clases del mes)", data=csv_bytes_from_df(df.drop(columns=["ID"])), file_name="clases_mes.csv", mime="text/csv")
    else:
        st.info("No hay clases registradas en este mes.")

    st.markdown("### Resumen por persona (mes seleccionado)")
    resumen = month_summary(st.session_state.year, st.session_state.month)
    if not resumen.empty:
        total_clases = resumen["Clases"].astype(int).sum()
        total_monto = sum(int(str(v).replace("$","").replace(".","")) for v in resumen["Monto"])
        st.dataframe(resumen, use_container_width=True, hide_index=True)
        st.markdown(f"**Total de clases:** {total_clases}  •  **Total a cobrar:** {format_cop(total_monto)}")
        st.download_button("Descargar CSV (resumen)", data=csv_bytes_from_df(resumen), file_name="resumen_mes.csv", mime="text/csv")
    else:
        st.info("Sin datos para el resumen en este mes.")

    st.markdown("### Actualizar estado de pago mensual")
    col1, col2, col3 = st.columns(3)
    with col1:
        cli_label = st.selectbox("Cliente", options=[c["name"] for c in clients] or ["—"])
    with col2:
        yy = st.number_input("Año", min_value=2020, max_value=2100, value=st.session_state.year, step=1, key="pay_year")
    with col3:
        mm_label = st.selectbox("Mes", options=MESES_ES, index=st.session_state.month-1, key="pay_month_label")

    if clients:
        cli_id = [c["id"] for c in clients if c["name"]==cli_label][0]
        mm = MESES_ES_MAP[mm_label]
        # total del cliente en ese mes
        items_cli = [it for it in load_sessions_month(yy, mm) if it["client_id"]==cli_id]
        total_cli = sum(it["amount_int"] for it in items_cli)
        st.markdown(f"**Total del cliente en {mm_label} {yy}:** {format_cop(total_cli)}")

        state = backend.get_month_payment(cli_id, yy, mm)
        paid_default = state.get("paid", False)
        paid_on_default = state.get("paid_on_iso")
        colp, cold = st.columns(2)
        with colp:
            paid_flag = st.checkbox("Pagado", value=paid_default)
        with cold:
            paid_on = st.date_input("Fecha de pago", value=date.fromisoformat(paid_on_default[:10]) if paid_on_default else date.today(), format="DD/MM/YYYY")
        if st.button("Guardar estado de pago"):
            backend.set_month_payment(cli_id, yy, mm, paid_flag, paid_on.isoformat() if paid_flag else None)
            st.success("Estado de pago actualizado.")


# =========================================================
# TAB 2: Calendario
# =========================================================
with tab2:
    st.subheader("Calendario mensual")
    y, m = st.session_state.year, st.session_state.month
    items = load_sessions_month(y, m)

    # agrupar por día
    by_day = {}
    for it in items:
        d = it["fecha"].day
        by_day.setdefault(d, []).append(it)

    # construir semanas Lun-Dom
    # primer día del mes
    first = date(y, m, 1)
    first_weekday = (first.weekday())  # 0=Mon ... 6=Sun
    # total de días
    if m == 12:
        next_first = date(y+1,1,1)
    else:
        next_first = date(y, m+1, 1)
    days_in_month = (next_first - first).days

    # filas de semanas
    day_ptr = 1
    # primera fila
    cols = st.columns(7)
    for i in range(7):
        with cols[i]:
            if i < first_weekday:
                st.markdown("&nbsp;", unsafe_allow_html=True)
            else:
                dnum = day_ptr
                st.markdown(f"**{dnum}**")
                if dnum in by_day:
                    total_d = 0
                    for it in by_day[dnum]:
                        total_d += it["amount_int"]
                        st.markdown(f"- {it['hora']} · {it['client_name']} · {format_cop(it['amount_int'])}")
                    st.markdown(f"<div class='daytotal'>Total: {format_cop(total_d)}</div>", unsafe_allow_html=True)
                else:
                    st.markdown("<span class='muted'>—</span>", unsafe_allow_html=True)
                day_ptr += 1
                if day_ptr > days_in_month: break

    # siguientes filas
    while day_ptr <= days_in_month:
        cols = st.columns(7)
        for i in range(7):
            with cols[i]:
                if day_ptr <= days_in_month:
                    dnum = day_ptr
                    st.markdown(f"**{dnum}**")
                    if dnum in by_day:
                        total_d = 0
                        for it in by_day[dnum]:
                            total_d += it["amount_int"]
                            st.markdown(f"- {it['hora']} · {it['client_name']} · {format_cop(it['amount_int'])}")
                        st.markdown(f"<div class='daytotal'>Total: {format_cop(total_d)}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<span class='muted'>—</span>", unsafe_allow_html=True)
                    day_ptr += 1


# =========================================================
# TAB 3: Clientes & cobros
# =========================================================
with tab3:
    st.subheader("Gestión de clientes")

    clients = list_clients_simple()
    names = [c["name"] for c in clients]
    choice = st.selectbox("Seleccionar cliente (o crea uno nuevo)", options=["(Nuevo)"] + names)

    if choice == "(Nuevo)":
        cname = st.text_input("Nombre", placeholder="Nombre y apellido")
        cphone = st.text_input("Teléfono (opcional)")
        cmet = st.selectbox("Método de pago", options=PAGO_METODOS, index=0)
        cacc = st.text_input("Cuenta/Alias", placeholder="Alias Nequi, cuenta, etc.")
        cnote = st.text_input("Nota (opcional)")

        if st.button("Crear cliente"):
            if not cname.strip():
                st.error("El nombre es obligatorio.")
            else:
                cid, _ = ensure_client_exists(cname, phone=cphone, method=cmet, account=cacc, note=cnote)
                st.success("Cliente creado o ya existente (normalizado).")
                _rerun()
    else:
        cli = [c for c in clients if c["name"]==choice][0]
        cname = st.text_input("Nombre", value=cli["name"])
        cphone = st.text_input("Teléfono", value=cli.get("phone") or "")
        cmet = st.selectbox("Método de pago", options=PAGO_METODOS, index=(PAGO_METODOS.index(cli["payment_method"]) if cli.get("payment_method") in PAGO_METODOS else 0))
        cacc = st.text_input("Cuenta/Alias", value=cli.get("account") or "")
        cnote = st.text_input("Nota", value=cli.get("note") or "")

        colu1, colu2 = st.columns(2)
        with colu1:
            if st.button("Guardar cambios"):
                backend.update_client(cli["id"], {"name": cname, "phone": cphone, "payment_method": cmet, "account": cacc, "note": cnote})
                st.success("Cliente actualizado.")
                _rerun()
        with colu2:
            if st.button("🗑️ Borrar cliente"):
                st.session_state.pending_delete_client = cli["id"]
        if st.session_state.pending_delete_client == cli["id"]:
            if st.button("❗ Confirmar eliminación del cliente y sus datos"):
                backend.delete_client(cli["id"])
                st.session_state.pending_delete_client = None
                st.success("Cliente eliminado.")
                _rerun()

    st.markdown("### Exportar clientes")
    if clients:
        dfc = pd.DataFrame(clients)[["name","phone","payment_method","account","note","created_at"]]
        st.download_button("Descargar CSV (clientes)", data=dfc.to_csv(index=False).encode("utf-8"), file_name="clientes.csv", mime="text/csv")
    else:
        st.caption("No hay clientes aún.")

    st.divider()
    st.subheader("Generar cuenta de cobro (por cliente y mes)")

    clients = list_clients_simple()
    if not clients:
        st.info("Primero crea un cliente.")
    else:
        csel = st.selectbox("Cliente", options=[c["name"] for c in clients], key="inv_cli")
        yy = st.number_input("Año", min_value=2020, max_value=2100, value=st.session_state.year, step=1, key="inv_y")
        mlabel = st.selectbox("Mes", options=MESES_ES, index=st.session_state.month-1, key="inv_m")
        mm = MESES_ES_MAP[mlabel]
        cli = [c for c in clients if c["name"]==csel][0]
        # clases del mes por cliente
        items_all = load_sessions_month(yy, mm)
        items_cli = [it for it in items_all if it["client_id"]==cli["id"]]
        total = sum(it["amount_int"] for it in items_cli)

        st.markdown(f"**Clases:** {len(items_cli)}  •  **Total:** {format_cop(total)}")

        if items_cli:
            # CSV detalle
            df_inv = pd.DataFrame([{"Fecha":it["fecha_str"], "Hora":it["hora"], "Valor":format_cop(it["amount_int"])} for it in items_cli])
            st.download_button("Descargar CSV (cuenta de cobro)", data=df_inv.to_csv(index=False).encode("utf-8"),
                               file_name=f"cuenta_{cli['name']}_{mlabel}_{yy}.csv", mime="text/csv")

            # PDF
            datos_pdf = {
                "cliente": {
                    "name": cli["name"],
                    "phone": cli.get("phone"),
                    "payment_method": cli.get("payment_method"),
                    "account": cli.get("account"),
                    "note": cli.get("note"),
                },
                "year": int(yy),
                "month": int(mm),
                "clases": [{"fecha_str": it["fecha_str"], "hora_str": it["hora"], "valor_int": it["amount_int"]} for it in items_cli],
                "total_int": int(total),
                "hoy_str": datetime.now().strftime("%d/%m/%Y")
            }
            pdf_bytes = build_invoice_pdf(datos_pdf)
            st.download_button("Descargar PDF (cuenta de cobro)", data=pdf_bytes,
                               file_name=f"cuenta_{cli['name']}_{mlabel}_{yy}.pdf", mime="application/pdf")
        else:
            st.caption("No hay clases para ese cliente en el mes seleccionado.")

    st.divider()
    st.subheader("Exportar vistas")
    # Clases del mes (todas)
    items_all = load_sessions_month(st.session_state.year, st.session_state.month)
    if items_all:
        df_all = pd.DataFrame([{
            "Cliente": it["client_name"],
            "Fecha": it["fecha_str"],
            "Hora": it["hora"],
            "Valor": format_cop(it["amount_int"])
        } for it in items_all])
        st.download_button("CSV: clases del mes (todas)", data=df_all.to_csv(index=False).encode("utf-8"),
                           file_name=f"clases_{st.session_state.month}_{st.session_state.year}.csv", mime="text/csv")
    else:
        st.caption("No hay clases en el mes para exportar.")
