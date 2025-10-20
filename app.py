# app.py
import os, json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ------------------- Secrets / Vars -------------------
SHEET_ID       = os.getenv("SHEET_ID")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1")
DATE_COL       = os.getenv("DATE_COL", "تاریخ")
CUSTOMER_COL   = os.getenv("CUSTOMER_COL", "عرضه به")
EXCLUDED_ENV   = os.getenv("EXCLUDED_CUSTOMERS", "")

# ------------------- UI Config -------------------
st.set_page_config(page_title="داشبورد مشتریان", layout="wide")
st.title("📊 داشبورد مشتریان (Realtime)")

# Sidebar controls
st.sidebar.header("تنظیمات")
auto_refresh = st.sidebar.toggle("رفرش خودکار", value=True, help="هر N ثانیه صفحه رفرش شود.")
refresh_every = st.sidebar.slider("فاصله رفرش (ثانیه)", min_value=15, max_value=300, value=60, step=15)
ttl = st.sidebar.slider("کش خواندن شیت (ثانیه)", min_value=15, max_value=300, value=60, step=15,
                        help="هر بار که TTL تمام شود، داده تازه از شیت خوانده می‌شود.")

if auto_refresh:
    st.components.v1.html(f'<meta http-equiv="refresh" content="{refresh_every}">', height=0)

# فهرست مشتریان استثناء (قابل ویرایش از سایدبار)
excluded_text = st.sidebar.text_area("حذف این مشتریان (هر خط یک نام)", value=EXCLUDED_ENV, height=140)
EXCLUDED = [s.strip() for s in excluded_text.splitlines() if s.strip()]

# ------------------- Sheets connection -------------------
@st.cache_data(ttl=60)
def _connect_and_read(ttl_seconds: int):
    creds_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(WORKSHEET_NAME)
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

_connect_and_read.clear()
df_raw = _connect_and_read(ttl)

if DATE_COL not in df_raw.columns or CUSTOMER_COL not in df_raw.columns:
    st.error(f"ستون‌های مورد انتظار پیدا نشدند: «{DATE_COL}» و «{CUSTOMER_COL}». ستون‌های موجود: {list(df_raw.columns)}")
    st.stop()

# ------------------- Data Cleaning -------------------
df_raw = df_raw.rename(columns={c: str(c).strip() for c in df_raw.columns})
df = df_raw[[DATE_COL, CUSTOMER_COL]].dropna(subset=[DATE_COL, CUSTOMER_COL]).copy()
df[DATE_COL] = pd.to_datetime(df[DATE_COL], dayfirst=False, errors="coerce")  # mm/dd/yyyy
df = df[df[DATE_COL].notna()]
df[CUSTOMER_COL] = df[CUSTOMER_COL].astype(str).str.strip()

today = pd.Timestamp.today().normalize()
df = df[df[DATE_COL] <= today]
if EXCLUDED:
    df = df[~df[CUSTOMER_COL].isin(EXCLUDED)]

# ------------------- Year selection -------------------
available_years = sorted(df[DATE_COL].dt.year.unique())
current_year = today.year
default_year = current_year if current_year in available_years else available_years[-1]
year_opt = st.sidebar.selectbox("سال گزارش", options=list(reversed(available_years)),
                                index=list(reversed(available_years)).index(default_year))

# ------------------- New customers -------------------
first_purchase = df.groupby(CUSTOMER_COL, as_index=False)[DATE_COL].min()
first_purchase["year"]  = first_purchase[DATE_COL].dt.year
first_purchase["month"] = first_purchase[DATE_COL].dt.month

new_monthly = (
    first_purchase[first_purchase["year"] == year_opt]
    .groupby("month", as_index=False)
    .size()
    .rename(columns={"size": "new_customers"})
)

# ------------------- Total customers (unique/day) -------------------
df_year = df[df[DATE_COL].dt.year == year_opt].copy()
df_year["date_day"] = df_year[DATE_COL].dt.normalize()
df_year["month"]    = df_year[DATE_COL].dt.month
df_year_unique = df_year.drop_duplicates(subset=[CUSTOMER_COL, "date_day"]).copy()

total_monthly = (
    df_year_unique.groupby("month")[CUSTOMER_COL]
    .nunique()
    .reset_index(name="total_unique_customers")
)

# ------------------- Merge -------------------
max_month = (today.month if year_opt == today.year else 12)
months = pd.DataFrame({"month": list(range(1, max_month + 1))})
res = (months.merge(total_monthly, on="month", how="left")
             .merge(new_monthly, on="month", how="left")
             .fillna(0))
res["total_unique_customers"] = res["total_unique_customers"].astype(int)
res["new_customers"]          = res["new_customers"].astype(int)
res["returning_customers"]    = (res["total_unique_customers"] - res["new_customers"]).clip(lower=0).astype(int)
res["month_label"]            = res["month"].apply(lambda m: f"{year_opt}-{m:02d}")

# ------------------- Chart 1: Stacked Bar -------------------
fig = go.Figure()
fig.add_trace(go.Bar(
    x=res["month_label"], y=res["returning_customers"],
    name="مشتریان برگشتی", text=res["returning_customers"],
    textposition="inside", insidetextanchor="middle"
))
fig.add_trace(go.Bar(
    x=res["month_label"], y=res["new_customers"],
    name="مشتریان جدید", text=res["new_customers"],
    textposition="inside", insidetextanchor="middle"
))
fig.update_layout(
    barmode="stack",
    title=f"مشتریان جدید و کل (انباشته) — {year_opt}",
    font=dict(size=16), title_font=dict(size=22), legend=dict(font=dict(size=14))
)
fig.update_traces(texttemplate="%{text}", textfont_size=14, cliponaxis=False)
fig.update_xaxes(title_text="سال-ماه", tickfont=dict(size=14), title_font=dict(size=18))
fig.update_yaxes(title_text="تعداد مشتری", tickfont=dict(size=14), title_font=dict(size=18))
for _, row in res.iterrows():
    fig.add_annotation(x=row["month_label"], y=int(row["total_unique_customers"]),
                       text=str(int(row["total_unique_customers"])),
                       showarrow=False, yshift=8, font=dict(size=14))
st.plotly_chart(fig, use_container_width=True)

# ------------------- Chart 2: Pie -------------------
tx_per_customer = df_year.groupby(CUSTOMER_COL).size().reset_index(name="tx_count")
def to_bucket(n): return "5+" if n >= 5 else str(int(n))
tx_per_customer["bucket"] = tx_per_customer["tx_count"].apply(to_bucket)
label_map = {"1": "۱ بار", "2": "۲ بار", "3": "۳ بار", "4": "۴ بار", "5+": "۵ بار یا بیشتر"}
tx_per_customer["bucket_label"] = tx_per_customer["bucket"].map(label_map)
dist = (tx_per_customer.groupby(["bucket","bucket_label"])
        .size().reset_index(name="n_customers"))
order = ["1","2","3","4","5+"]
dist["order"] = dist["bucket"].apply(lambda x: order.index(x))
dist = dist.sort_values("order")

fig_pie = px.pie(dist, names="bucket_label", values="n_customers",
                 title=f"توزیع تعداد خرید مشتریان در سال {year_opt}")
fig_pie.update_traces(textposition="inside", textinfo="label+percent+value")
fig_pie.update_layout(font=dict(size=16), title_font=dict(size=22), legend=dict(font=dict(size=14)))
st.plotly_chart(fig_pie, use_container_width=True)

# ------------------- لیست اسامی -------------------
with st.expander("📋 لیست اسامی مشتریان در هر دسته"):
    lists_by_bucket = (tx_per_customer.sort_values(["bucket", CUSTOMER_COL])
                       .groupby(["bucket","bucket_label"])[CUSTOMER_COL]
                       .apply(list).reset_index(name="customers"))
    lists_by_bucket["count"] = lists_by_bucket["customers"].apply(len)
    st.dataframe(lists_by_bucket[["bucket_label","count"]], use_container_width=True)
    for b in order:
        row = lists_by_bucket[lists_by_bucket["bucket"] == b]
        if row.empty:
            st.write(f"— دسته {label_map[b]}: موردی ندارد —")
            continue
        st.markdown(f"**مشتریان ({label_map[b]}) — {len(row['customers'].iloc[0])} نفر**")
        st.write(pd.DataFrame(row["customers"].iloc[0], columns=["نام مشتری"]))
