import streamlit as st
import pandas as pd
import json
import os
import pdfplumber
import re

CATEGORIES = [
    "Local Transport", "Distance Travel", "Dining & Delivery", "Groceries", 
    "Housing & Utilities", "Subscriptions", "Health & Grooming", 
    "Family Remittances", "Interest", "Pension", "Investments", 
    "Cashbacks", "Others", "Uncategorised"
]
MAPPING_FILE = "category_mapping.json"
EXPORT_FILE = "Processed_Statement.xlsx"

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

if 'transactions' not in st.session_state:
    st.session_state.transactions = pd.DataFrame(columns=[
        "Date", "Transaction ID", "Description", "Amount", "Type", "Payment Method", "Category"
    ])

st.title("Local Secure Financial Manager")

# File Upload Section
uploaded_file = st.file_uploader("Upload Google Pay Statement (PDF)", type="pdf")

if uploaded_file:
    mappings = load_mappings()
    new_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                i = 0
                while i < len(lines):
                    if re.match(r'^\d{1,2}\s+[A-Za-z]{3},\s+\d{4}$', lines[i]):
                        if i + 5 < len(lines) and "₹" in lines[i+5]:
                            date_str = lines[i]
                            raw_desc = lines[i+2]
                            raw_id = lines[i+3]
                            amount_str = lines[i+5].replace("₹", "").replace(",", "")
                            
                            tx_type = "Credit" if "Received" in raw_desc else "Debit"
                            desc = raw_desc.replace("Paid to ", "").replace("Received from ", "")
                            tx_id = raw_id.replace("UPI Transaction ID: ", "").strip()
                            
                            new_data.append({
                                "Date": date_str,
                                "Transaction ID": tx_id,
                                "Description": desc,
                                "Amount": float(amount_str),
                                "Type": tx_type,
                                "Payment Method": "UPI",
                                "Category": guess_category(desc, mappings)
                            })
                            i += 6
                            continue
                    i += 1
    
    if new_data:
        new_df = pd.DataFrame(new_data)
        st.session_state.transactions = pd.concat([st.session_state.transactions, new_df], ignore_index=True)
        st.session_state.transactions.drop_duplicates(subset=['Transaction ID'], keep='first', inplace=True)
        st.success("PDF Processed and Deduplicated.")
    else:
        st.error("No transactions matched. The PDF text structure might be aligned differently.")
        # Debugging: Show exactly how the first 30 lines are being read
        with pdfplumber.open(uploaded_file) as pdf:
            debug_text = pdf.pages[0].extract_text()
            debug_lines = [line.strip() for line in debug_text.split('\n') if line.strip()]
            st.write("### Debugging Output: First 30 lines")
            st.write(debug_lines[:30])

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
        st.success("Manual transaction added.")

# Review and Edit Section
if not st.session_state.transactions.empty:
    st.subheader("Review and Confirm Data")
    
    edited_df = st.data_editor(
        st.session_state.transactions,
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
