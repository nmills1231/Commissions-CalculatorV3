import sqlite3
import json
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

DB_FILE = "deals.db"

st.set_page_config(page_title="Commission Calculator", layout="wide", page_icon="🏢")

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
    }
    .block-container {
        padding-top: 1.5rem;
    }
    div[data-testid="stMetric"] {
        background: white;
        border: 1px solid #e5e7eb;
        padding: 14px;
        border-radius: 16px;
        box-shadow: 0 6px 18px rgba(15,23,42,.06);
    }
    section[data-testid="stSidebar"] {
        background: #0f172a !important;
    }
    section[data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }
    section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div,
    section[data-testid="stSidebar"] .stTextInput input {
        background-color: #f8fafc !important;
        color: #0f172a !important;
    }
    section[data-testid="stSidebar"] .stSelectbox svg {
        fill: #0f172a !important;
    }
    .card {
        background: white;
        padding: 18px 20px;
        border-radius: 18px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 8px 24px rgba(15,23,42,.06);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def get_conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.commit()

def save_or_update_deal(name, payload):
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM deals WHERE name = ?", (name,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE deals SET updated_at = ?, payload = ? WHERE name = ?",
                (now, json.dumps(payload), name),
            )
        else:
            conn.execute(
                "INSERT INTO deals (name, created_at, updated_at, payload) VALUES (?, ?, ?, ?)",
                (name, now, now, json.dumps(payload)),
            )
        conn.commit()

@st.cache_data(ttl=5)
def load_deals():
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT id, name, created_at, updated_at, payload FROM deals ORDER BY updated_at DESC",
            conn,
        )

def get_deal_by_name(name):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, created_at, updated_at, payload FROM deals WHERE name = ?",
            (name,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "created_at": row[2],
        "updated_at": row[3],
        "payload": json.loads(row[4]),
    }

def calc_schedule(sf, base_rent_psf, term_years, fee_pct, esc_type, esc_amt, esc_freq, flat_years):
    rows = []
    current_rent = base_rent_psf

    for year in range(1, term_years + 1):
        if year > 1:
            if esc_type == "Flat":
                pass
            elif esc_type == "Annual %":
                current_rent *= (1 + esc_amt / 100)
            elif esc_type == "Every N Years %":
                if (year - 1) % esc_freq == 0:
                    current_rent *= (1 + esc_amt / 100)
            elif esc_type == "Flat Then Annual %":
                if year > flat_years:
                    current_rent *= (1 + esc_amt / 100)
            elif esc_type == "Flat Then Every N Years %":
                if year > flat_years and (year - flat_years - 1) % esc_freq == 0:
                    current_rent *= (1 + esc_amt / 100)

        annual_rent = current_rent * sf
        annual_commission = annual_rent * (fee_pct / 100)

        rows.append(
            {
                "Year": year,
                "Rent PSF ($)": round(current_rent, 2),
                "Annual Rent ($)": round(annual_rent, 2),
                "Total Commission ($)": round(annual_commission, 2),
            }
        )

    df = pd.DataFrame(rows)
    return df, round(df["Annual Rent ($)"].sum(), 2), round(df["Total Commission ($)"].sum(), 2)

def build_pdf(title, inputs, schedule_df, total_base_rent, total_commission):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=28,
        leftMargin=28,
        topMargin=28,
        bottomMargin=28,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 10)]

    summary = [
        ["Deal Name", inputs["deal_name"]],
        ["SF", f'{inputs["sf"]:,.2f}'],
        ["Term", f'{inputs["term_years"]} years'],
        ["Fee %", f'{inputs["fee_pct"]:.2f}%'],
        ["Escalation", inputs["esc_type"]],
        ["Total Base Rent", f'${total_base_rent:,.2f}'],
        ["Total Commission", f'${total_commission:,.2f}'],
    ]

    summary_tbl = Table(summary, colWidths=[160, 330])
    summary_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story += [summary_tbl, Spacer(1, 14)]

    tbl_data = [schedule_df.columns.tolist()] + schedule_df.round(2).astype(str).values.tolist()
    tbl = Table(tbl_data, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(tbl)
    doc.build(story)
    buffer.seek(0)
    return buffer

def esc_type_changed():
    st.session_state.show_esc_inputs = st.session_state.esc_type_selector

init_db()

if "loaded_deal" not in st.session_state:
    st.session_state.loaded_deal = None
if "last_calc" not in st.session_state:
    st.session_state.last_calc = None
if "show_esc_inputs" not in st.session_state:
    st.session_state.show_esc_inputs = "Annual %"
if "esc_type_selector" not in st.session_state:
    st.session_state.esc_type_selector = st.session_state.show_esc_inputs

df_deals = load_deals()

st.markdown(
    '<div class="card"><h1 style="margin:0">Real Estate Commission Calculator</h1><p style="margin:6px 0 0 0;color:#475569">Calculate commissions from total base rent, save deals, and export a printable summary.</p></div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Saved Deals")
    if len(df_deals):
        selected = st.selectbox("Load deal", [""] + df_deals["name"].tolist())
        if st.button("Load Selected") and selected:
            st.session_state.loaded_deal = get_deal_by_name(selected)
            st.session_state.show_esc_inputs = st.session_state.loaded_deal["payload"].get("esc_type", "Annual %")
            st.session_state.esc_type_selector = st.session_state.show_esc_inputs
            st.cache_data.clear()
            st.rerun()
    else:
        st.caption("No saved deals yet.")
    if st.button("Clear Loaded Deal"):
        st.session_state.loaded_deal = None
        st.rerun()

payload = st.session_state.loaded_deal["payload"] if st.session_state.loaded_deal else {}

st.markdown("### Deal Inputs")

deal_name = st.text_input("Deal Name", value=payload.get("deal_name", ""))

c1, c2 = st.columns(2)

with c1:
    sf = st.number_input("Square Feet (SF)", min_value=0.0, step=100.0, format="%.2f", value=float(payload.get("sf", 0.0)))
    base_rent_psf = st.number_input("Base Rent PSF ($)", min_value=0.0, step=0.01, format="%.2f", value=float(payload.get("base_rent_psf", 0.0)))

with c2:
    term_years = st.number_input("Term Length (Years)", min_value=1, step=1, value=int(payload.get("term_years", 5)))
    fee_pct = st.number_input("Fee %", min_value=0.0, step=0.01, format="%.2f", value=float(payload.get("fee_pct", 3.0)))

st.markdown("### Escalation")
st.selectbox(
    "Escalation Type",
    ["Flat", "Annual %", "Every N Years %", "Flat Then Annual %", "Flat Then Every N Years %"],
    index=["Flat", "Annual %", "Every N Years %", "Flat Then Annual %", "Flat Then Every N Years %"].index(st.session_state.show_esc_inputs),
    key="esc_type_selector",
    on_change=esc_type_changed,
)

esc_type = st.session_state.show_esc_inputs
esc_amt = 0.0
esc_freq = 1
flat_years = 0

if esc_type == "Annual %":
    esc_amt = st.number_input("Increase %", min_value=0.0, step=0.01, format="%.2f", value=float(payload.get("esc_amt", 3.0)))

elif esc_type == "Every N Years %":
    esc_amt = st.number_input("Increase %", min_value=0.0, step=0.01, format="%.2f", value=float(payload.get("esc_amt", 3.0)))
    esc_freq = st.number_input("Increase Every N Years", min_value=1, step=1, value=int(payload.get("esc_freq", 5)))

elif esc_type == "Flat Then Annual %":
    flat_years = st.number_input("Flat Years Before Increases", min_value=0, step=1, value=int(payload.get("flat_years", 0)))
    esc_amt = st.number_input("Increase %", min_value=0.0, step=0.01, format="%.2f", value=float(payload.get("esc_amt", 3.0)))

elif esc_type == "Flat Then Every N Years %":
    flat_years = st.number_input("Flat Years Before Increases", min_value=0, step=1, value=int(payload.get("flat_years", 0)))
    esc_amt = st.number_input("Increase %", min_value=0.0, step=0.01, format="%.2f", value=float(payload.get("esc_amt", 3.0)))
    esc_freq = st.number_input("Increase Every N Years", min_value=1, step=1, value=int(payload.get("esc_freq", 5)))

with st.form("deal_form"):
    submit = st.form_submit_button("Calculate")

if submit:
    inputs = {
        "deal_name": deal_name.strip(),
        "sf": sf,
        "base_rent_psf": base_rent_psf,
        "term_years": int(term_years),
        "fee_pct": fee_pct,
        "esc_type": esc_type,
        "esc_amt": float(esc_amt),
        "esc_freq": int(esc_freq),
        "flat_years": int(flat_years),
    }
    schedule_df, total_base_rent, total_commission = calc_schedule(
        sf,
        base_rent_psf,
        int(term_years),
        fee_pct,
        esc_type,
        float(esc_amt),
        int(esc_freq),
        int(flat_years),
    )
    st.session_state.last_calc = {
        "inputs": inputs,
        "schedule_df": schedule_df,
        "total_base_rent": total_base_rent,
        "total_commission": total_commission,
    }

if st.session_state.last_calc:
    calc = st.session_state.last_calc
    inputs = calc["inputs"]
    schedule_df = calc["schedule_df"]
    total_base_rent = calc["total_base_rent"]
    total_commission = calc["total_commission"]

    st.markdown("### Results")
    a, b, c, d = st.columns(4)
    a.metric("Total Base Rent", f"${total_base_rent:,.2f}")
    b.metric("Total Commission", f"${total_commission:,.2f}")
    c.metric("Term", f"{inputs['term_years']} years")
    d.metric("Fee %", f"{inputs['fee_pct']:.2f}%")

    st.dataframe(schedule_df, use_container_width=True, hide_index=True)

    colx, coly = st.columns(2)
    with colx:
        st.download_button(
            "Download CSV",
            schedule_df.to_csv(index=False).encode("utf-8"),
            "commission_schedule.csv",
            "text/csv",
        )
    with coly:
        pdf = build_pdf(
            inputs["deal_name"] or "Deal Summary",
            inputs,
            schedule_df,
            total_base_rent,
            total_commission,
        )
        st.download_button(
            "Download Printable PDF",
            pdf,
            "deal_summary.pdf",
            "application/pdf",
        )

    st.markdown("### Save Deal")
    save_name = st.text_input("Save As", value=inputs["deal_name"] or "Untitled Deal", key="save_name")
    csave1, csave2 = st.columns(2)
    with csave1:
        if st.button("Save Deal"):
            save_or_update_deal(save_name, inputs)
            st.cache_data.clear()
            st.success("Deal saved.")
            st.rerun()
    with csave2:
        if st.session_state.loaded_deal and st.button("Update Loaded Deal"):
            save_or_update_deal(save_name, inputs)
            st.cache_data.clear()
            st.success("Deal updated.")
            st.rerun()

st.markdown("### Saved Deals Table")
if len(df_deals):
    view = df_deals.copy()
    view["deal_name"] = view["payload"].apply(lambda x: json.loads(x).get("deal_name", ""))
    view["sf"] = view["payload"].apply(lambda x: json.loads(x).get("sf", 0))
    view["term_years"] = view["payload"].apply(lambda x: json.loads(x).get("term_years", 0))
    view["fee_pct"] = view["payload"].apply(lambda x: json.loads(x).get("fee_pct", 0))
    st.dataframe(
        view[["id", "deal_name", "sf", "term_years", "fee_pct", "created_at", "updated_at"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.caption("No deals saved yet.")
