# generate_report.py
import os, json
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path

SERVICE_ACCOUNT = os.environ["GOOGLE_SERVICE_ACCOUNT"]
SHEET_ID        = os.environ["SHEET_ID"]
WORKSHEET_NAME  = os.environ.get("WORKSHEET_NAME", "تراکنش ریالی")
DATE_COL        = os.environ.get("DATE_COL", "تاریخ")
CUSTOMER_COL    = os.environ.get("CUSTOMER_COL", "عرضه به")
EXCLUDED_TEXT   = os.environ.get("EXCLUDED_CUSTOMERS", "").strip()
EXCLUDED = [ln.strip() for ln in EXCLUDED_TEXT.splitlines() if ln.strip()]

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
creds = Credentials.from_service_account_info(json.loads(SERVICE_ACCOUNT), scopes=SCOPE)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SHEET_ID)
ws = sh.worksheet(WORKSHEET_NAME)
rows = ws.get_all_records()
df_raw = pd.DataFrame(rows)

# Clean
df_raw = df_raw.rename(columns={c: str(c).strip() for c in df_raw.columns})
df = df_raw[[DATE_COL, CUSTOMER_COL]].dropna(subset=[DATE_COL, CUSTOMER_COL]).copy()
df[DATE_COL] = pd.to_datetime(df[DATE_COL], dayfirst=False, errors="coerce")  # mm/dd/yyyy
df = df[df[DATE_COL].notna()]
df[CUSTOMER_COL] = df[CUSTOMER_COL].astype(str).str.strip()

today = pd.Timestamp.today().normalize()
df = df[df[DATE_COL] <= today]
if EXCLUDED:
    df = df[~df[CUSTOMER_COL].isin(EXCLUDED)]

current_year = today.year

# New customers (first-time by month)
first_purchase = df.groupby(CUSTOMER_COL, as_index=False)[DATE_COL].min()
first_purchase["year"]  = first_purchase[DATE_COL].dt.year
first_purchase["month"] = first_purchase[DATE_COL].dt.month
new_monthly = (
    first_purchase[first_purchase["year"] == current_year]
    .groupby("month", as_index=False)
    .size().rename(columns={"size": "new_customers"})
)

# Total unique customers per month (dedupe by customer per day)
df_year = df[df[DATE_COL].dt.year == current_year].copy()
df_year["date_day"] = df_year[DATE_COL].dt.normalize()
df_year["month"]    = df_year[DATE_COL].dt.month
df_year_unique = df_year.drop_duplicates(subset=[CUSTOMER_COL, "date_day"]).copy()
total_monthly = (
    df_year_unique.groupby("month")[CUSTOMER_COL]
    .nunique().reset_index(name="total_unique_customers")
)

# Merge
max_month = today.month
months = pd.DataFrame({"month": list(range(1, max_month + 1))})
res = (months.merge(total_monthly, on="month", how="left")
             .merge(new_monthly, on="month", how="left")
             .fillna(0))
res["total_unique_customers"] = res["total_unique_customers"].astype(int)
res["new_customers"]          = res["new_customers"].astype(int)
res["returning_customers"]    = (res["total_unique_customers"] - res["new_customers"]).clip(lower=0).astype(int)
res["month_label"]            = res["month"].apply(lambda m: f"{current_year}-{m:02d}")

# Bar (stacked)
fig_bar = go.Figure()
fig_bar.add_trace(go.Bar(
    x=res["month_label"], y=res["returning_customers"],
    name="مشتریان برگشتی", text=res["returning_customers"],
    textposition="inside", insidetextanchor="middle"
))
fig_bar.add_trace(go.Bar(
    x=res["month_label"], y=res["new_customers"],
    name="مشتریان جدید", text=res["new_customers"],
    textposition="inside", insidetextanchor="middle"
))
fig_bar.update_layout(
    barmode="stack",
    title=f"مشتریان جدید و کل (انباشته) — {current_year}",
    font=dict(size=16), title_font=dict(size=22), legend=dict(font=dict(size=14))
)
fig_bar.update_traces(texttemplate="%{text}", textfont_size=14, cliponaxis=False)
fig_bar.update_xaxes(title_text="سال-ماه", tickfont=dict(size=14), title_font=dict(size=18))
fig_bar.update_yaxes(title_text="تعداد مشتری", tickfont=dict(size=14), title_font=dict(size=18))

# Pie
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
                 title=f"توزیع تعداد خرید مشتریان در سال {current_year}")
fig_pie.update_traces(textposition="inside", textinfo="label+percent+value")
fig_pie.update_layout(font=dict(size=16), title_font=dict(size=22), legend=dict(font=dict(size=14)))

bar_html = fig_bar.to_html(full_html=False, include_plotlyjs="cdn")
pie_html = fig_pie.to_html(full_html=False, include_plotlyjs=False)

html = f"""
<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>گزارش مشتریان - {current_year}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
  <meta http-equiv="Pragma" content="no-cache" />
  <meta http-equiv="Expires" content="0" />
  <style>
    body {{ font-family: sans-serif; margin: 24px; }}
    h1 {{ font-size: 28px; margin-bottom: 12px; }}
    h2 {{ font-size: 20px; margin: 24px 0 12px; }}
    .chart {{ margin: 16px 0; }}
    .tbl {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
    .tbl th, .tbl td {{ border: 1px solid #ccc; padding: 8px; vertical-align: top; }}
    .tbl th {{ background: #f5f5f5; }}
    .note {{ color:#666; font-size:14px; }}
  </style>
</head>
<body>
  <h1>گزارش مشتریان — {current_year}</h1>
  <p class="note">این صفحه روزی یک بار به‌روزرسانی می‌شود. آخرین به‌روزرسانی: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

  <h2>۱) مشتریان جدید و کل (ستون انباشته)</h2>
  <div class="chart">{bar_html}</div>

  <h2>۲) توزیع تعداد خرید مشتریان</h2>
  <div class="chart">{pie_html}</div>

  <h2>۳) لیست اسامی مشتریان در هر دسته</h2>
  {table_html}
</body>
</html>
"""

out_dir = Path("build")
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "new_customers_report.html"
out_path.write_text(html, encoding="utf-8")
print(f"[OK] HTML written to: {out_path}")
