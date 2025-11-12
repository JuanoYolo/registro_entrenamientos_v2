from datetime import datetime
import re

MESES_ES = [
    "enero","febrero","marzo","abril","mayo","junio",
    "julio","agosto","septiembre","octubre","noviembre","diciembre"
]
MESES_ES_MAP = {m:i+1 for i,m in enumerate(MESES_ES)}
MESES_NUM_TO_ES = {i+1:m for i,m in enumerate(MESES_ES)}

PAGO_METODOS = ["Nequi","Bancolombia","Nu","Lulo","Otro"]

DEFAULT_CLASE_COP = 30000

def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def normalize_name(name: str) -> str:
    """
    - Trim + colapsar espacios
    - Case-insensitive -> almacenar también name_norm (lower)
    - Presentación en Title Case (pero sin romper acentos)
    """
    base = normalize_spaces(name)
    # Title Case suave (conserva letras como Mc, etc., de forma simple)
    title = " ".join([w.capitalize() for w in base.split(" ")])
    return title

def name_norm_key(name: str) -> str:
    """Clave de unicidad case-insensitive."""
    return normalize_spaces(name).lower()

def format_cop(value) -> str:
    try:
        n = int(round(float(value)))
    except Exception:
        return "$0"
    return f"${n:,}".replace(",", ".")

def combine_date_time(d, t) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second)

def ym_to_label(year: int, month: int) -> str:
    return f"{MESES_NUM_TO_ES.get(month, 'mes')} {year}"

def label_to_month(label: str) -> int:
    return MESES_ES_MAP.get(label.lower(), 1)
