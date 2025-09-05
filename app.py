import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date
import matplotlib.pyplot as plt
import numpy as np
import io
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
import base64

# -------------------- Config --------------------
DB_PATH = "finance.db"
DEFAULT_CATEGORIES = ["Food", "Rent", "Transport", "Entertainment", "Utilities", "Shopping", "Health", "Other"]

# -------------------- Helpers --------------------
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    display_name TEXT,
                    created_at TEXT
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    type TEXT,
                    amount REAL,
                    category TEXT,
                    note TEXT,
                    date TEXT,
                    created_at TEXT
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS budgets (
                    user_id INTEGER PRIMARY KEY,
                    monthly_budget REAL,
                    updated_at TEXT
                )""")
    conn.commit()
    return conn

conn = init_db()

def add_user(username, display_name=None):
    now = datetime.utcnow().isoformat()
    try:
        conn.execute("INSERT INTO users (username, display_name, created_at) VALUES (?, ?, ?)", (username, display_name or username, now))
        conn.commit()
    except Exception:
        pass
    user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return user

def get_user(username):
    user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return user

def add_entry(user_id, type_, amount, category, note, date_str):
    now = datetime.utcnow().isoformat()
    conn.execute("INSERT INTO entries (user_id, type, amount, category, note, date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (user_id, type_, amount, category, note, date_str, now))
    conn.commit()

def get_entries_df(user_id):
    df = pd.read_sql_query("SELECT * FROM entries WHERE user_id=? ORDER BY date ASC", conn, params=(user_id,), parse_dates=["date"])
    if not df.empty:
        df['date'] = pd.to_datetime(df['date']).dt.date
    return df

def set_budget(user_id, amount):
    now = datetime.utcnow().isoformat()
    cur = conn.execute("SELECT * FROM budgets WHERE user_id=?", (user_id,)).fetchone()
    if cur:
        conn.execute("UPDATE budgets SET monthly_budget=?, updated_at=? WHERE user_id=?", (amount, now, user_id))
    else:
        conn.execute("INSERT INTO budgets (user_id, monthly_budget, updated_at) VALUES (?, ?, ?)", (user_id, amount, now))
    conn.commit()

def get_budget(user_id):
    cur = conn.execute("SELECT monthly_budget FROM budgets WHERE user_id=?", (user_id,)).fetchone()
    return cur[0] if cur else None

# -------------------- Financial Utils --------------------
def compute_summary(df):
    income = df[df['type']=='Income']['amount'].sum() if not df.empty else 0.0
    expenses = df[df['type']=='Expense']['amount'].sum() if not df.empty else 0.0
    savings = income - expenses
    return income, expenses, savings

def financial_health_score(income, expenses):
    if income <= 0:
        return 0
    save_ratio = max(0.0, (income - expenses) / income)  # 0..1
    score = int(save_ratio * 100)
    return min(max(score, 0), 100)

def generate_insights(df, income, expenses, budget):
    insights = []
    if not df.empty and (df['type']=='Expense').any():
        exp_df = df[df['type']=='Expense'].groupby('category')['amount'].sum().sort_values(ascending=False)
        top_cat = exp_df.index[0]
        top_pct = exp_df.iloc[0] / expenses if expenses>0 else 0
        if top_pct > 0.4:
            insights.append(f"⚠ You spend {top_pct:.0%} of your expenses on {top_cat}. Consider reducing it.")
        else:
            insights.append(f"✅ Your highest expense category is {top_cat} ({top_pct:.0%} of expenses).")
    if budget is not None:
        this_month = date.today().replace(day=1)
        monthly_exp = df[(df['type']=='Expense') & (pd.to_datetime(df['date']).dt.date >= this_month)]['amount'].sum() if not df.empty else 0
        if monthly_exp > budget:
            insights.append(f"🔴 You exceeded your monthly budget of ₹{budget:,.2f}. You've spent ₹{monthly_exp:,.2f} this month.")
        else:
            pct = (monthly_exp / budget) if budget>0 else 0
            insights.append(f"🟢 You used {pct:.0%} of your monthly budget (₹{monthly_exp:,.2f} of ₹{budget:,.2f}).")
    if income>0 and (income-expenses)/income < 0.05:
        insights.append("💡 Your savings are very low. Try reducing non-essential spending or increasing income.")
    if not insights:
        insights.append("No major issues detected. Keep tracking your expenses!")
    return insights

# -------------------- PDF Report --------------------
def create_pdf_report(user, df, income, expenses, savings, budget, score, images):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"Personal Finance Report - {user[2] or user[1]}", styles['Title']))
    story.append(Spacer(1,12))
    story.append(Paragraph(f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", styles['Normal']))
    story.append(Spacer(1,12))
    story.append(Paragraph(f"Total Income: ₹{income:,.2f}", styles['Normal']))
    story.append(Paragraph(f"Total Expenses: ₹{expenses:,.2f}", styles['Normal']))
    story.append(Paragraph(f"Savings: ₹{savings:,.2f}", styles['Normal']))
    if budget:
        story.append(Paragraph(f"Monthly Budget: ₹{budget:,.2f}", styles['Normal']))
    story.append(Paragraph(f"Financial Health Score: {score}/100", styles['Normal']))
    story.append(Spacer(1,12))
    for img_bytes in images:
        img_path = io.BytesIO(img_bytes)
        img_path.seek(0)
        rl_img = RLImage(img_path, width=450, height=300)
        story.append(rl_img)
        story.append(Spacer(1,12))
    doc.build(story)
    buffer.seek(0)
    return buffer

# -------------------- Streamlit App --------------------
st.set_page_config(page_title="Hackathon Finance Dashboard", layout="wide")

st.markdown("<h1 style='text-align:center'>Personal Finance Dashboard</h1>", unsafe_allow_html=True)

# Sidebar - User login / Profile
st.sidebar.header("Profile & Controls")
username = st.sidebar.text_input("Enter a username (simple login)", value="guest").strip()
if username:
    user = get_user(username)
    if not user:
        add_user(username, display_name=username)
        user = get_user(username)
    st.sidebar.success(f"Signed in as: {user[2] or user[1]}")
else:
    st.sidebar.info("Please enter a username to start")

# Theme toggle (Light/Dark)
theme = st.sidebar.radio("Theme", ("Light", "Dark"))
if theme == "Dark":
    st.markdown("""
    <style>
    .reportview-container { background: #0E1117; color: #E6EDF3; }
    .sidebar .sidebar-content { background: #0E1117; }
    </style>
    """, unsafe_allow_html=True)

# Budget input
st.sidebar.header("Budget Planner")
user_budget = get_budget(user[0]) if username else None
budget_input = st.sidebar.number_input("Set monthly budget (₹)", value=float(user_budget) if user_budget else 0.0, step=500.0)
if st.sidebar.button("Save Budget"):
    set_budget(user[0], budget_input)
    st.sidebar.success("Budget saved")

# Quick import/export
st.sidebar.header("Data Import / Export")
uploaded = st.sidebar.file_uploader("Import transactions CSV", type=["csv"])
if uploaded is not None:
    try:
        imp_df = pd.read_csv(uploaded, parse_dates=["date"])
        required_cols = {'type','amount','category','date'}
        if not required_cols.issubset(set(imp_df.columns.str.lower())):
            st.sidebar.error("CSV must have columns: type, amount, category, date")
        else:
            for _, row in imp_df.iterrows():
                ttype = str(row['type']).capitalize()
                amt = float(row['amount'])
                cat = row.get('category', 'Other')
                d = pd.to_datetime(row['date']).date().isoformat()
                add_entry(user[0], ttype, amt, cat, '', d)
            st.sidebar.success("Imported transactions")
    except Exception as e:
        st.sidebar.error(f"Import failed: {e}")

if st.sidebar.button("Export CSV"):
    df_export = get_entries_df(user[0])
    csv = df_export.to_csv(index=False).encode('utf-8')
    b64 = base64.b64encode(csv).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="transactions_{username}.csv">Download CSV</a>'
    st.sidebar.markdown(href, unsafe_allow_html=True)

# Main UI - Add Entry
st.subheader("Add Income / Expense")
with st.form("entry_form", clear_on_submit=True):
    cols = st.columns([1,1,1,1])
    with cols[0]:
        type_ = st.selectbox("Type", ["Income", "Expense"])
    with cols[1]:
        amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0)
    with cols[2]:
        category = st.selectbox("Category", DEFAULT_CATEGORIES + ["Other"])
    with cols[3]:
        date_in = st.date_input("Date", value=date.today())
    note = st.text_input("Note (optional)")
    submitted = st.form_submit_button("Add")
    if submitted:
        if amount <= 0:
            st.error("Enter a valid amount")
        else:
            add_entry(user[0], type_, float(amount), category, note, date_in.isoformat())
            st.success("Entry added")

# Load data
df = get_entries_df(user[0])

# Summary metrics
income, expenses, savings = compute_summary(df)
budget_val = get_budget(user[0])
score = financial_health_score(income, expenses)
insights = generate_insights(df, income, expenses, budget_val)

st.markdown("### Key Metrics")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Income", f"₹{income:,.2f}")
k2.metric("Total Expenses", f"₹{expenses:,.2f}")
k3.metric("Savings", f"₹{savings:,.2f}")
k4.metric("Health Score", f"{score}/100")

if budget_val:
    st.markdown(f"**Monthly Budget:** ₹{budget_val:,.2f}")

# Charts area
st.markdown("### Visualizations")
chart_col1, chart_col2 = st.columns([2,2])

# Pie chart - expense by category
with chart_col1:
    st.markdown("**Expenses by Category**")
    exp_df = df[df['type']=='Expense'].groupby('category')['amount'].sum() if not df.empty else pd.Series()
    if not exp_df.empty:
        fig1, ax1 = plt.subplots()
        ax1.pie(exp_df.values, labels=exp_df.index, autopct='%1.1f%%')
        ax1.set_aspect('equal')
        st.pyplot(fig1)
    else:
        st.info("No expense data to show")

# Line chart - cumulative savings over time
with chart_col2:
    st.markdown("**Savings Over Time**")
    if not df.empty:
        df_sorted = df.sort_values('date').copy()
        df_sorted['net'] = df_sorted.apply(lambda r: r['amount'] if r['type']=='Income' else -r['amount'], axis=1)
        trend = df_sorted.groupby('date')['net'].sum().cumsum()
        fig2, ax2 = plt.subplots()
        ax2.plot(trend.index.astype(str), trend.values, marker='o')
        ax2.set_xlabel('Date')
        ax2.set_ylabel('Cumulative Savings (₹)')
        plt.xticks(rotation=45)
        st.pyplot(fig2)
    else:
        st.info("No data yet to show trend")

# Additional charts
st.markdown("### More Insights")
colA, colB = st.columns(2)
with colA:
    st.markdown("**Expenses by Month**")
    if not df.empty:
        df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
        monthly = df[df['type']=='Expense'].groupby('month')['amount'].sum()
        if not monthly.empty:
            fig3, ax3 = plt.subplots()
            ax3.bar([str(m) for m in monthly.index.astype(str)], monthly.values)
            ax3.set_xlabel('Month')
            ax3.set_ylabel('Expenses (₹)')
            plt.xticks(rotation=45)
            st.pyplot(fig3)
        else:
            st.info("No expense data for months")
    else:
        st.info("No data")

with colB:
    st.markdown("**Spending Heatmap (Weekday vs Hour) - approximate**")
    if not df.empty:
        df['weekday'] = pd.to_datetime(df['date']).dt.day_name()
        heat = df[df['type']=='Expense'].groupby('weekday')['amount'].sum().reindex(
            ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']).fillna(0)
        fig4, ax4 = plt.subplots(figsize=(6,2))
        ax4.imshow(heat.values.reshape(1,-1), aspect='auto')
        ax4.set_xticks(range(len(heat.index)))
        ax4.set_xticklabels(heat.index, rotation=45)
        ax4.set_yticks([])
        ax4.set_title('Spending Heat (Total per weekday)')
        st.pyplot(fig4)
    else:
        st.info("No expense data")

# Transaction table with filters
st.markdown("### Transactions")
if not df.empty:
    st.dataframe(df[['date','type','amount','category','note']].sort_values('date', ascending=False))
else:
    st.info("No transactions yet. Add some to see the table.")

# Insights panel and tips
st.markdown("### Insights & Tips")
for ins in insights:
    st.write("-", ins)

# PDF export - capture charts images and include
if st.button("Generate PDF Report"):
    images = []
    if not exp_df.empty:
        buf1 = io.BytesIO()
        fig1.savefig(buf1, format='png', bbox_inches='tight')
        buf1.seek(0)
        images.append(buf1.read())
    if not df.empty:
        buf2 = io.BytesIO()
        fig2.savefig(buf2, format='png', bbox_inches='tight')
        buf2.seek(0)
        images.append(buf2.read())
    if 'fig3' in globals():
        buf3 = io.BytesIO()
        fig3.savefig(buf3, format='png', bbox_inches='tight')
        buf3.seek(0)
        images.append(buf3.read())
    pdf_buffer = create_pdf_report(user, df, income, expenses, savings, budget_val, score, images)
    b64 = base64.b64encode(pdf_buffer.read()).decode()
    href = f'<a href="data:application/pdf;base64,{b64}" download="finance_report_{username}.pdf">Download PDF Report</a>'
    st.markdown(href, unsafe_allow_html=True)