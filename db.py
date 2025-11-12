import os, json, sqlite3
from datetime import datetime, timedelta
from dateutil import tz
import requests

from utils import name_norm_key, normalize_name, DEFAULT_CLASE_COP

# ---------- Interfaz común ----------

class Backend:
    def list_clients(self):
        raise NotImplementedError

    def get_client_by_name_ci(self, name):
        raise NotImplementedError

    def add_client(self, data):
        raise NotImplementedError

    def update_client(self, client_id, data):
        raise NotImplementedError

    def delete_client(self, client_id):
        raise NotImplementedError

    def log_session(self, client_id, ts_iso, amount_int):
        raise NotImplementedError

    def list_sessions_between(self, start_iso, end_iso):
        raise NotImplementedError

    def delete_session(self, session_id):
        raise NotImplementedError

    def get_month_payment(self, client_id, year, month):
        raise NotImplementedError

    def set_month_payment(self, client_id, year, month, paid: bool, paid_on_iso: str|None):
        raise NotImplementedError

# ---------- SQLite ----------

class SQLiteBackend(Backend):
    def __init__(self, path="entrenos.db"):
        self.path = path
        self._init()

    def _conn(self):
        return sqlite3.connect(self.path, check_same_thread=False)

    def _init(self):
        with self._conn() as con:
            cur = con.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS clients(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              name_norm TEXT NOT NULL UNIQUE,
              phone TEXT,
              payment_method TEXT,
              account TEXT,
              note TEXT,
              created_at TEXT NOT NULL
            )
            """)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_name_norm ON clients(name_norm)")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id INTEGER NOT NULL,
              ts_iso TEXT NOT NULL,
              amount_int INTEGER NOT NULL,
              FOREIGN KEY(client_id) REFERENCES clients(id)
            )
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS monthly_payments(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id INTEGER NOT NULL,
              year INTEGER NOT NULL,
              month INTEGER NOT NULL,
              paid INTEGER NOT NULL DEFAULT 0,
              paid_on_iso TEXT,
              UNIQUE(client_id, year, month),
              FOREIGN KEY(client_id) REFERENCES clients(id)
            )
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS invoices(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id INTEGER NOT NULL,
              year INTEGER NOT NULL,
              month INTEGER NOT NULL,
              total_int INTEGER NOT NULL,
              method TEXT,
              account TEXT,
              classes_json TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY(client_id) REFERENCES clients(id)
            )
            """)
            con.commit()

    # ---- clients ----
    def list_clients(self):
        with self._conn() as con:
            rows = con.execute("SELECT id,name,phone,payment_method,account,note,created_at FROM clients ORDER BY name").fetchall()
        return [dict(id=r[0], name=r[1], phone=r[2], payment_method=r[3], account=r[4], note=r[5], created_at=r[6]) for r in rows]

    def get_client_by_name_ci(self, name):
        key = name_norm_key(name)
        with self._conn() as con:
            r = con.execute("SELECT id,name,phone,payment_method,account,note FROM clients WHERE name_norm=?", (key,)).fetchone()
        if not r: return None
        return dict(id=r[0], name=r[1], phone=r[2], payment_method=r[3], account=r[4], note=r[5])

    def add_client(self, data):
        name = normalize_name(data["name"])
        key = name_norm_key(name)
        now = datetime.utcnow().isoformat()
        with self._conn() as con:
            try:
                cur = con.execute("""
                  INSERT INTO clients(name,name_norm,phone,payment_method,account,note,created_at)
                  VALUES (?,?,?,?,?,?,?)
                """, (name, key, data.get("phone"), data.get("payment_method"), data.get("account"), data.get("note"), now))
                con.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                # ya existe
                r = con.execute("SELECT id FROM clients WHERE name_norm=?", (key,)).fetchone()
                return r[0] if r else None

    def update_client(self, client_id, data):
        # Si cambia el nombre, mantener unicidad por name_norm
        sets, vals = [], []
        if "name" in data and data["name"]:
            nm = normalize_name(data["name"])
            sets += ["name=?", "name_norm=?"]
            vals += [nm, name_norm_key(nm)]
        for k in ["phone","payment_method","account","note"]:
            if k in data:
                sets.append(f"{k}=?")
                vals.append(data.get(k))
        if not sets: return
        vals.append(client_id)
        with self._conn() as con:
            con.execute(f"UPDATE clients SET {','.join(sets)} WHERE id=?", tuple(vals))
            con.commit()

    def delete_client(self, client_id):
        with self._conn() as con:
            # Opcional: borrar sesiones y pagos asociados
            con.execute("DELETE FROM sessions WHERE client_id=?", (client_id,))
            con.execute("DELETE FROM monthly_payments WHERE client_id=?", (client_id,))
            con.execute("DELETE FROM invoices WHERE client_id=?", (client_id,))
            con.execute("DELETE FROM clients WHERE id=?", (client_id,))
            con.commit()

    # ---- sessions ----
    def log_session(self, client_id, ts_iso, amount_int):
        with self._conn() as con:
            cur = con.execute("INSERT INTO sessions(client_id,ts_iso,amount_int) VALUES(?,?,?)",
                              (client_id, ts_iso, int(amount_int or DEFAULT_CLASE_COP)))
            con.commit()
            return cur.lastrowid

    def list_sessions_between(self, start_iso, end_iso):
        with self._conn() as con:
            rows = con.execute("""
              SELECT s.id, s.client_id, c.name, s.ts_iso, s.amount_int
              FROM sessions s JOIN clients c ON c.id=s.client_id
              WHERE s.ts_iso >= ? AND s.ts_iso < ?
              ORDER BY s.ts_iso ASC
            """, (start_iso, end_iso)).fetchall()
        out = []
        for r in rows:
            out.append(dict(
                id=r[0], client_id=r[1], client_name=r[2], ts_iso=r[3], amount_int=r[4]
            ))
        return out

    def delete_session(self, session_id):
        with self._conn() as con:
            con.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            con.commit()

    # ---- monthly payments ----
    def get_month_payment(self, client_id, year, month):
        with self._conn() as con:
            r = con.execute("""
              SELECT paid, paid_on_iso FROM monthly_payments
              WHERE client_id=? AND year=? AND month=?
            """, (client_id, year, month)).fetchone()
        if not r: return dict(paid=False, paid_on_iso=None)
        return dict(paid=bool(r[0]), paid_on_iso=r[1])

    def set_month_payment(self, client_id, year, month, paid: bool, paid_on_iso: str|None):
        with self._conn() as con:
            # UPSERT
            cur = con.execute("""
              INSERT INTO monthly_payments(client_id,year,month,paid,paid_on_iso)
              VALUES(?,?,?,?,?)
              ON CONFLICT(client_id,year,month) DO UPDATE SET
                paid=excluded.paid, paid_on_iso=excluded.paid_on_iso
            """, (client_id, year, month, int(bool(paid)), paid_on_iso))
            con.commit()


# ---------- Supabase (REST PostgREST) ----------

class SupabaseBackend(Backend):
    def __init__(self, url, anon_key):
        self.base = url.rstrip("/") + "/rest/v1"
        self.key = anon_key
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # sanity check: si falla, lo capturará get_backend()
        _ = self.list_clients()

    def _get(self, path, params=None):
        r = requests.get(self.base + path, headers=self.headers, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _post(self, path, data, prefer=None):
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        r = requests.post(self.base + path, headers=headers, data=json.dumps(data), timeout=20)
        r.raise_for_status()
        return r.json() if r.text else None

    def _patch(self, path, data, params=None, prefer=None):
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        r = requests.patch(self.base + path, headers=headers, params=params, data=json.dumps(data), timeout=20)
        r.raise_for_status()
        return r.json() if r.text else None

    def _delete(self, path, params=None):
        headers = dict(self.headers)
        headers["Prefer"] = "return=minimal"
        r = requests.delete(self.base + path, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        return True

    # ---- clients ----
    def list_clients(self):
        return self._get("/clients", params={"select":"id,name,phone,payment_method,account,note,created_at","order":"name.asc"})

    def get_client_by_name_ci(self, name):
        # No hay equals case-insensitive; traemos todos y comparamos en código (escala para pocos clientes)
        allc = self.list_clients()
        key = name_norm_key(name)
        for c in allc:
            if name_norm_key(c["name"]) == key:
                return c
        return None

    def add_client(self, data):
        # evitar duplicados manualmente
        ex = self.get_client_by_name_ci(data["name"])
        if ex:
            return ex["id"]
        payload = [{
            "name": normalize_name(data["name"]),
            "phone": data.get("phone"),
            "payment_method": data.get("payment_method"),
            "account": data.get("account"),
            "note": data.get("note"),
            "created_at": datetime.utcnow().isoformat()
        }]
        resp = self._post("/clients", payload, prefer="return=representation")
        return resp[0]["id"]

    def update_client(self, client_id, data):
        payload = {}
        if "name" in data and data["name"]:
            payload["name"] = normalize_name(data["name"])
        for k in ["phone","payment_method","account","note"]:
            if k in data:
                payload[k] = data.get(k)
        if not payload: return
        self._patch("/clients", payload, params={"id": f"eq.{client_id}"}, prefer="return=minimal")

    def delete_client(self, client_id):
        # borrar cascada (asumiendo FK on delete no-cascade; borramos manualmente)
        self._delete("/sessions", params={"client_id": f"eq.{client_id}"})
        self._delete("/monthly_payments", params={"client_id": f"eq.{client_id}"})
        self._delete("/invoices", params={"client_id": f"eq.{client_id}"})
        self._delete("/clients", params={"id": f"eq.{client_id}"})

    # ---- sessions ----
    def log_session(self, client_id, ts_iso, amount_int):
        payload = [{"client_id": client_id, "ts_iso": ts_iso, "amount_int": int(amount_int or DEFAULT_CLASE_COP)}]
        resp = self._post("/sessions", payload, prefer="return=representation")
        return resp[0]["id"]

    def list_sessions_between(self, start_iso, end_iso):
        # Filtro correcto con AND en PostgREST (rango: [start_iso, end_iso) )
        params = {
            "select": "id,client_id,ts_iso,amount_int",
            "and": f"(ts_iso.gte.{start_iso},ts_iso.lt.{end_iso})",
            "order": "ts_iso.asc",
        }
        data = self._get("/sessions", params=params)

        # Mapear nombre del cliente
        cmap = {c["id"]: c for c in self.list_clients()}
        for d in data:
            d["client_name"] = cmap.get(d["client_id"], {}).get("name", "—")
        return data

    def delete_session(self, session_id):
        self._delete("/sessions", params={"id": f"eq.{session_id}"})

    # ---- monthly payments ----
    def get_month_payment(self, client_id, year, month):
        res = self._get("/monthly_payments", params={
            "select":"paid,paid_on_iso",
            "client_id":f"eq.{client_id}",
            "year":f"eq.{year}",
            "month":f"eq.{month}"
        })
        if not res: return dict(paid=False, paid_on_iso=None)
        r = res[0]
        return dict(paid=bool(r.get("paid", False)), paid_on_iso=r.get("paid_on_iso"))

    def set_month_payment(self, client_id, year, month, paid: bool, paid_on_iso: str|None):
        # upsert (requiere unique(client_id,year,month) en supabase)
        payload = [{
            "client_id": client_id,
            "year": year,
            "month": month,
            "paid": bool(paid),
            "paid_on_iso": paid_on_iso
        }]
        self._post("/monthly_payments", payload, prefer="resolution=merge-duplicates,return=minimal")


def get_backend():
    import os
    # intentar leer de st.secrets si existe, si no, de variables de entorno
    url = None
    key = None
    try:
        import streamlit as st
        if "SUPABASE_URL" in st.secrets:
            url = st.secrets["SUPABASE_URL"]
        if "SUPABASE_ANON_KEY" in st.secrets:
            key = st.secrets["SUPABASE_ANON_KEY"]
    except Exception:
        pass

    url = url or os.getenv("SUPABASE_URL")
    key = key or os.getenv("SUPABASE_ANON_KEY")

    if url and key:
        try:
            return SupabaseBackend(url, key), "Supabase"
        except Exception:
            # Si algo falla con Supabase, caemos a SQLite
            pass
    return SQLiteBackend(), "SQLite"

