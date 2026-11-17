import streamlit as st
import pandas as pd
import json
import os
import pdfplumber
import re

CATEGORIES = [
    "Local Transport", "Distance Travel", "Food - dining & delivery", "Groceries", 
    "Rent", "Housing & Utilities", "Subscriptions", "Health & Grooming", 
    "Family Remittances", "Interest", "Pension", "Investments", 
    "Cashbacks", "Others", "Uncategorised"
]
MAPPING_FILE = "category_mapping.json"
EXPORT_FILE = "Processed_Statement.xlsx"

# Terms to completely ignore during PDF parsing (wallet top-ups, self-transfers)
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

if 'transactions' not in st.session_state:
    st.session_state.transactions = pd.DataFrame(columns=[
        "Date", "Transaction ID", "Description", "Amount", "Type", "Payment Method", "Category"
    ])

st.title("Local Secure Financial Manager")

tab1, tab2 = st.tabs(["Data Entry & Review", "Interactive Dashboard"])

with tab1:
    # File Upload Section
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
                            
                            # Check exclusions before processing
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
                                "Category": guess_category(desc, mappings)
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
    
    # Manual Entry Section
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
                "Amount": m_amount,
                "Type": m_type,
                "Payment Method": m_method,
                "Category": m_cat
            }])
            st.session_state.transactions = pd.concat([st.session_state.transactions, manual_row], ignore_index=True)
            st.session_state.transactions.reset_index(drop=True, inplace=True)
            st.success("Manual transaction added.")
    
    # Review and Edit Section
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
                )
            },
            hide_index=True,
            use_container_width=True
        )
        
        if st.button("Save Data & Export to Excel"):
            st.session_state.transactions = edited_df
            mappings = load_mappings()
            
            for index, row in edited_df.iterrows():
                if row["Category"] != "Uncategorised" and str(row["Description"]).strip():
                    keyword = str(row["Description"]).split()[0].lower()
                    mappings[keyword] = row["Category"]
            
            save_mappings(mappings)
            edited_df.to_excel(EXPORT_FILE, index=False)
            
            with open(EXPORT_FILE, "rb") as file:
                st.download_button(
                    label="Download Excel File",
                    data=file,
                    file_name=EXPORT_FILE,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

with tab2:
    st.header("Financial Dashboard")
    
    if st.session_state.transactions.empty:
        st.info("No data available. Please upload a statement or add transactions manually in the other tab.")
    else:
        dash_df = st.session_state.transactions.copy()
        
        col_f1, col_f2 = st.columns(2)
        selected_type = col_f1.multiselect("Filter by Type", ["Debit", "Credit"], default=["Debit", "Credit"])
        selected_method = col_f2.multiselect("Filter by Payment Method", ["UPI", "Debit Card", "Credit Card", "Cash"], default=["UPI", "Debit Card", "Credit Card", "Cash"])
        
        filtered_df = dash_df[
            (dash_df["Type"].isin(selected_type)) & 
            (dash_df["Payment Method"].isin(selected_method))
        ]
        
        total_debit = filtered_df[filtered_df["Type"] == "Debit"]["Amount"].sum()
        total_credit = filtered_df[filtered_df["Type"] == "Credit"]["Amount"].sum()
        
        col_m1, col_m2 = st.columns(2)
        col_m1.metric("Total Expenses (Debit)", f"₹ {total_debit:,.2f}")
        col_m2.metric("Total Income (Credit)", f"₹ {total_credit:,.2f}")
        
        st.divider()
        
        st.subheader("Expenses by Category")
        expense_df = filtered_df[filtered_df["Type"] == "Debit"]
        
        if not expense_df.empty:
            category_group = expense_df.groupby("Category")["Amount"].sum().reset_index()
            category_group = category_group.sort_values(by="Amount", ascending=False)
            
            st.bar_chart(category_group.set_index("Category"))
            
            top_category = category_group.iloc[0]["Category"]
            top_amount = category_group.iloc[0]["Amount"]
            st.caption(f"Highest expense category: **{top_category}** (₹ {top_amount:,.2f})")
        else:
            st.write("No expense data available for the selected filters.")
