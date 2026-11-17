import streamlit as st
import pandas as pd
import json
import os
import pdfplumber
import re

CATEGORIES = [
    "Cashbacks",
    "Distance Travel",
    "Family Remittances",
    "Food - dining & delivery",
    "Groceries",
    "Health & Grooming",
    "Housing & Utilities",
    "Interest",
    "Investments",
    "Local Transport",
    "Others",
    "Pension",
    "Rent",
    "Shopping",
    "Subscriptions",
    "Trip Expense",
    "Uncategorised"
]

MAPPING_FILE = "category_mapping.json"
EXPORT_FILE = "Processed_Statement.xlsx"
EXCLUDED_TERMS = ["top-uptoupilite", "selftransfer"]

def load_mappings():
    if os.path.exists(MAPPING_FILE):
        with open(MAPPING_FILE, "r") as f:
            return json.load(f)
    return {}

def save_mappings(mappings):
    with open(MAPPING_FILE, "w") as f:
        json.dump(mappings, f, indent=4)

def guess_category(description, mappings):
    desc_lower = str(description).lower()
    for keyword, category in mappings.items():
        if keyword in desc_lower:
            return category
    return "Uncategorised"

def sync_categories():
    if "tx_editor" in st.session_state:
        edited_rows = st.session_state.tx_editor.get("edited_rows", {})
        for idx_str, edits in edited_rows.items():
            if "Category" in edits:
                new_cat = edits["Category"]
                idx = int(idx_str)
                desc = st.session_state.transactions.at[idx, "Description"]
                mask = st.session_state.transactions["Description"] == desc
                st.session_state.transactions.loc[mask, "Category"] = new_cat

# Strictly define column types to prevent Pandas TypeErrors during mathematical operations
if 'transactions' not in st.session_state:
    st.session_state.transactions = pd.DataFrame({
        "Date": pd.Series(dtype='str'),
        "Transaction ID": pd.Series(dtype='str'),
        "Description": pd.Series(dtype='str'),
        "Amount": pd.Series(dtype='float'),
        "Type": pd.Series(dtype='str'),
        "Payment Method": pd.Series(dtype='str'),
        "Category": pd.Series(dtype='str'),
        "Remember Mapping": pd.Series(dtype='bool')
    })

st.set_page_config(layout="wide")
st.title("Local Secure Financial Manager")

tab1, tab2 = st.tabs(["Data Entry & Review", "Analytical Dashboard"])

with tab1:
    uploaded_file = st.file_uploader("Upload Google Pay Statement (PDF)", type="pdf")
    
    if uploaded_file:
        mappings = load_mappings()
        new_data = []
        
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text(keep_blank_chars=True)
                if text:
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    i = 0
                    while i < len(lines):
                        match1 = re.search(r'^(\d{1,2}\s*[A-Za-z]{3}\s*,\s*\d{4})\s*(.*?)\s*₹\s*([\d,\.]+)', lines[i])
                        if match1:
                            date_str = match1.group(1)
                            raw_desc = match1.group(2).strip()
                            amount_str = match1.group(3).replace(",", "")
                            
                            normalized_desc = raw_desc.lower().replace(" ", "")
                            is_excluded = False
                            for term in EXCLUDED_TERMS:
                                if term in normalized_desc:
                                    is_excluded = True
                                    break
                            
                            if is_excluded:
                                i += 2
                                continue
                            
                            tx_type = "Debit"
                            desc = raw_desc
                            
                            if desc.startswith("Paid to "):
                                desc = desc[8:]
                            elif desc.startswith("Paidto"):
                                desc = desc[6:]
                            elif desc.startswith("Received from "):
                                desc = desc[14:]
                                tx_type = "Credit"
                            elif desc.startswith("Receivedfrom"):
                                desc = desc[12:]
                                tx_type = "Credit"
                                
                            desc = re.sub(r'([a-z])([A-Z])', r'\1 \2', desc)
                            date_clean = re.sub(r'^(\d{1,2})\s*([A-Za-z]{3})\s*,\s*(\d{4})$', r'\1 \2, \3', date_str)
                            
                            tx_id = "UNKNOWN"
                            if i + 1 < len(lines):
                                match2 = re.search(r'UPITransactionID:\s*(\d+)', lines[i+1].replace(" ", ""))
                                if match2:
                                    tx_id = match2.group(1)
                            
                            new_data.append({
                                "Date": date_clean,
                                "Transaction ID": tx_id,
                                "Description": desc.strip(),
                                "Amount": float(amount_str),
                                "Type": tx_type,
                                "Payment Method": "UPI",
                                "Category": guess_category(desc, mappings),
                                "Remember Mapping": False
                            })
                            i += 2  
                            continue
                        i += 1
                        
        if new_data:
            new_df = pd.DataFrame(new_data)
            st.session_state.transactions = pd.concat([st.session_state.transactions, new_df], ignore_index=True)
            st.session_state.transactions.drop_duplicates(subset=['Transaction ID'], keep='first', inplace=True)
            st.session_state.transactions.reset_index(drop=True, inplace=True)
            st.success("PDF Processed and Deduplicated.")
        else:
            st.error("No transactions matched.")
    
    st.subheader("Manual Entry (Cash / Missing Transactions)")
    with st.form("manual_entry_form"):
        col1, col2, col3 = st.columns(3)
        m_date = col1.text_input("Date (DD MMM, YYYY)")
        m_desc = col2.text_input("Description")
        m_amount = col3.number_input("Amount", min_value=0.0, step=1.0)
        
        col4, col5, col6 = st.columns(3)
        m_type = col4.selectbox("Type", ["Debit", "Credit"])
        m_method = col5.selectbox("Payment Method", ["Cash", "Credit Card", "Debit Card", "UPI"])
        m_cat = col6.selectbox("Category", CATEGORIES)
        
        submitted = st.form_submit_button("Add Transaction")
        if submitted and m_date and m_desc:
            manual_row = pd.DataFrame([{
                "Date": m_date,
                "Transaction ID": "MANUAL_" + str(pd.Timestamp.now().timestamp()),
                "Description": m_desc,
                "Amount": float(m_amount),
                "Type": m_type,
                "Payment Method": m_method,
                "Category": m_cat,
                "Remember Mapping": False
            }])
            st.session_state.transactions = pd.concat([st.session_state.transactions, manual_row], ignore_index=True)
            st.session_state.transactions.reset_index(drop=True, inplace=True)
            st.success("Manual transaction added.")
    
    if not st.session_state.transactions.empty:
        st.subheader("Review and Confirm Data")
        
        edited_df = st.data_editor(
            st.session_state.transactions,
            key="tx_editor",
            on_change=sync_categories,
            column_config={
                "Category": st.column_config.SelectboxColumn(
                    "Category",
                    options=CATEGORIES,
                    required=True
                ),
                "Type": st.column_config.SelectboxColumn(
                    "Type",
                    options=["Debit", "Credit"],
                    required=True
                ),
                "Payment Method": st.column_config.SelectboxColumn(
                    "Payment Method",
                    options=["UPI", "Debit Card", "Credit Card", "Cash"],
                    required=True
                ),
                "Remember Mapping": st.column_config.CheckboxColumn(
                    "Remember Mapping",
                    help="Check this box to permanently save this vendor's categorisation.",
                    default=False
                )
            },
            hide_index=True,
            use_container_width=True
        )
        
        if st.button("Save Data & Export to Excel"):
            st.session_state.transactions = edited_df
            mappings = load_mappings()
            
            # Only update mappings if the user explicitly ticked the checkbox
            for index, row in edited_df.iterrows():
                if row.get("Remember Mapping", False) and row["Category"] != "Uncategorised" and str(row["Description"]).strip():
                    keyword = str(row["Description"]).split()[0].lower()
                    mappings[keyword] = row["Category"]
            
            save_mappings(mappings)
            
            export_df = edited_df.drop(columns=["Remember Mapping"])
            export_df.to_excel(EXPORT_FILE, index=False)
            
            with open(EXPORT_FILE, "rb") as file:
                st.download_button(
                    label="Download Excel File",
                    data=file,
                    file_name=EXPORT_FILE,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

with tab2:
    if st.session_state.transactions.empty:
        st.info("No data available. Process a statement to generate dashboard.")
    else:
        dash_df = st.session_state.transactions.copy()
        
        # Double safety net: force Amount column to numeric right before calculations
        dash_df["Amount"] = pd.to_numeric(dash_df["Amount"], errors="coerce")
        dash_df["Date_DT"] = pd.to_datetime(dash_df["Date"], format="%d %b, %Y", errors="coerce")
        
        wealth_categories = ["Investments", "Pension"]
        
        expenses_df = dash_df[(dash_df["Type"] == "Debit") & (~dash_df["Category"].isin(wealth_categories))]
        wealth_df = dash_df[(dash_df["Type"] == "Debit") & (dash_df["Category"].isin(wealth_categories))]
        income_df = dash_df[dash_df["Type"] == "Credit"]
        
        total_expenses = expenses_df["Amount"].sum()
        total_wealth = wealth_df["Amount"].sum()
        total_income = income_df["Amount"].sum()
        total_rent = expenses_df[expenses_df["Category"] == "Rent"]["Amount"].sum()
        
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Living Expenses", f"₹ {total_expenses:,.2f}")
        col_m2.metric("Rent", f"₹ {total_rent:,.2f}")
        col_m3.metric("Investments & Pension", f"₹ {total_wealth:,.2f}")
        col_m4.metric("Income / Cashbacks", f"₹ {total_income:,.2f}")
        
        st.divider()
        
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            st.subheader("Expenses by Category")
            if not expenses_df.empty:
                cat_group = expenses_df.groupby("Category")["Amount"].sum().reset_index()
                st.bar_chart(cat_group.set_index("Category"))
                
        with col_c2:
            st.subheader("Daily Spending Trend")
            if not expenses_df.empty:
                daily_spend = expenses_df.groupby("Date_DT")["Amount"].sum().reset_index()
                st.line_chart(daily_spend.set_index("Date_DT"))
                
        st.divider()
        
        col_t1, col_t2 = st.columns(2)
        
        with col_t1:
            st.subheader("Wealth Building Log")
            if not wealth_df.empty:
                st.dataframe(wealth_df[["Date", "Description", "Category", "Amount"]], hide_index=True, use_container_width=True)
            else:
                st.write("No investments or pension recorded.")
                
        with col_t2:
            st.subheader("Top 5 Variable Expenses")
            non_rent_df = expenses_df[expenses_df["Category"] != "Rent"]
            if not non_rent_df.empty:
                top_5 = non_rent_df.nlargest(5, "Amount")
                st.dataframe(top_5[["Date", "Description", "Category", "Amount"]], hide_index=True, use_container_width=True)
            else:
                st.write("No variable expenses recorded.")
