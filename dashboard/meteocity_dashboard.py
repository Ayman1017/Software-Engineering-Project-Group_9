"""
MeteoCity Streamlit Dashboard
Monitoring City Weather — Milan & Rome

Role-based access:
  student / researcher  : Map & Stations, Export CSV
  ngo                   : Map & Stations, Trend Analysis, Export CSV
  government            : Map & Stations, Trend Analysis, Statistics, Export CSV

Start:
  python -m streamlit run dashboard/meteocity_dashboard.py
Flask must be running on localhost:5000.
"""
from datetime import date, timedelta

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_folium import st_folium

# ── Constants ──────────────────────────────────────────────────────────────────
API_BASE = "http://localhost:5000"

ROLE_LABELS = {
    "student":    "Student / Researcher",
    "researcher": "Student / Researcher",
    "ngo":        "NGO",
    "government": "Government",
    "user":       "User",
}
CAN_TREND = {"ngo", "government"}
CAN_STATS = {"government"}

VAR_LABELS = {
    "temperature": "Temperature (°C)",
    "humidity":    "Humidity (%)",
    "wind_speed":  "Wind Speed (m/s)",
}

CITY_CENTERS = {"Milan": [45.47, 9.19], "Rome": [41.90, 12.49]}

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MeteoCity - Monitoring City Weather",
    page_icon="🌡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Global UI chrome hiding (applies on all pages).
st.markdown("""
<style>
#MainMenu {visibility: hidden !important;}
button[data-testid="stBaseButton-header"] {display: none !important;}
[data-testid="stToolbar"] {display: none !important;}
header[data-testid="stHeader"] .stDeployButton {display: none !important;}
footer {visibility: hidden !important;}
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────
_DEFAULTS = {
    "logged_in":      False,
    "token":          None,
    "role":           None,
    "username":       None,
    "analysis_done":  False,
    "sel_city":       "Milan",
    "sel_var":        "temperature",
    "sel_start":      date(2026, 5, 1),
    "sel_end":        date.today(),
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ══════════════════════════════════════════════════════════════════════════════
# API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _auth_headers():
    return {
        "Authorization": f"Bearer {st.session_state.token}",
        "Accept": "application/json",
    }


def _api_get(path, params=None):
    """Returns (data_dict_or_list, error_str_or_None)."""
    try:
        r = requests.get(
            f"{API_BASE}{path}",
            headers=_auth_headers(),
            params={k: v for k, v in (params or {}).items() if v is not None},
            timeout=20,
        )
        if r.ok:
            return r.json(), None
        return None, f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.ConnectionError:
        return None, "Cannot connect to Flask at localhost:5000 — is the backend running?"
    except Exception as exc:
        return None, str(exc)


def _post_json(path, body):
    """Returns requests.Response."""
    return requests.post(
        f"{API_BASE}{path}",
        json=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=10,
    )


# ── Auth ───────────────────────────────────────────────────────────────────────

def do_login(username, password):
    """Returns error string on failure, None on success."""
    try:
        r = _post_json("/auth/login", {"username": username, "password": password})
        if r.ok:
            d = r.json()
            st.session_state.update({
                "logged_in": True,
                "token":     d["access_token"],
                "role":      d.get("role") or d.get("user", {}).get("role", "student"),
                "username":  d.get("username", username),
            })
            return None
        print(f"[login debug] HTTP {r.status_code}: {r.text[:500]}")
        try:
            return r.json().get("error", f"HTTP {r.status_code}: Login failed")
        except Exception:
            return f"HTTP {r.status_code}: {r.text[:200]}"
    except requests.ConnectionError:
        return "Cannot connect to Flask at localhost:5000 — start with: python backend/app.py"
    except Exception as exc:
        return str(exc)


def do_register(username, password, role):
    """Returns error string on failure, None on success."""
    print(f"[debug] do_register payload: username={username!r}, role={role!r}")
    try:
        r = _post_json("/auth/register", {"username": username, "password": password, "role": role})
        print(f"[debug] do_register response: HTTP {r.status_code}: {r.text[:300]}")
        if r.ok:
            return None
        try:
            return r.json().get("error", f"HTTP {r.status_code}: Registration failed")
        except Exception:
            return f"HTTP {r.status_code}: {r.text[:200]}"
    except requests.ConnectionError:
        return "Cannot connect to Flask at localhost:5000"
    except Exception as exc:
        return str(exc)


# ── Data fetchers ──────────────────────────────────────────────────────────────

def get_city_id(city_name):
    data, _ = _api_get("/api/cities")
    if data:
        for c in data:
            if c.get("city_name", "").lower() == city_name.lower():
                return c["id"]
    return {"Milan": 1, "Rome": 2}.get(city_name, 1)


def fetch_stations(city_name):
    data, err = _api_get("/api/stations", {"city_name": city_name})
    if err or not data:
        return pd.DataFrame(), err
    df = pd.DataFrame(data)
    if "station_name" not in df.columns and "name" in df.columns:
        df["station_name"] = df["name"]
    return df, None


def fetch_observations(city_name, start, end):
    """Pages through /api/observations. Returns (DataFrame, error_or_None)."""
    rows, offset, limit = [], 0, 1000
    end_param = str(end + timedelta(days=1))
    while True:
        data, err = _api_get("/api/observations", {
            "city":   city_name.lower(),
            "start":  str(start),
            "end":    end_param,
            "limit":  limit,
            "offset": offset,
        })
        if err:
            return pd.DataFrame(), err
        batch = data.get("observations", [])
        rows.extend(batch)
        total = data.get("total", 0)
        if len(batch) < limit or len(rows) >= total:
            break
        offset += limit
    return pd.DataFrame(rows) if rows else pd.DataFrame(), None


def fetch_map_data(city_id):
    data, _ = _api_get("/api/map_data", {"city_id": city_id})
    return (data or {}).get("features", [])


def fetch_statistics(city_id):
    data, err = _api_get("/api/statistics", {"city_id": city_id})
    if err and "403" in str(err):
        return None, "access_denied"
    return data, err


def _missing_ranges(city_name, start, end):
    """
    Return a list of (gap_start, gap_end) date pairs that need ingestion.
    Probes both the start and end boundaries of the requested range.
    For partial DB coverage, queries the oldest/newest record to find the
    exact gap edges so only truly missing sub-ranges are fetched.
    """
    def _probe(s, e):
        d, _ = _api_get("/api/observations", {
            "city": city_name.lower(),
            "start": str(s), "end": str(e + timedelta(days=1)),
            "limit": 1,
        })
        return bool((d or {}).get("observations"))

    has_start = _probe(start, start + timedelta(days=1))
    has_end   = _probe(end - timedelta(days=1), end)

    if has_start and has_end:
        return []  # both boundaries covered — no ingestion needed

    if not has_start and not has_end:
        return [(start, end)]  # no data at all — fetch the full range

    # Partial coverage: one boundary is present, the other is missing.
    # The observations API returns records in DESC order (newest first), so:
    #   limit=1            → gives the LATEST record in the range
    #   limit=1, offset=N-1 → gives the OLDEST record in the range
    full_d, _ = _api_get("/api/observations", {
        "city": city_name.lower(),
        "start": str(start), "end": str(end + timedelta(days=1)), "limit": 1,
    })
    total     = (full_d or {}).get("total", 0)
    latest_ts = ((full_d or {}).get("observations") or [{}])[0].get("obs_timestamp", "")

    gaps = []

    if not has_start and total > 0:
        # Data near end exists — find the oldest record to know where the gap ends
        old_d, _ = _api_get("/api/observations", {
            "city": city_name.lower(),
            "start": str(start), "end": str(end + timedelta(days=1)),
            "limit": 1, "offset": total - 1,
        })
        oldest_ts = ((old_d or {}).get("observations") or [{}])[0].get("obs_timestamp", "")
        if oldest_ts:
            db_earliest = date.fromisoformat(oldest_ts[:10])
            if db_earliest > start:
                gaps.append((start, db_earliest - timedelta(days=1)))
        else:
            gaps.append((start, end))

    if not has_end and total > 0 and latest_ts:
        # Data near start exists — find the newest record to know where the gap begins
        db_latest = date.fromisoformat(latest_ts[:10])
        if db_latest < end:
            gaps.append((db_latest + timedelta(days=1), end))

    return gaps if gaps else [(start, end)]  # fallback: fetch everything


def _trigger_ingest(start, end):
    """Call POST /ingest/range to fetch data for the given date range."""
    print(f"[debug] _trigger_ingest: sending start={start}, end={end}")
    try:
        r = requests.post(
            f"{API_BASE}/ingest/range",
            json={"start": str(start), "end": str(end)},
            headers={**_auth_headers(), "Content-Type": "application/json"},
            timeout=180,
        )
        result = r.json() if r.ok else {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        print(f"[debug] _trigger_ingest response: {result}")
        return result if r.ok else None
    except Exception as exc:
        print(f"[debug] _trigger_ingest exception: {exc}")
        return None


# ── Folium map helper ──────────────────────────────────────────────────────────

def _make_map(center, zoom=10):
    """Create a folium Map with the right-side control toolbar hidden."""
    m = folium.Map(
        location=center, zoom_start=zoom,
        tiles="CartoDB positron", control_scale=False,
    )
    # CHANGE 4 — hide the Leaflet top-right toolbar (layers / fullscreen icons)
    m.get_root().html.add_child(folium.Element(
        "<style>"
        ".leaflet-control-container .leaflet-top.leaflet-right"
        "{display:none!important;}"
        "</style>"
    ))
    return m


def _marker_color(value, variable="temperature"):
    if value is None:
        return "gray"
    if variable == "temperature":
        if value >= 32: return "red"
        if value >= 26: return "orange"
        if value >= 20: return "green"
        return "blue"
    if variable == "humidity":
        if value >= 80: return "red"
        if value >= 60: return "orange"
        if value >= 40: return "green"
        return "blue"
    if variable == "wind_speed":
        kmh = value * 3.6  # stored as m/s, thresholds are km/h
        if kmh >= 50: return "red"
        if kmh >= 30: return "orange"
        if kmh >= 10: return "green"
        return "blue"
    return "gray"


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN / REGISTER PAGE
# ══════════════════════════════════════════════════════════════════════════════

if not st.session_state.logged_in:
    import base64, pathlib

    def _bg_css(path):
        data = base64.b64encode(pathlib.Path(path).read_bytes()).decode()
        ext = pathlib.Path(path).suffix.lstrip(".")
        return f"data:image/{ext};base64,{data}"

    bg = _bg_css("dashboard/bg.png")

    # CHANGE 1 — deploy/toolbar hiding + background + CHANGE 2 — form styling
    st.markdown(f"""<style>
/* ── Hide deploy button, toolbar, menu ── */
button[data-testid="stBaseButton-header"] {{display: none !important;}}
[data-testid="stToolbar"] {{display: none !important;}}
#MainMenu {{visibility: hidden !important;}}

/* ── Background image with dark overlay ── */
[data-testid="stAppViewContainer"] {{
    background-image: url("{bg}");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
}}
[data-testid="stAppViewContainer"]::before {{
    content: "";
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.45);
    z-index: 0;
}}

/* ── CHANGE 2: Tab bar ── */
.stTabs [data-baseweb="tab-list"] {{
    background: rgba(255,255,255,0.15);
    border-radius: 10px;
    padding: 4px;
}}
.stTabs [data-baseweb="tab"] {{
    color: white !important;
    font-weight: 600;
}}
.stTabs [aria-selected="true"] {{
    background: rgba(255,255,255,0.9) !important;
    color: #1e3a5f !important;
    border-radius: 8px;
}}

/* ── CHANGE 2: Text inputs ── */
[data-testid="stTextInput"] input {{
    background: rgba(255,255,255,0.92) !important;
    color: #1e3a5f !important;
    font-weight: 500;
    border-radius: 8px;
}}
[data-testid="stTextInput"] label {{
    color: white !important;
    font-weight: 600;
    font-size: 1em;
    text-shadow: 0 1px 3px rgba(0,0,0,0.8);
}}

/* ── CHANGE 2: Selectbox ── */
.stSelectbox label {{
    color: white !important;
    font-weight: 600;
    text-shadow: 0 1px 3px rgba(0,0,0,0.8);
}}
.stSelectbox [data-baseweb="select"] {{
    background: rgba(255,255,255,0.92) !important;
    border-radius: 8px;
}}
</style>""", unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        # CHANGE 3 — white title with strong text-shadow on the dark background
        st.markdown("""
        <div style="text-align:center;padding:32px 0 8px;">
            <h1 style="font-size:2.4rem;margin-bottom:6px;
                       color:white;
                       text-shadow:0 2px 8px rgba(0,0,0,0.9);
                       font-weight:800;">
                🌡️ MeteoCity
            </h1>
            <p style="color:rgba(255,255,255,0.88);margin:0;font-size:1.1em;
                      text-shadow:0 1px 4px rgba(0,0,0,0.8);">
                Monitoring City Weather &mdash; Milan &amp; Rome
            </p>
        </div>
        """, unsafe_allow_html=True)

        # CHANGE 4 — role info card
        st.markdown("""
        <div style="background:rgba(255,255,255,0.15);
                    border:1px solid rgba(255,255,255,0.3);
                    border-radius:16px;
                    padding:1.2rem 1.5rem;
                    margin:12px 0 16px 0;
                    color:white;">
            <p style="margin:0 0 10px 0;font-weight:700;font-size:0.95em;
                      letter-spacing:0.04em;opacity:0.9;">
                📍 Cities: Milan &amp; Rome
            </p>
            <table style="width:100%;border-collapse:collapse;font-size:0.88em;">
                <thead>
                    <tr style="border-bottom:1px solid rgba(255,255,255,0.3);">
                        <th style="text-align:left;padding:4px 8px 6px 0;opacity:0.75;font-weight:600;">Role</th>
                        <th style="text-align:left;padding:4px 0 6px 8px;opacity:0.75;font-weight:600;">Access</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding:5px 8px 5px 0;white-space:nowrap;">🎓 Student / Researcher</td>
                        <td style="padding:5px 0 5px 8px;opacity:0.9;">Map &amp; Stations &nbsp;·&nbsp; Query &amp; Filter &nbsp;·&nbsp; Export CSV</td>
                    </tr>
                    <tr style="background:rgba(255,255,255,0.07);">
                        <td style="padding:5px 8px 5px 0;white-space:nowrap;">🌿 NGO</td>
                        <td style="padding:5px 0 5px 8px;opacity:0.9;">Map &nbsp;·&nbsp; Query &nbsp;·&nbsp; Trend Analysis &nbsp;·&nbsp; Export CSV</td>
                    </tr>
                    <tr>
                        <td style="padding:5px 8px 5px 0;white-space:nowrap;">🏛️ Government Official</td>
                        <td style="padding:5px 0 5px 8px;opacity:0.9;">All features &nbsp;·&nbsp; + Statistics Dashboard</td>
                    </tr>
                </tbody>
            </table>
        </div>
        """, unsafe_allow_html=True)

        tab_login, tab_register = st.tabs(["🔑 Login", "📝 Register"])

        with tab_login:
            # dummy hidden password field — suppresses Chrome autofill popup
            st.markdown(
                '<input type="password" style="display:none" autocomplete="new-password"/>',
                unsafe_allow_html=True,
            )
            with st.form("login_form", clear_on_submit=False):
                uname = st.text_input("Username", placeholder="e.g. testuser")
                pwd   = st.text_input("Password", type="password")
                submitted = st.form_submit_button(
                    "Login", use_container_width=True, type="primary"
                )
            if submitted:
                if uname and pwd:
                    err = do_login(uname.strip(), pwd)
                    if err:
                        st.error(f"**Login failed:** {err}")
                    else:
                        st.rerun()
                else:
                    st.warning("Please enter username and password.")

        with tab_register:
            # dummy hidden password field — suppresses Chrome autofill popup
            st.markdown(
                '<input type="password" style="display:none" autocomplete="new-password"/>',
                unsafe_allow_html=True,
            )
            roles = ["student", "ngo", "government"]
            with st.form("register_form", clear_on_submit=False):
                r_uname = st.text_input("Username", key="reg_uname")
                r_pwd   = st.text_input("Password (min 6 chars)", type="password", key="reg_pwd")
                r_role  = st.selectbox(
                    "Role", options=roles,
                    format_func=lambda x: ROLE_LABELS.get(x, x),
                    key="reg_role",
                )
                r_submitted = st.form_submit_button("Register", use_container_width=True)
            if r_submitted:
                print(f"[debug] register form submit: r_role={r_role!r}, r_uname={r_uname!r}")
                if r_uname and r_pwd:
                    err = do_register(r_uname.strip(), r_pwd, r_role)
                    if err:
                        st.error(f"**Registration failed:** {err}")
                    else:
                        st.success("✅ Registered! You can now log in.")
                else:
                    st.warning("Please fill in all fields.")

    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD (logged in)
# ══════════════════════════════════════════════════════════════════════════════

role = st.session_state.role or "student"

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**👤 {st.session_state.username}**")
    st.caption(ROLE_LABELS.get(role, role))
    if st.button("Logout", use_container_width=True):
        for k in _DEFAULTS:
            st.session_state[k] = _DEFAULTS[k]
        st.rerun()

    st.divider()
    st.markdown("### 🔍 Filters")

    city = st.selectbox("City", ["Milan", "Rome"],
                        index=["Milan", "Rome"].index(st.session_state.sel_city))
    var  = st.selectbox(
        "Variable",
        ["temperature", "humidity", "wind_speed"],
        format_func=lambda x: VAR_LABELS[x],
        index=["temperature", "humidity", "wind_speed"].index(st.session_state.sel_var),
    )
    start = st.date_input("From", value=st.session_state.sel_start,
                          max_value=date.today())
    end   = st.date_input("To",   value=st.session_state.sel_end,
                          max_value=date.today())

    if start > end:
        st.error("'From' date must be before 'To' date.")
        st.stop()

    run = st.button("Show Analysis", type="primary", use_container_width=True)
    if run:
        st.session_state.analysis_done = True
        st.session_state.sel_city  = city
        st.session_state.sel_var   = var
        st.session_state.sel_start = start
        st.session_state.sel_end   = end


# ── Header ─────────────────────────────────────────────────────────────────────
st.title("🌡️ MeteoCity - Monitoring City Weather")
st.caption("Milan & Rome Weather Station Dashboard")

# CHANGE 6 — Before "Show Analysis" is clicked, show a default station map
# for the selected city using gray markers (no observation data needed).
if not st.session_state.analysis_done:
    st.markdown(f"### Stations in {city}")
    st.caption("Select filters in the sidebar and click **Show Analysis** to load charts.")

    _def_stations, _ = fetch_stations(city)
    _dm = _make_map(CITY_CENTERS.get(city, [45.47, 9.19]), zoom=10)

    if not _def_stations.empty:
        _station_colors = ['red', 'blue', 'green', 'orange', 'purple', 'darkred', 'cadetblue']
        for _idx, (_, _row) in enumerate(_def_stations.iterrows()):
            _sname = str(_row.get("station_name", _row.get("station_id", "")))
            _color = _station_colors[_idx % len(_station_colors)]
            folium.Marker(
                location=[_row["latitude"], _row["longitude"]],
                tooltip=_sname,
                popup=folium.Popup(
                    f"<b>{_sname}</b><br>{_row.get('city_name', city)}<br>"
                    f"Lat: {_row['latitude']:.4f}, Lon: {_row['longitude']:.4f}",
                    max_width=200,
                ),
                icon=folium.Icon(color=_color),
            ).add_to(_dm)
    else:
        st.caption("(Station data unavailable — check that Flask is running.)")

    st_folium(_dm, height=480, returned_objects=[])
    st.stop()

# Use persisted filter values so switching tabs doesn't lose context
city      = st.session_state.sel_city
var       = st.session_state.sel_var
start     = st.session_state.sel_start
end       = st.session_state.sel_end
var_label = VAR_LABELS[var]

st.markdown(
    f"**City:** {city} &nbsp;|&nbsp; **Variable:** {var_label} &nbsp;|&nbsp; "
    f"**Period:** {start} → {end}"
)
st.divider()


# ── Fetch missing data if needed ───────────────────────────────────────────────
_gaps = _missing_ranges(city, start, end)
if _gaps:
    _ingest_errors = []
    _total_inserted = 0
    with st.spinner("Missing data detected — fetching from Meteostat (this may take a minute)…"):
        for _g_start, _g_end in _gaps:
            print(f"[debug] fetching gap: {_g_start} → {_g_end}")
            _result = _trigger_ingest(_g_start, _g_end)
            if _result:
                _n = _result.get("inserted", 0)
                _total_inserted += _n
                print(f"[debug] gap {_g_start}→{_g_end}: inserted {_n} rows (mode={_result.get('mode')})")
            else:
                print(f"[debug] gap {_g_start}→{_g_end}: ingest returned error or None")
                _ingest_errors.append(f"{_g_start} → {_g_end}")
    if _ingest_errors:
        st.error(f"Ingestion failed for: {', '.join(_ingest_errors)}. Check Flask logs for details.")
    else:
        print(f"[debug] ingestion complete — total inserted: {_total_inserted}")

# ── Load data ──────────────────────────────────────────────────────────────────
print(f"[debug] fetch_observations: city={city!r}, start={start}, end={end}")
with st.spinner(f"Loading data for {city} ({start} – {end})…"):
    city_id              = get_city_id(city)
    df_stations, st_err  = fetch_stations(city)
    df_obs, obs_err      = fetch_observations(city, start, end)
    features             = fetch_map_data(city_id)

if obs_err:
    st.error(f"**Could not load observations:** {obs_err}")
    st.stop()

if df_obs.empty:
    st.warning(f"No observations found for {city} between {start} and {end}.")
    st.stop()

df_obs["obs_timestamp"] = pd.to_datetime(df_obs["obs_timestamp"], utc=True)
df_obs = df_obs.sort_values("obs_timestamp")

if "station_name" not in df_obs.columns:
    if not df_stations.empty and "station_name" in df_stations.columns:
        nm = df_stations.set_index("station_id")["station_name"].to_dict()
        df_obs["station_name"] = df_obs["station_id"].map(nm).fillna(df_obs["station_id"])
    else:
        df_obs["station_name"] = df_obs["station_id"]

if "is_synthetic" not in df_obs.columns:
    df_obs["is_synthetic"] = True


# ── Build tabs based on role ──────────────────────────────────────────────────
tab_names = ["🗺️ Map & Stations"]
if role in CAN_TREND:
    tab_names.append("📈 Trend Analysis")
if role in CAN_STATS:
    tab_names.append("📊 Statistics")
tab_names.append("⬇️ Export CSV")

tabs    = st.tabs(tab_names)
tab_idx = {name: i for i, name in enumerate(tab_names)}


# ══════════════════════════════════════════════════════════════════════════════
# TAB: Map & Stations (all roles)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[tab_idx["🗺️ Map & Stations"]]:
    st.subheader(f"Weather Stations — {city}")

    # CHANGE 4 — _make_map() creates the map with the right-side toolbar hidden.
    m = _make_map(CITY_CENTERS.get(city, [45.47, 9.19]))

    # Most recent observation per station within the selected date range, from df_obs.
    _latest_by_sid = {}
    if not df_obs.empty:
        _latest_by_sid = (
            df_obs.sort_values("obs_timestamp")
            .groupby("station_id")
            .last()[["temperature", "humidity", "wind_speed"]]
            .to_dict("index")
        )

    for feat in features:
        lon, lat = feat["geometry"]["coordinates"]
        p        = feat["properties"]
        t        = p.get("temperature")
        h        = p.get("humidity")
        w        = p.get("wind_speed")
        t_s      = f"{t:.1f}°C"   if t is not None else "N/A"
        h_s      = f"{h:.0f}%"    if h is not None else "N/A"
        w_s      = f"{w:.1f} m/s" if w is not None else "N/A"

        _sid      = p.get("station_id")
        _obs_row  = _latest_by_sid.get(_sid, {})
        _mv       = _obs_row.get(var) if _obs_row else {"temperature": t, "humidity": h, "wind_speed": w}.get(var, t)
        _active_s = (
            f"{_mv:.1f}°C"   if var == "temperature" and _mv is not None else
            f"{_mv:.0f}%"    if var == "humidity"    and _mv is not None else
            f"{_mv:.1f} m/s" if var == "wind_speed"  and _mv is not None else
            {"temperature": t_s, "humidity": h_s, "wind_speed": w_s}.get(var, t_s)
        )
        folium.CircleMarker(
            location=[lat, lon], radius=13,
            color=_marker_color(_mv, var), fill=True, fill_opacity=0.82,
            popup=folium.Popup(
                f"<b>{p['name']}</b><br>{p['city']}<br>"
                f"🌡 {t_s} &nbsp;|&nbsp; 💧 {h_s} &nbsp;|&nbsp; 💨 {w_s}<br>"
                f"<small>Updated: {p.get('last_updated', 'N/A')}</small>",
                max_width=240,
            ),
            tooltip=f"{p['name']} — {_active_s}",
        ).add_to(m)

    _legend_bands = {
        "temperature": ("Temperature (°C)", [
            ("red",     "≥32°C",     "Hot"),
            ("orange",  "26–31°C",   "Warm"),
            ("green",   "20–25°C",   "Mild"),
            ("#2c7be5", "&lt;20°C",  "Cool"),
            ("gray",    "No data",   ""),
        ]),
        "humidity": ("Humidity (%)", [
            ("red",     "≥80%",      "Very Humid"),
            ("orange",  "60–79%",    "Humid"),
            ("green",   "40–59%",    "Comfortable"),
            ("#2c7be5", "&lt;40%",   "Dry"),
            ("gray",    "No data",   ""),
        ]),
        "wind_speed": ("Wind Speed (km/h)", [
            ("red",     "≥50 km/h",    "Strong"),
            ("orange",  "30–49 km/h",  "Moderate"),
            ("green",   "10–29 km/h",  "Light"),
            ("#2c7be5", "&lt;10 km/h", "Calm"),
            ("gray",    "No data",     ""),
        ]),
    }
    _ltitle, _lbands = _legend_bands.get(var, _legend_bands["temperature"])
    _rows = "".join(
        f'<span style="color:{c};font-size:16px;">●</span> {rng} — {lbl}<br>'
        if lbl else
        f'<span style="color:{c};font-size:16px;">●</span> {rng}<br>'
        for c, rng, lbl in _lbands
    )
    legend = (
        '<div style="position:fixed;bottom:28px;left:28px;background:white;'
        'padding:10px 14px;border-radius:8px;border:1px solid #ddd;font-size:12px;'
        'box-shadow:0 2px 8px rgba(0,0,0,0.12);z-index:9999;line-height:2.0;">'
        f'<b>{_ltitle}</b><br>{_rows}</div>'
    )
    m.get_root().html.add_child(folium.Element(legend))

    st_folium(m, height=500, returned_objects=[])

    if not df_stations.empty:
        st.subheader("Station Details")
        show = [c for c in ["station_name", "station_id", "latitude",
                             "longitude", "elevation", "city_name"]
                if c in df_stations.columns]
        df_stations = df_stations.drop_duplicates(subset=["latitude", "longitude"], keep="first")
        st.dataframe(df_stations[show], use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB: Trend Analysis (ngo + government)
# ══════════════════════════════════════════════════════════════════════════════
if "📈 Trend Analysis" in tab_idx:
    with tabs[tab_idx["📈 Trend Analysis"]]:
        st.subheader(f"Trend Analysis — {var_label}")

        df_v = df_obs.dropna(subset=[var]).copy()

        if df_v.empty:
            st.info(f"No {var_label} data in this period.")
        else:
            # ── Time-series + 24h moving average ─────────────────────────────
            st.markdown("##### Hourly Readings + 24h Moving Average")
            pal    = px.colors.qualitative.Set2
            fig_ts = go.Figure()
            for i, (sid, grp) in enumerate(df_v.groupby("station_name")):
                g    = grp.set_index("obs_timestamp").sort_index()
                col  = pal[i % len(pal)]
                ma24 = g[var].rolling("24h", min_periods=1).mean()
                fig_ts.add_trace(go.Scatter(
                    x=g.index, y=g[var],
                    name=f"{sid} (raw)", mode="lines",
                    line=dict(color=col, width=1), opacity=0.22, legendgroup=sid,
                ))
                fig_ts.add_trace(go.Scatter(
                    x=g.index, y=ma24,
                    name=f"{sid} (24h avg)", mode="lines",
                    line=dict(color=col, width=2.5), legendgroup=sid,
                ))
            fig_ts.update_layout(
                template="plotly_white", hovermode="x unified", height=420,
                margin=dict(t=30, b=40, l=60, r=20),
                yaxis_title=var_label,
                legend=dict(orientation="h", y=1.06, xanchor="right", x=1),
            )
            # CHANGE 3 — remove Plotly toolbar
            st.plotly_chart(fig_ts, use_container_width=True,
                            config={"displayModeBar": False})

            # ── Weekly bar chart ──────────────────────────────────────────────
            st.markdown("##### Weekly Average")
            df_v["week"] = df_v["obs_timestamp"].dt.to_period("W").astype(str)
            weekly = (
                df_v.groupby(["week", "station_name"])[var]
                .mean().reset_index()
            )
            fig_bar = px.bar(
                weekly, x="week", y=var, color="station_name",
                barmode="group", template="plotly_white",
                labels={"week": "Week", var: var_label, "station_name": "Station"},
                height=360,
            )
            fig_bar.update_layout(
                margin=dict(t=30, b=40, l=60, r=20),
                legend=dict(orientation="h", y=1.06, xanchor="right", x=1),
            )
            # CHANGE 3 — remove Plotly toolbar
            st.plotly_chart(fig_bar, use_container_width=True,
                            config={"displayModeBar": False})

            # ── Histogram ─────────────────────────────────────────────────────
            st.markdown(f"##### Distribution of {var_label}")
            fig_hist = px.histogram(
                df_v, x=var, color="station_name", nbins=40,
                template="plotly_white", opacity=0.70, barmode="overlay",
                labels={var: var_label, "station_name": "Station"},
                height=340,
            )
            fig_hist.update_layout(
                margin=dict(t=30, b=40, l=60, r=20),
                legend=dict(orientation="h", y=1.06, xanchor="right", x=1),
            )
            # CHANGE 3 — remove Plotly toolbar
            st.plotly_chart(fig_hist, use_container_width=True,
                            config={"displayModeBar": False})


# ══════════════════════════════════════════════════════════════════════════════
# TAB: Statistics (government only)
# CHANGE 1 — Box plot removed from this section entirely.
# ══════════════════════════════════════════════════════════════════════════════
if "📊 Statistics" in tab_idx:
    with tabs[tab_idx["📊 Statistics"]]:
        st.subheader(f"Statistics — {city}")

        stats, stats_err = fetch_statistics(city_id)

        if stats_err == "access_denied":
            st.error("Access denied — Statistics require Government role.")
        elif stats_err:
            st.error(f"Statistics error: {stats_err}")
        elif stats:
            def _v(d, k, unit=""):
                val = d.get(k)
                return f"{val:.2f}{unit}" if val is not None else "N/A"

            temp_d = stats.get("temperature", {})
            hum_d  = stats.get("humidity",    {})
            wind_d = stats.get("wind_speed",  {})
            total  = stats.get("total_observations", 0)

            _unit = {"temperature": "°C", "humidity": "%", "wind_speed": " m/s"}.get(var, "")
            for _stn_name, _stn_grp in df_obs.groupby("station_name"):
                st.markdown(f"**{_stn_name}**")
                _d = _stn_grp[var].dropna()
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Mean",    f"{_d.mean():.2f}{_unit}" if not _d.empty else "N/A")
                c2.metric("Max",     f"{_d.max():.2f}{_unit}"  if not _d.empty else "N/A")
                c3.metric("Min",     f"{_d.min():.2f}{_unit}"  if not _d.empty else "N/A")
                c4.metric("Std Dev", f"{_d.std():.2f}{_unit}"  if not _d.empty else "N/A")
                c5.metric("Records", f"{len(_d):,}")

            if stats.get("per_station"):
                st.divider()
                st.markdown("**Per-Station Breakdown**")
                df_ps = pd.DataFrame(stats["per_station"])
                _ps_avg_col = {
                    "temperature": "avg_temperature",
                    "humidity":    "avg_humidity",
                    "wind_speed":  "avg_wind_speed",
                }.get(var, "avg_temperature")
                ps_show = [c for c in ["station_id", "name", "city", _ps_avg_col, "observation_count"]
                           if c in df_ps.columns]
                st.dataframe(df_ps[ps_show], use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB: Export CSV (all roles)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[tab_idx["⬇️ Export CSV"]]:
    st.subheader("Export Data as CSV")

    _station_opts = ["All stations"] + sorted(
        df_obs["station_name"].dropna().unique().tolist()
    )
    _sel_station = st.selectbox("Station", _station_opts, key="export_station")

    export_cols = [c for c in
                   ["obs_timestamp", "station_id", "station_name", var]
                   if c in df_obs.columns]
    df_export = df_obs[export_cols].copy()
    if _sel_station != "All stations":
        df_export = df_export[df_export["station_name"] == _sel_station]
    n_rows = len(df_export)

    _station_label = _sel_station if _sel_station != "All stations" else f"all stations ({len(_station_opts) - 1})"
    st.info(
        f"**{n_rows:,} observations** ready — "
        f"{city} | {start} → {end} | {_station_label}",
        icon="📦",
    )

    csv_bytes = df_export.to_csv(index=False).encode("utf-8")

    _fname_station = "" if _sel_station == "All stations" else f"_{_sel_station.lower().replace(' ', '_')}"
    st.download_button(
        label=f"⬇️  Download CSV  ({n_rows:,} rows)",
        data=csv_bytes,
        file_name=f"meteocity_{city.lower()}_{start}_{end}{_fname_station}.csv",
        mime="text/csv",
        type="primary",
        use_container_width=True,
    )

    st.divider()
    st.markdown("**Preview — first 30 rows**")
    st.dataframe(df_export.head(30), use_container_width=True, hide_index=True)
