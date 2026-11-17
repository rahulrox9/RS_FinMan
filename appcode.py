import streamlit as st
import pandas as pd
import json
import os
import pdfplumber
import re
from datetime import datetime
from github import Github

CATEGORIES = [
    "Bank Transfer",
    "Bills & Utilities",
    "Cashbacks",
    "Credit Card Repayment",
    "Currency Transfer",
    "Distance Travel",
    "Entertainment",
    "Family Remittances",
    "Food - dining & delivery",
    "Groceries & Home Needs",
    "Income - Additional",
    "Income - GTA",
    "Income - Stipend",
    "Income - SNTPS",
    "Income - Others",
    "Interest",
    "Investment - FD",
    "Investment - Groww",
    "Local Transport",
    "Others",
    "Pension - APY",
    "Pot Transfer",
    "Rent",
    "Shopping",
    "Subscriptions",
    "Trip Expenses",
    "Uncategorised"
]

PAYMENT_METHODS = ["UPI", "Bank Transfer", "Debit Card", "Credit Card - Pixel", "Credit Card - Appa", "Credit Card - Monzo Flex", "Cash"]
CURRENCIES = ["INR", "GBP", "EUR"]

MAPPING_FILE = "category_mapping.json"
PM_MAPPING_FILE = "payment_mapping.json"
DB_FILE = "transactions_db.csv"
EXCLUDED_TERMS = ["top-uptoupilite", "selftransfer"]

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return {}

def save_json(data, file_path):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

def load_db():
    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE)
            df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
            df["Remember Mapping"] = df["Remember Mapping"].astype(bool)
            if "Remember PM" not in df.columns:
                df["Remember PM"] = False
            else:
                df["Remember PM"] = df["Remember PM"].astype(bool)
            return df
        except Exception:
            pass
            
    return pd.DataFrame({
        "Date": pd.Series(dtype='str'),
        "Transaction ID": pd.Series(dtype='str'),
        "Description": pd.Series(dtype='str'),
        "Amount": pd.Series(dtype='float'),
        "Currency": pd.Series(dtype='str'),
        "Type": pd.Series(dtype='str'),
        "Payment Method": pd.Series(dtype='str'),
        "Category": pd.Series(dtype='str'),
        "Remember Mapping": pd.Series(dtype='bool'),
        "Remember PM": pd.Series(dtype='bool')
    })

def save_db(df):
    df.to_csv(DB_FILE, index=False)

def guess_category(description, mappings):
    desc_lower = str(description).lower()
    for keyword, category in mappings.items():
        if keyword in desc_lower:
            return category
    return "Uncategorised"

def guess_payment_method(description, pm_mappings):
    desc_lower = str(description).lower()
    for keyword, pm in pm_mappings.items():
        if keyword in desc_lower:
            return pm
    return "Bank Transfer"

def sync_selected_mappings():
    if "tx_editor" in st.session_state:
        edited_rows = st.session_state.tx_editor.get("edited_rows", {})
        cat_mappings = load_json(MAPPING_FILE)
        pm_mappings = load_json(PM_MAPPING_FILE)
        
        for idx_str, edits in edited_rows.items():
            idx = int(idx_str)
            for col, val in edits.items():
                st.session_state.transactions.at[idx, col] = val
            
            desc = st.session_state.transactions.at[idx, "Description"]
            
            # Handle Category Mapping Propagation
            is_remembered = st.session_state.transactions.at[idx, "Remember Mapping"]
            new_cat = st.session_state.transactions.at[idx, "Category"]
            if is_remembered:
                mask = st.session_state.transactions["Description"] == desc
                st.session_state.transactions.loc[mask, "Category"] = new_cat
                st.session_state.transactions.loc[mask, "Remember Mapping"] = True
                cat_mappings[desc.lower()] = new_cat
                save_json(cat_mappings, MAPPING_FILE)
                
            # Handle Payment Method Auto-Replace / Propagation
            new_pm = st.session_state.transactions.at[idx, "Payment Method"]
            is_remembered_pm = st.session_state.transactions.at[idx, "Remember PM"]
            if is_remembered_pm or "Payment Method" in edits:
                mask = st.session_state.transactions["Description"] == desc
                st.session_state.transactions.loc[mask, "Payment Method"] = new_pm
                st.session_state.transactions.loc[mask, "Remember PM"] = True
                pm_mappings[desc.lower()] = new_pm
                save_json(pm_mappings, PM_MAPPING_FILE)
                
        save_db(st.session_state.transactions)

def push_to_github():
    try:
        g = Github(st.secrets["GITHUB_TOKEN"])
        repo = g.get_repo(st.secrets["REPO_NAME"])
        
        for file_name in [DB_FILE, MAPPING_FILE, PM_MAPPING_FILE]:
            if os.path.exists(file_name):
                with open(file_name, "r") as f:
                    content = f.read()
                try:
                    contents = repo.get_contents(file_name)
                    repo.update_file(contents.path, f"Sync {file_name}", content, contents.sha)
                except Exception:
                    repo.create_file(file_name, f"Initial commit {file_name}", content)
        st.success("Successfully pushed database and mappings to GitHub!")
    except Exception as e:
        st.error(f"GitHub Sync failed. Verify your Streamlit secrets. Error: {e}")

if 'transactions' not in st.session_state:
    st.session_state.transactions = load_db()

if 'split_target_idx' not in st.session_state:
    st.session_state.split_target_idx = None

if 'delete_target_idx' not in st.session_state:
    st.session_state.delete_target_idx = None

st.set_page_config(layout="wide")
st.title("Multi-Currency Financial Manager")

with st.sidebar:
    st.header("Cloud Controls")
    if st.button("Sync Database to GitHub"):
        push_to_github()

tab1, tab2 = st.tabs(["Data Entry & Review", "Analytical Dashboard"])

with tab1:
    st.subheader("Statement Uploads")
    bank_type = st.selectbox("Select Statement Source", ["Google Pay (PDF)", "HDFC (CSV)", "Monzo (CSV)", "Revolut (CSV)"])
    uploaded_file = st.file_uploader(f"Upload {bank_type} file", type=["pdf", "csv"])
    
    if uploaded_file:
        mappings = load_json(MAPPING_FILE)
        pm_mappings = load_json(PM_MAPPING_FILE)
        new_data = []
        
        if bank_type == "Google Pay (PDF)":
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
                                if any(term in normalized_desc for term in EXCLUDED_TERMS):
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
                                
                                date_clean = date_str
                                d_match = re.search(r'^(\d{1,2})\s*([A-Za-z]{3})\s*,\s*(\d{4})$', date_str)
                                if d_match:
                                    try:
                                        date_obj = datetime.strptime(f"{d_match.group(1)} {d_match.group(2)} {d_match.group(3)}", "%d %b %Y")
                                        date_clean = date_obj.strftime("%d-%m-%Y")
                                    except ValueError:
                                        pass
                                
                                tx_id = "UNKNOWN"
                                if i + 1 < len(lines):
                                    match2 = re.search(r'UPITransactionID:\s*(\d+)', lines[i+1].replace(" ", ""))
                                    if match2:
                                        tx_id = match2.group(1)
                                
                                clean_desc_str = desc.strip()
                                new_data.append({
                                    "Date": date_clean,
                                    "Transaction ID": f"GPAY_{tx_id}_{amount_str}",
                                    "Description": clean_desc_str,
                                    "Amount": float(amount_str),
                                    "Currency": "INR",
                                    "Type": tx_type,
                                    "Payment Method": guess_payment_method(clean_desc_str, pm_mappings),
                                    "Category": guess_category(clean_desc_str, mappings),
                                    "Remember Mapping": clean_desc_str.lower() in mappings,
                                    "Remember PM": clean_desc_str.lower() in pm_mappings
                                })
                                i += 2  
                                continue
                            i += 1
                            
        elif bank_type == "HDFC (CSV)":
            df_hdfc = pd.read_csv(uploaded_file)
            for _, row in df_hdfc.iterrows():
                date_val = str(row.get("Date", ""))
                if "*" in date_val or not date_val.strip():
                    continue
                narration = str(row.get("Narration", "")).strip()
                withdrawal = row.get("Withdrawal Amt.", 0)
                deposit = row.get("Deposit Amt.", 0)
                ref_no = str(row.get("Chq./Ref.No.", "UNKNOWN"))
                
                try:
                    dt = datetime.strptime(date_val.strip(), "%d/%m/%y")
                    formatted_date = dt.strftime("%d-%m-%Y")
                except:
                    formatted_date = date_val
                
                amount = 0.0
                tx_type = "Debit"
                if pd.notna(withdrawal) and str(withdrawal).strip() != "" and float(str(withdrawal).replace(",", "")) > 0:
                    amount = float(str(withdrawal).replace(",", ""))
                    tx_type = "Debit"
                elif pd.notna(deposit) and str(deposit).strip() != "" and float(str(deposit).replace(",", "")) > 0:
                    amount = float(str(deposit).replace(",", ""))
                    tx_type = "Credit"
                else:
                    continue
                
                new_data.append({
                    "Date": formatted_date,
                    "Transaction ID": f"HDFC_{ref_no}_{amount}",
                    "Description": narration,
                    "Amount": amount,
                    "Currency": "INR",
                    "Type": tx_type,
                    "Payment Method": guess_payment_method(narration, pm_mappings),
                    "Category": guess_category(narration, mappings),
                    "Remember Mapping": narration.lower() in mappings,
                    "Remember PM": narration.lower() in pm_mappings
                })
                
        elif bank_type == "Monzo (CSV)":
            df_monzo = pd.read_csv(uploaded_file)
            for _, row in df_monzo.iterrows():
                tx_id = str(row.get("Transaction ID", "MONZO_" + str(pd.Timestamp.now().timestamp())))
                date_raw = str(row.get("Date", ""))
                try:
                    dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
                    formatted_date = dt.strftime("%d-%m-%Y")
                except:
                    formatted_date = date_raw[:10]
                
                desc = str(row.get("Name", row.get("Description", "Monzo Tx"))).strip()
                amount = float(row.get("Amount", 0.0))
                currency = str(row.get("Currency", "GBP"))
                
                tx_type = "Credit" if amount > 0 else "Debit"
                default_pm = "Credit Card - Monzo Flex" if "Flex" in str(row.get("Product", "")) else guess_payment_method(desc, pm_mappings)
                
                new_data.append({
                    "Date": formatted_date,
                    "Transaction ID": tx_id,
                    "Description": desc,
                    "Amount": abs(amount),
                    "Currency": currency,
                    "Type": tx_type,
                    "Payment Method": default_pm,
                    "Category": guess_category(desc, mappings),
                    "Remember Mapping": desc.lower() in mappings,
                    "Remember PM": desc.lower() in pm_mappings
                })
                
        elif bank_type == "Revolut (CSV)":
            df_rev = pd.read_csv(uploaded_file)
            for _, row in df_rev.iterrows():
                date_raw = str(row.get("Completed Date", row.get("Started Date", "")))
                try:
                    dt = datetime.strptime(date_raw.split()[0], "%Y-%m-%d")
                    formatted_date = dt.strftime("%d-%m-%Y")
                except:
                    formatted_date = date_raw
                
                desc = str(row.get("Description", "Revolut Tx")).strip()
                amount = float(row.get("Amount", 0.0))
                currency = str(row.get("Currency", "GBP"))
                
                tx_type = "Credit" if amount > 0 else "Debit"
                
                new_data.append({
                    "Date": formatted_date,
                    "Transaction ID": f"REV_{formatted_date}_{amount}_{desc[:10]}",
                    "Description": desc,
                    "Amount": abs(amount),
                    "Currency": currency,
                    "Type": tx_type,
                    "Payment Method": guess_payment_method(desc, pm_mappings),
                    "Category": guess_category(desc, mappings),
                    "Remember Mapping": desc.lower() in mappings,
                    "Remember PM": desc.lower() in pm_mappings
                })
                
        if new_data:
            new_df = pd.DataFrame(new_data)
            st.session_state.transactions = pd.concat([st.session_state.transactions, new_df], ignore_index=True)
            st.session_state.transactions.drop_duplicates(subset=['Transaction ID'], keep='first', inplace=True)
            st.session_state.transactions.reset_index(drop=True, inplace=True)
            save_db(st.session_state.transactions)
            st.success("Statement processed, deduplicated, and auto-saved locally.")
        else:
            st.error("No valid transactions extracted.")
    
    st.subheader("Manual Entry")
    with st.form("manual_entry_form"):
        col1, col2, col3 = st.columns(3)
        m_date = col1.text_input("Date (DD-MM-YYYY)")
        m_desc = col2.text_input("Description")
        m_amount = col3.number_input("Amount", min_value=0.0, step=1.0)
        
        col4, col5, col6, col7 = st.columns(4)
        m_curr = col4.selectbox("Currency", CURRENCIES)
        m_type = col5.selectbox("Type", ["Debit", "Credit"])
        m_method = col6.selectbox("Payment Method", PAYMENT_METHODS)
        m_cat = col7.selectbox("Category", CATEGORIES)
        
        submitted = st.form_submit_button("Add Transaction")
        if submitted and m_date and m_desc:
            manual_row = pd.DataFrame([{
                "Date": m_date,
                "Transaction ID": "MANUAL_" + str(pd.Timestamp.now().timestamp()),
                "Description": m_desc,
                "Amount": float(m_amount),
                "Currency": m_curr,
                "Type": m_type,
                "Payment Method": m_method,
                "Category": m_cat,
                "Remember Mapping": False,
                "Remember PM": False
            }])
            st.session_state.transactions = pd.concat([st.session_state.transactions, manual_row], ignore_index=True)
            st.session_state.transactions.reset_index(drop=True, inplace=True)
            save_db(st.session_state.transactions)
            st.success("Manual transaction added.")

    if not st.session_state.transactions.empty:
        st.subheader("Review and Manage Transactions")
        
        edited_df = st.data_editor(
            st.session_state.transactions,
            key="tx_editor",
            on_change=sync_selected_mappings,
            column_config={
                "Category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
                "Type": st.column_config.SelectboxColumn("Type", options=["Debit", "Credit"], required=True),
                "Currency": st.column_config.SelectboxColumn("Currency", options=CURRENCIES, required=True),
                "Payment Method": st.column_config.SelectboxColumn("Payment Method", options=PAYMENT_METHODS, required=True),
                "Remember Mapping": st.column_config.CheckboxColumn("Remember Mapping", default=False),
                "Remember PM": st.column_config.CheckboxColumn("Remember PM", default=False)
            },
            hide_index=True,
            use_container_width=True
        )
        st.session_state.transactions = edited_df
        save_db(st.session_state.transactions)

        st.divider()
        st.subheader("Transaction Actions (Split & Delete)")
        
        tx_options = {f"Row {idx}: {row['Date']} | {row['Description']} | {row['Currency']} {row['Amount']}": idx for idx, row in st.session_state.transactions.iterrows()}
        
        if tx_options:
            selected_action_tx_label = st.selectbox("Select a transaction for actions", list(tx_options.keys()))
            target_idx = tx_options[selected_action_tx_label]
            
            act_col1, act_col2 = st.columns(2)
            with act_col1:
                if st.button("Split Selected Transaction"):
                    st.session_state.split_target_idx = target_idx
                    st.session_state.delete_target_idx = None
            with act_col2:
                if st.button("Delete Selected Transaction"):
                    st.session_state.delete_target_idx = target_idx
                    st.session_state.split_target_idx = None

            # Split Modal Form
            if st.session_state.split_target_idx is not None:
                s_idx = st.session_state.split_target_idx
                if s_idx in st.session_state.transactions.index:
                    t_row = st.session_state.transactions.loc[s_idx]
                    st.info(f"**Splitting Transaction:** {t_row['Date']} - {t_row['Description']} ({t_row['Currency']} {t_row['Amount']})")
                    
                    with st.form("popup_split_form"):
                        p1_amt = st.number_input("Part 1 Amount", min_value=0.0, value=float(t_row['Amount'])/2, step=1.0)
                        p1_cat = st.selectbox("Part 1 Category", CATEGORIES, index=0)
                        
                        p2_amt = st.number_input("Part 2 Amount", min_value=0.0, value=float(t_row['Amount'])/2, step=1.0)
                        p2_cat = st.selectbox("Part 2 Category", CATEGORIES, index=1 if len(CATEGORIES) > 1 else 0)
                        
                        col_sub1, col_sub2 = st.columns(2)
                        execute_split = col_sub1.form_submit_button("Confirm Split")
                        cancel_split = col_sub2.form_submit_button("Cancel")
                        
                        if cancel_split:
                            st.session_state.split_target_idx = None
                            st.rerun()
                            
                        if execute_split:
                            orig_amt = float(t_row["Amount"])
                            if abs((p1_amt + p2_amt) - orig_amt) > 0.01:
                                st.error(f"Split total ({p1_amt + p2_amt}) does not match original amount ({orig_amt}).")
                            else:
                                base_id = str(t_row["Transaction ID"])
                                row1 = t_row.copy()
                                row1["Amount"] = p1_amt
                                row1["Category"] = p1_cat
                                row1["Transaction ID"] = f"{base_id}_split1"
                                
                                row2 = t_row.copy()
                                row2["Amount"] = p2_amt
                                row2["Category"] = p2_cat
                                row2["Transaction ID"] = f"{base_id}_split2"
                                
                                st.session_state.transactions = st.session_state.transactions.drop(s_idx).reset_index(drop=True)
                                new_split_df = pd.DataFrame([row1, row2])
                                st.session_state.transactions = pd.concat([st.session_state.transactions, new_split_df], ignore_index=True)
                                save_db(st.session_state.transactions)
                                st.session_state.split_target_idx = None
                                st.success("Transaction split successfully!")
                                st.rerun()

            # Delete Safety Confirmation Popup
            if st.session_state.delete_target_idx is not None:
                d_idx = st.session_state.delete_target_idx
                if d_idx in st.session_state.transactions.index:
                    t_row = st.session_state.transactions.loc[d_idx]
                    st.warning(f"**Are you sure you want to delete this transaction?**\n\n{t_row['Date']} | {t_row['Description']} | {t_row['Currency']} {t_row['Amount']}")
                    
                    col_del1, col_del2 = st.columns(2)
                    if col_del1.button("Yes, Delete"):
                        st.session_state.transactions = st.session_state.transactions.drop(d_idx).reset_index(drop=True)
                        save_db(st.session_state.transactions)
                        st.session_state.delete_target_idx = None
                        st.success("Transaction deleted successfully.")
                        st.rerun()
                    if col_del2.button("No, Cancel"):
                        st.session_state.delete_target_idx = None
                        st.rerun()

with tab2:
    if st.session_state.transactions.empty:
        st.info("No data available.")
    else:
        selected_dashboard_curr = st.selectbox("Select Currency Filter for Dashboard", CURRENCIES)
        
        dash_df = st.session_state.transactions[st.session_state.transactions["Currency"] == selected_dashboard_curr].copy()
        
        if dash_df.empty:
            st.warning(f"No transactions found for {selected_dashboard_curr}.")
        else:
            dash_df["Amount"] = pd.to_numeric(dash_df["Amount"], errors="coerce")
            dash_df["Date_DT"] = pd.to_datetime(dash_df["Date"], format="%d-%m-%Y", errors="coerce")
            
            wealth_categories = [c for c in CATEGORIES if "Investment" in c or "Pension" in c]
            ignored_categories = ["Credit Card Repayment", "Currency Transfer", "Pot Transfer"]
            
            expenses_df = dash_df[
                (dash_df["Type"] == "Debit") & 
                (~dash_df["Category"].isin(wealth_categories)) & 
                (~dash_df["Category"].isin(ignored_categories))
            ]
            wealth_df = dash_df[(dash_df["Type"] == "Debit") & (dash_df["Category"].isin(wealth_categories))]
            income_df = dash_df[(dash_df["Type"] == "Credit") & (~dash_df["Category"].isin(ignored_categories))]
            
            total_expenses = expenses_df["Amount"].sum()
            total_wealth = wealth_df["Amount"].sum()
            total_income = income_df["Amount"].sum()
            total_rent = expenses_df[expenses_df["Category"] == "Rent"]["Amount"].sum()
            
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric(f"Living Expenses ({selected_dashboard_curr})", f"{total_expenses:,.2f}")
            col_m2.metric(f"Rent ({selected_dashboard_curr})", f"{total_rent:,.2f}")
            col_m3.metric(f"Investments & Pension ({selected_dashboard_curr})", f"{total_wealth:,.2f}")
            col_m4.metric(f"Income ({selected_dashboard_curr})", f"{total_income:,.2f}")
            
            st.divider()
            
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                st.subheader("Expenses by Category")
                if not expenses_df.empty:
                    cat_group = expenses_df.groupby("Category")["Amount"].sum().reset_index()
                    st.bar_chart(cat_group.set_index("Category"))
                else:
                    st.write("No expenses recorded.")
                    
            with col_c2:
                st.subheader("Daily Spending Trend")
                if not expenses_df.empty:
                    daily_spend = expenses_df.groupby("Date_DT")["Amount"].sum().reset_index()
                    st.line_chart(daily_spend.set_index("Date_DT"))
                else:
                    st.write("No trend data available.")
                    
            st.divider()
            
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.subheader("Granular Wealth Building Log")
                if not wealth_df.empty:
                    st.dataframe(wealth_df[["Date", "Description", "Category", "Amount"]], hide_index=True, use_container_width=True)
                else:
                    st.write("No investments or pension entries found.")
                    
            with col_t2:
                st.subheader("Top 5 Variable Expenses")
                non_rent_df = expenses_df[expenses_df["Category"] != "Rent"]
                if not non_rent_df.empty:
                    top_5 = non_rent_df.nlargest(5, "Amount")
                    st.dataframe(top_5[["Date", "Description", "Category", "Amount"]], hide_index=True, use_container_width=True)
                else:
                    st.write("No variable expenses found.")
