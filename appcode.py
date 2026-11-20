import streamlit as st
import pandas as pd
import json
import os
import io
import pdfplumber
import re
from datetime import datetime
from github import Github
import plotly.express as px

CATEGORIES = [
    "Bank Transfer",
    "Bills & Utilities",
    "Cashbacks",
    "Credit Card Repayment",
    "Currency Transfer",
    "Entertainment",
    "Family Remittances",
    "Food - dining & delivery",
    "Groceries & Home Needs",
    "Income - UoM GTA",
    "Income - UoM Extras",
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

INCOME_CATEGORIES = [
    "Income - UoM GTA",
    "Income - UoM Extras",
    "Income - Stipend",
    "Income - SNTPS",
    "Income - Others",
    "Interest"
]

WEALTH_CATEGORIES = [
    "Investment - FD",
    "Investment - Groww",
    "Pension - APY"
]

EXCLUDED_CATEGORIES = [
    "Bank Transfer",
    "Cashbacks",
    "Credit Card Repayment",
    "Currency Transfer",
    "Family Remittances",
    "Pot Transfer"
]

EXPENDITURE_CATEGORIES = [
    c for c in CATEGORIES
    if c not in INCOME_CATEGORIES and c not in WEALTH_CATEGORIES and c not in EXCLUDED_CATEGORIES
]

PAYMENT_METHODS = ["Debit Card", "UPI", "Bank Transfer", "Credit Card - Pixel", "Credit Card - Appa", "Credit Card - Monzo Flex", "Cash"]
CURRENCIES = ["INR", "GBP", "EUR"]

MAPPING_FILE = "category_mapping.json"
DB_FILE = "transactions_db.csv"
EXCLUDED_TERMS = ["top-uptoupilite", "selftransfer"]

def load_mappings():
    if os.path.exists(MAPPING_FILE):
        with open(MAPPING_FILE, "r") as f:
            raw_map = json.load(f)
        return {k: ("Trip Expenses" if v == "Distance Travel" else v) for k, v in raw_map.items()}
    return {}

def save_mappings(mappings):
    with open(MAPPING_FILE, "w") as f:
        json.dump(mappings, f, indent=4)

def apply_uom_credit_rule(df):
    if not df.empty and {"Description", "Type", "Payment Method"}.issubset(df.columns):
        uom_mask = (
            df["Description"].astype(str).str.lower().str.contains("the university of manchester", na=False)
            & (df["Type"].astype(str).str.strip() == "Credit")
        )
        df.loc[uom_mask, "Payment Method"] = "Bank Transfer"
    return df

def load_db():
    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE)
            df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
            if "Category" in df.columns:
                df["Category"] = df["Category"].replace({"Distance Travel": "Trip Expenses"}).fillna("Uncategorised")
            for col in ["Select", "Remember Mapping"]:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.lower() == "true"
                else:
                    df[col] = False
            return apply_uom_credit_rule(df)
        except Exception:
            pass

    return pd.DataFrame({
        "Select": pd.Series(dtype="bool"),
        "Date": pd.Series(dtype="str"),
        "Transaction ID": pd.Series(dtype="str"),
        "Description": pd.Series(dtype="str"),
        "Amount": pd.Series(dtype="float"),
        "Currency": pd.Series(dtype="str"),
        "Type": pd.Series(dtype="str"),
        "Payment Method": pd.Series(dtype="str"),
        "Category": pd.Series(dtype="str"),
        "Remember Mapping": pd.Series(dtype="bool")
    })

def save_db(df):
    df.to_csv(DB_FILE, index=False)

def guess_category(description, mappings):
    desc_lower = str(description).strip().lower()
    for keyword, category in mappings.items():
        if keyword in desc_lower:
            return category
    return "Uncategorised"

def push_to_github():
    try:
        g = Github(st.secrets["GITHUB_TOKEN"])
        repo = g.get_repo(st.secrets["REPO_NAME"])

        for file_name in [DB_FILE, MAPPING_FILE]:
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

if "transactions" not in st.session_state:
    st.session_state.transactions = load_db()
else:
    st.session_state.transactions = apply_uom_credit_rule(st.session_state.transactions)

if "split_target_idx" not in st.session_state:
    st.session_state.split_target_idx = None

if "confirm_delete" not in st.session_state:
    st.session_state.confirm_delete = False

if "filtered_indices" not in st.session_state:
    st.session_state.filtered_indices = st.session_state.transactions.index.tolist()

def handle_editor_change():
    if "tx_editor" in st.session_state:
        editor_state = st.session_state.tx_editor
        edited_rows = editor_state.get("edited_rows", {})
        filtered_indices = st.session_state.get("filtered_indices", [])

        mappings = load_mappings()
        mappings_updated = False

        for pos_str, edits in edited_rows.items():
            pos = int(pos_str)
            if pos >= len(filtered_indices):
                continue
            idx = filtered_indices[pos]

            if edits.get("Select") is True:
                st.session_state.transactions["Select"] = False

            for col, val in edits.items():
                st.session_state.transactions.at[idx, col] = val

            row_desc = str(st.session_state.transactions.at[idx, "Description"]).strip().lower()
            row_type = str(st.session_state.transactions.at[idx, "Type"]).strip()
            if "the university of manchester" in row_desc and row_type == "Credit":
                st.session_state.transactions.at[idx, "Payment Method"] = "Bank Transfer"

            is_remembered = st.session_state.transactions.at[idx, "Remember Mapping"]
            if is_remembered:
                desc = str(st.session_state.transactions.at[idx, "Description"]).strip().lower()
                new_cat = st.session_state.transactions.at[idx, "Category"]

                mappings[desc] = new_cat
                mappings_updated = True

                mask = st.session_state.transactions["Description"].str.strip().str.lower() == desc
                st.session_state.transactions.loc[mask, "Category"] = new_cat
                st.session_state.transactions.loc[mask, "Remember Mapping"] = True

        if mappings_updated:
            save_mappings(mappings)

        save_db(st.session_state.transactions)

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
    uploaded_file = st.file_uploader(f"Upload {bank_type} file", type=["pdf", "csv", "xlsx"])

    if uploaded_file:
        mappings = load_mappings()
        new_data = []
        debug_info = ""

        if bank_type == "Google Pay (PDF)":
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    text = page.extract_text(keep_blank_chars=True)
                    if text:
                        lines = [line.strip() for line in text.split("\n") if line.strip()]
                        i = 0
                        while i < len(lines):
                            match1 = re.search(r"^(\d{1,2}\s*[A-Za-z]{3}\s*,\s*\d{4})\s*(.*?)\s*₹\s*([\d,\.]+)", lines[i])
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

                                desc = re.sub(r"([a-z])([A-Z])", r"\1 \2", desc)

                                date_clean = date_str
                                d_match = re.search(r"^(\d{1,2})\s*([A-Za-z]{3})\s*,\s*(\d{4})$", date_str)
                                if d_match:
                                    try:
                                        date_obj = datetime.strptime(f"{d_match.group(1)} {d_match.group(2)} {d_match.group(3)}", "%d %b %Y")
                                        date_clean = date_obj.strftime("%d-%m-%Y")
                                    except ValueError:
                                        pass

                                tx_id = "UNKNOWN"
                                if i + 1 < len(lines):
                                    match2 = re.search(r"UPITransactionID:\s*(\d+)", lines[i + 1].replace(" ", ""))
                                    if match2:
                                        tx_id = match2.group(1)

                                payment_method = (
                                    "Bank Transfer"
                                    if ("the university of manchester" in desc.lower() and tx_type == "Credit")
                                    else "Debit Card"
                                )

                                new_data.append({
                                    "Select": False,
                                    "Date": date_clean,
                                    "Transaction ID": f"GPAY_{tx_id}_{amount_str}",
                                    "Description": desc.strip(),
                                    "Amount": float(amount_str),
                                    "Currency": "INR",
                                    "Type": tx_type,
                                    "Payment Method": payment_method,
                                    "Category": guess_category(desc, mappings),
                                    "Remember Mapping": False
                                })
                                i += 2
                                continue
                            i += 1

        elif bank_type == "HDFC (CSV)":
            raw_bytes = uploaded_file.getvalue()
            if raw_bytes.startswith(b"PK\x03\x04"):
                df_hdfc = pd.read_excel(io.BytesIO(raw_bytes))
            else:
                df_hdfc = pd.read_csv(io.BytesIO(raw_bytes), encoding="latin-1")
            df_hdfc.columns = df_hdfc.columns.str.strip()
            debug_info = f"Detected columns: {list(df_hdfc.columns)}"
            for _, row in df_hdfc.iterrows():
                date_val = str(row.get("Date", ""))
                if "*" in date_val or not date_val.strip() or date_val == "nan":
                    continue
                narration = str(row.get("Narration", ""))
                withdrawal = row.get("Withdrawal Amt.", 0)
                deposit = row.get("Deposit Amt.", 0)
                ref_no = str(row.get("Chq./Ref.No.", "UNKNOWN"))

                try:
                    dt = datetime.strptime(date_val.strip(), "%d/%m/%y")
                    formatted_date = dt.strftime("%d-%m-%Y")
                except Exception:
                    formatted_date = date_val.strip()

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

                payment_method = (
                    "Bank Transfer"
                    if ("the university of manchester" in narration.lower() and tx_type == "Credit")
                    else "Debit Card"
                )

                new_data.append({
                    "Select": False,
                    "Date": formatted_date,
                    "Transaction ID": f"HDFC_{ref_no}_{amount}",
                    "Description": narration.strip(),
                    "Amount": amount,
                    "Currency": "INR",
                    "Type": tx_type,
                    "Payment Method": payment_method,
                    "Category": guess_category(narration, mappings),
                    "Remember Mapping": False
                })

        elif bank_type == "Monzo (CSV)":
            raw_bytes = uploaded_file.getvalue()
            if raw_bytes.startswith(b"PK\x03\x04"):
                df_monzo = pd.read_excel(io.BytesIO(raw_bytes))
            else:
                df_monzo = pd.read_csv(io.BytesIO(raw_bytes), sep=None, engine="python", encoding="latin-1", on_bad_lines="skip")
            df_monzo.columns = df_monzo.columns.str.strip()
            debug_info = f"Detected columns: {list(df_monzo.columns)}"
            for _, row in df_monzo.iterrows():
                tx_id = str(row.get("Transaction ID", "")).strip()
                if not tx_id or tx_id == "nan":
                    continue

                amt_raw = row.get("Amount", 0.0)
                try:
                    amount = float(str(amt_raw).replace(",", ""))
                except ValueError:
                    continue
                if amount == 0.0:
                    continue

                date_raw = str(row.get("Date", "")).strip()
                parsed_dt = pd.to_datetime(date_raw, dayfirst=True, errors="coerce")
                formatted_date = parsed_dt.strftime("%d-%m-%Y") if pd.notna(parsed_dt) else date_raw[:10]

                name_val = row.get("Name")
                desc_val = row.get("Description")
                type_val = str(row.get("Type", "")).strip()

                if pd.notna(name_val) and str(name_val).strip() != "":
                    desc = str(name_val).strip()
                elif pd.notna(desc_val) and str(desc_val).strip() != "":
                    desc = str(desc_val).strip()
                else:
                    desc = type_val if type_val else "Monzo Tx"

                currency = str(row.get("Currency", "GBP")).strip()
                tx_type = "Credit" if amount > 0 else "Debit"
                if "the university of manchester" in desc.lower() and tx_type == "Credit":
                    payment_method = "Bank Transfer"
                elif "flex" in type_val.lower():
                    payment_method = "Credit Card - Monzo Flex"
                else:
                    payment_method = "Debit Card"
                category = "Pot Transfer" if "pot transfer" in type_val.lower() else guess_category(desc, mappings)

                new_data.append({
                    "Select": False,
                    "Date": formatted_date,
                    "Transaction ID": tx_id,
                    "Description": desc,
                    "Amount": abs(amount),
                    "Currency": currency,
                    "Type": tx_type,
                    "Payment Method": payment_method,
                    "Category": category,
                    "Remember Mapping": False
                })

        elif bank_type == "Revolut (CSV)":
            raw_bytes = uploaded_file.getvalue()
            if raw_bytes.startswith(b"PK\x03\x04"):
                preview_df = pd.read_excel(io.BytesIO(raw_bytes), header=None, nrows=15)
                header_idx = 0
                for idx, row_vals in preview_df.iterrows():
                    row_str = " ".join([str(v) for v in row_vals.values if pd.notna(v)])
                    if "Description" in row_str and "Amount" in row_str:
                        header_idx = idx
                        break
                df_rev = pd.read_excel(io.BytesIO(raw_bytes), skiprows=header_idx)
                df_rev.columns = df_rev.columns.astype(str).str.strip()
                debug_info = f"Format: XLSX, Header row: {header_idx}, Columns: {list(df_rev.columns)}"
            else:
                try:
                    text_content = raw_bytes.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text_content = raw_bytes.decode("latin-1")

                lines = text_content.splitlines()
                header_idx = 0
                detected_sep = ","
                for idx, line in enumerate(lines[:15]):
                    if "Description" in line and "Amount" in line:
                        header_idx = idx
                        if "\t" in line:
                            detected_sep = "\t"
                        elif ";" in line and "," not in line:
                            detected_sep = ";"
                        else:
                            detected_sep = ","
                        break

                df_rev = pd.read_csv(
                    io.StringIO(text_content),
                    sep=detected_sep,
                    skiprows=header_idx,
                    on_bad_lines="skip"
                )
                df_rev.columns = df_rev.columns.astype(str).str.strip()
                debug_info = f"Format: CSV, Header row: {header_idx}, Separator: {repr(detected_sep)}, Columns: {list(df_rev.columns)}"

            rev_id_counts = {}
            for _, row in df_rev.iterrows():
                date_raw = row.get("Completed Date")
                if pd.isna(date_raw) or str(date_raw).strip() == "":
                    date_raw = row.get("Started Date")
                if pd.isna(date_raw) or str(date_raw).strip() == "":
                    continue

                parsed_dt = pd.to_datetime(str(date_raw).strip(), dayfirst=True, errors="coerce")
                if pd.isna(parsed_dt):
                    parsed_dt = pd.to_datetime(str(date_raw).strip(), errors="coerce")
                if pd.isna(parsed_dt):
                    continue
                formatted_date = parsed_dt.strftime("%d-%m-%Y")

                desc_val = row.get("Description")
                desc = str(desc_val).strip() if pd.notna(desc_val) and str(desc_val).strip() != "" else "Revolut Tx"

                amount_val = row.get("Amount")
                if pd.isna(amount_val):
                    continue
                try:
                    amount = float(str(amount_val).replace(",", "").strip())
                except ValueError:
                    continue
                if amount == 0.0:
                    continue

                currency_val = row.get("Currency")
                currency = str(currency_val).strip() if pd.notna(currency_val) and str(currency_val).strip() != "" else "GBP"

                state_val = row.get("State")
                state = str(state_val).strip().upper() if pd.notna(state_val) else "COMPLETED"
                if state in ["FAILED", "REVERTED", "DECLINED"]:
                    continue

                tx_type = "Credit" if amount > 0 else "Debit"
                product_val = row.get("Product")
                product = str(product_val).strip() if pd.notna(product_val) else "Current"
                if "the university of manchester" in desc.lower() and tx_type == "Credit":
                    payment_method = "Bank Transfer"
                elif "Flex" in product:
                    payment_method = "Credit Card - Monzo Flex"
                else:
                    payment_method = "Debit Card"

                rev_type_val = row.get("Type")
                rev_type = str(rev_type_val).strip().lower() if pd.notna(rev_type_val) else ""
                if "pot" in rev_type or "vault" in rev_type or "pocket" in rev_type:
                    category = "Pot Transfer"
                else:
                    category = guess_category(desc, mappings)

                base_rev_key = f"REV_{formatted_date}_{abs(amount)}_{desc[:10]}"
                occurrence = rev_id_counts.get(base_rev_key, 0) + 1
                rev_id_counts[base_rev_key] = occurrence

                new_data.append({
                    "Select": False,
                    "Date": formatted_date,
                    "Transaction ID": f"{base_rev_key}_{occurrence}",
                    "Description": desc,
                    "Amount": abs(amount),
                    "Currency": currency,
                    "Type": tx_type,
                    "Payment Method": payment_method,
                    "Category": category,
                    "Remember Mapping": False
                })

        if new_data:
            new_df = pd.DataFrame(new_data)
            st.session_state.transactions = pd.concat([st.session_state.transactions, new_df], ignore_index=True)
            st.session_state.transactions.drop_duplicates(subset=["Transaction ID"], keep="first", inplace=True)
            st.session_state.transactions.reset_index(drop=True, inplace=True)
            save_db(st.session_state.transactions)
            st.success(f"Extracted {len(new_data)} transactions, deduplicated, and auto-saved locally.")
        else:
            st.error(f"No valid transactions extracted. ({debug_info})")

    st.subheader("Manual Entry")
    with st.form("manual_entry_form"):
        col1, col2, col3 = st.columns(3)
        m_date = col1.text_input("Date (DD-MM-YYYY)")
        m_desc = col2.text_input("Description")
        m_amount = col3.number_input("Amount", min_value=0.0, step=1.0)

        col4, col5, col6, col7 = st.columns(4)
        m_curr = col4.selectbox("Currency", CURRENCIES)
        m_type = col5.selectbox("Type", ["Debit", "Credit"])
        m_method = col6.selectbox("Payment Method", PAYMENT_METHODS, index=0)
        m_cat = col7.selectbox("Category", CATEGORIES)

        submitted = st.form_submit_button("Add Transaction")
        if submitted and m_date and m_desc:
            effective_method = (
                "Bank Transfer"
                if ("the university of manchester" in m_desc.strip().lower() and m_type == "Credit")
                else m_method
            )
            manual_row = pd.DataFrame([{
                "Select": False,
                "Date": m_date,
                "Transaction ID": "MANUAL_" + str(pd.Timestamp.now().timestamp()),
                "Description": m_desc,
                "Amount": float(m_amount),
                "Currency": m_curr,
                "Type": m_type,
                "Payment Method": effective_method,
                "Category": m_cat,
                "Remember Mapping": False
            }])
            st.session_state.transactions = pd.concat([st.session_state.transactions, manual_row], ignore_index=True)
            st.session_state.transactions.reset_index(drop=True, inplace=True)
            save_db(st.session_state.transactions)
            st.success("Manual transaction added.")

    if not st.session_state.transactions.empty:
        st.subheader("Review and Manage Transactions")

        search_query = st.text_input("Search / Filter by Keyword (Description, Reference, etc.)")

        display_df = st.session_state.transactions.copy()
        if search_query:
            mask = display_df.astype(str).apply(lambda x: x.str.contains(search_query, case=False)).any(axis=1)
            display_df = display_df[mask]

        st.session_state.filtered_indices = display_df.index.tolist()

        st.data_editor(
            display_df,
            key="tx_editor",
            on_change=handle_editor_change,
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", default=False),
                "Category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
                "Type": st.column_config.SelectboxColumn("Type", options=["Debit", "Credit"], required=True),
                "Currency": st.column_config.SelectboxColumn("Currency", options=CURRENCIES, required=True),
                "Payment Method": st.column_config.SelectboxColumn("Payment Method", options=PAYMENT_METHODS, required=True),
                "Remember Mapping": st.column_config.CheckboxColumn("Remember Mapping", default=False)
            },
            hide_index=True,
            use_container_width=True
        )

        st.divider()
        st.subheader("Selected Row Actions")

        selected_indices = st.session_state.transactions[st.session_state.transactions["Select"] == True].index.tolist()
        has_selection = len(selected_indices) > 0
        selected_idx = selected_indices[0] if has_selection else None

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Split Selected Transaction", disabled=not has_selection):
                if has_selection:
                    st.session_state.split_target_idx = selected_idx
                    st.session_state.confirm_delete = False
                    init_amt = float(st.session_state.transactions.loc[selected_idx, "Amount"])
                    half_amt = round(init_amt / 2, 2)
                    st.session_state.split_p1_amt = half_amt
                    st.session_state.split_p2_amt = round(init_amt - half_amt, 2)
        with col_btn2:
            if st.button("Delete Selected Transaction", disabled=not has_selection):
                if has_selection:
                    st.session_state.confirm_delete = True
                    st.session_state.split_target_idx = None

        if st.session_state.split_target_idx is not None:
            s_idx = st.session_state.split_target_idx
            if s_idx in st.session_state.transactions.index:
                t_row = st.session_state.transactions.loc[s_idx]
                orig_amt = float(t_row["Amount"])

                if "split_p1_amt" not in st.session_state or "split_p2_amt" not in st.session_state:
                    half_amt = round(orig_amt / 2, 2)
                    st.session_state.split_p1_amt = half_amt
                    st.session_state.split_p2_amt = round(orig_amt - half_amt, 2)

                def update_p2():
                    st.session_state.split_p2_amt = round(max(0.0, orig_amt - float(st.session_state.split_p1_amt)), 2)

                def update_p1():
                    st.session_state.split_p1_amt = round(max(0.0, orig_amt - float(st.session_state.split_p2_amt)), 2)

                st.markdown(f"**Splitting:** {t_row['Date']} - {t_row['Description']} ({t_row['Currency']} {orig_amt:.2f})")

                with st.container(border=True):
                    p1_amt = st.number_input(
                        "Part 1 Amount",
                        min_value=0.0,
                        max_value=orig_amt,
                        step=0.01,
                        key="split_p1_amt",
                        on_change=update_p2
                    )
                    p1_cat = st.selectbox("Part 1 Category", CATEGORIES, index=0, key="split_p1_cat")

                    p2_amt = st.number_input(
                        "Part 2 Amount",
                        min_value=0.0,
                        max_value=orig_amt,
                        step=0.01,
                        key="split_p2_amt",
                        on_change=update_p1
                    )
                    p2_cat = st.selectbox("Part 2 Category", CATEGORIES, index=1 if len(CATEGORIES) > 1 else 0, key="split_p2_cat")

                    execute_split = st.button("Confirm Split")
                    if execute_split:
                        if abs((p1_amt + p2_amt) - orig_amt) > 0.01:
                            st.error(f"Split total ({p1_amt + p2_amt:.2f}) does not match original amount ({orig_amt:.2f}).")
                        else:
                            base_id = str(t_row["Transaction ID"])
                            row1 = t_row.copy()
                            row1["Amount"] = p1_amt
                            row1["Category"] = p1_cat
                            row1["Transaction ID"] = f"{base_id}_split1"
                            row1["Select"] = False

                            row2 = t_row.copy()
                            row2["Amount"] = p2_amt
                            row2["Category"] = p2_cat
                            row2["Transaction ID"] = f"{base_id}_split2"
                            row2["Select"] = False

                            st.session_state.transactions = st.session_state.transactions.drop(s_idx).reset_index(drop=True)
                            new_split_df = pd.DataFrame([row1, row2])
                            st.session_state.transactions = pd.concat([st.session_state.transactions, new_split_df], ignore_index=True)
                            save_db(st.session_state.transactions)
                            st.session_state.split_target_idx = None
                            st.session_state.pop("split_p1_amt", None)
                            st.session_state.pop("split_p2_amt", None)
                            st.success("Transaction split successfully!")
                            st.rerun()
            else:
                st.session_state.split_target_idx = None

        if st.session_state.confirm_delete and has_selection:
            d_row = st.session_state.transactions.loc[selected_idx]
            st.warning(f"Are you sure you want to delete: **{d_row['Date']} | {d_row['Description']} | {d_row['Currency']} {d_row['Amount']}**?")
            d_col1, d_col2 = st.columns(2)
            if d_col1.button("Yes, Delete"):
                st.session_state.transactions = st.session_state.transactions.drop(selected_idx).reset_index(drop=True)
                save_db(st.session_state.transactions)
                st.session_state.confirm_delete = False
                st.success("Transaction deleted successfully!")
                st.rerun()
            if d_col2.button("No, Cancel"):
                st.session_state.confirm_delete = False
                st.rerun()

with tab2:
    col_top1, col_top2 = st.columns([3, 1])
    with col_top2:
        if st.button("Refresh Dashboard Data", use_container_width=True):
            if os.path.exists(DB_FILE):
                st.session_state.transactions = load_db()
            st.rerun()

    if st.session_state.transactions.empty:
        st.info("No data available.")
    else:
        curr_counts = st.session_state.transactions["Currency"].dropna().astype(str).str.strip().value_counts()
        default_curr_idx = 0
        if not curr_counts.empty and curr_counts.index[0] in CURRENCIES:
            default_curr_idx = CURRENCIES.index(curr_counts.index[0])

        with col_top1:
            selected_dashboard_curr = st.selectbox("Select Currency Filter for Dashboard", CURRENCIES, index=default_curr_idx)

        dash_df = st.session_state.transactions[
            st.session_state.transactions["Currency"].astype(str).str.strip() == selected_dashboard_curr
        ].copy()

        if dash_df.empty:
            st.warning(f"No transactions found for {selected_dashboard_curr}.")
        else:
            dash_df["Amount"] = pd.to_numeric(dash_df["Amount"], errors="coerce").fillna(0.0)
            dash_df["Category"] = dash_df["Category"].replace({"Distance Travel": "Trip Expenses"}).fillna("Uncategorised").replace("", "Uncategorised")
            dash_df["Type"] = dash_df["Type"].astype(str).str.strip()
            dash_df["Payment Method"] = dash_df["Payment Method"].astype(str).str.strip()
            dash_df["Date_DT"] = pd.to_datetime(dash_df["Date"], dayfirst=True, errors="coerce")

            # 1. Real Expenditure (Debit adds, Credit refunds/splits subtract)
            expenses_df = dash_df[dash_df["Category"].isin(EXPENDITURE_CATEGORIES)].copy()
            expenses_df["Net_Amount"] = expenses_df.apply(
                lambda r: r["Amount"] if r["Type"] == "Debit" else -r["Amount"], axis=1
            )

            # 2. Income (Strictly specified income categories)
            income_df = dash_df[dash_df["Category"].isin(INCOME_CATEGORIES)].copy()
            income_df["Net_Income"] = income_df.apply(
                lambda r: r["Amount"] if r["Type"] == "Credit" else -r["Amount"], axis=1
            )

            # 3. Wealth Building (Investments & Pension)
            wealth_df = dash_df[dash_df["Category"].isin(WEALTH_CATEGORIES)].copy()
            wealth_df["Net_Wealth"] = wealth_df.apply(
                lambda r: r["Amount"] if r["Type"] == "Debit" else -r["Amount"], axis=1
            )

            total_expenses = expenses_df["Net_Amount"].sum()
            total_rent = expenses_df[expenses_df["Category"] == "Rent"]["Net_Amount"].sum()
            total_wealth = wealth_df["Net_Wealth"].sum()
            total_income = income_df["Net_Income"].sum()

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric(f"Real Expenditure ({selected_dashboard_curr})", f"{total_expenses:,.2f}")
            col_m2.metric(f"Rent ({selected_dashboard_curr})", f"{total_rent:,.2f}")
            col_m3.metric(f"Wealth Building ({selected_dashboard_curr})", f"{total_wealth:,.2f}")
            col_m4.metric(f"Total Income ({selected_dashboard_curr})", f"{total_income:,.2f}")

            st.divider()

            # Expenditure Pie Chart (Full Width for Maximum Space)
            st.subheader("Expenditure Breakdown (%)")
            if not expenses_df.empty:
                cat_group = expenses_df.groupby("Category", as_index=False)["Net_Amount"].sum()
                cat_group = cat_group[cat_group["Net_Amount"] > 0]
                if not cat_group.empty:
                    fig_exp = px.pie(cat_group, values="Net_Amount", names="Category", hole=0.4)
                    fig_exp.update_layout(height=400, margin=dict(t=20, b=20, l=20, r=20))
                    st.plotly_chart(fig_exp, use_container_width=True)
                else:
                    st.write("No net positive expenses recorded.")
            else:
                st.write("No expenses recorded.")

            st.divider()

            # Daily Real Expenditure Trend
            st.subheader("Daily Expenditure Trend")
            valid_trend_df = expenses_df.dropna(subset=["Date_DT"])
            if not valid_trend_df.empty:
                daily_spend = valid_trend_df.groupby("Date_DT", as_index=False)["Net_Amount"].sum().sort_values("Date_DT")
                st.line_chart(daily_spend.set_index("Date_DT")["Net_Amount"])
            else:
                st.write("No expenditure trend data available.")

            st.divider()

            # Credit Card Usage Tracker (Daily vs. Cumulative Toggle)
            cc_header_col1, cc_header_col2 = st.columns([3, 1])
            with cc_header_col1:
                st.subheader(f"Credit Card Usage Tracker ({selected_dashboard_curr})")
            with cc_header_col2:
                show_cumulative_cc = st.toggle("Cumulative Tracker", value=False)

            credit_card_methods = [m for m in PAYMENT_METHODS if "Credit Card" in m]
            cc_df = dash_df[
                (dash_df["Payment Method"].isin(credit_card_methods)) &
                (dash_df["Category"] != "Credit Card Repayment")
            ].copy()

            if cc_df.empty:
                st.info(f"No credit card usage recorded in {selected_dashboard_curr}.")
            else:
                cc_df["Usage_Amount"] = cc_df.apply(
                    lambda r: r["Amount"] if r["Type"] == "Debit" else -r["Amount"], axis=1
                )

                # Summary metrics per credit card
                card_totals = cc_df.groupby("Payment Method")["Usage_Amount"].sum()
                cc_metric_cols = st.columns(len(credit_card_methods) + 1)
                cc_metric_cols[0].metric("All Credit Cards Total", f"{cc_df['Usage_Amount'].sum():,.2f}")
                for idx_c, card_name in enumerate(credit_card_methods, start=1):
                    card_val = card_totals.get(card_name, 0.0)
                    short_label = card_name.replace("Credit Card - ", "")
                    cc_metric_cols[idx_c].metric(f"{short_label} Usage", f"{card_val:,.2f}")

                cc_valid = cc_df.dropna(subset=["Date_DT"]).copy()
                if not cc_valid.empty:
                    daily_cc = cc_valid.pivot_table(
                        index="Date_DT",
                        columns="Payment Method",
                        values="Usage_Amount",
                        aggfunc="sum",
                        fill_value=0.0
                    ).sort_index()

                    active_cards = list(daily_cc.columns)
                    if show_cumulative_cc:
                        cum_cc = daily_cc.cumsum()
                        cum_cc["Total All Cards"] = cum_cc[active_cards].sum(axis=1)
                        plot_cc_df = cum_cc.reset_index()
                        fig_cc = px.line(
                            plot_cc_df,
                            x="Date_DT",
                            y=active_cards + ["Total All Cards"],
                            markers=True,
                            labels={"Date_DT": "Date", "value": f"Cumulative Usage ({selected_dashboard_curr})", "variable": "Card"}
                        )
                        st.plotly_chart(fig_cc, use_container_width=True)
                    else:
                        plot_cc_df = daily_cc.reset_index()
                        fig_cc = px.bar(
                            plot_cc_df,
                            x="Date_DT",
                            y=active_cards,
                            barmode="stack",
                            labels={"Date_DT": "Date", "value": f"Daily Usage ({selected_dashboard_curr})", "variable": "Card"}
                        )
                        st.plotly_chart(fig_cc, use_container_width=True)
                else:
                    st.write("No valid dates available for credit card timeline.")

            st.divider()

            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.subheader("Granular Wealth Building Log")
                if not wealth_df.empty:
                    st.dataframe(wealth_df[["Date", "Description", "Category", "Amount"]], hide_index=True, use_container_width=True)
                else:
                    st.write("No investments or pension entries found.")

            with col_t2:
                st.subheader("Income Tracker by Category")
                if not income_df.empty:
                    income_summary = income_df.groupby("Category", as_index=False)["Net_Income"].sum().rename(columns={"Net_Income": "Amount"})
                    st.dataframe(income_summary, hide_index=True, use_container_width=True)
                else:
                    st.write("No income entries found.")
