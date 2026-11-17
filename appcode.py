import streamlit as st
import pandas as pd
import json
import os
import pdfplumber

# Match the exact categories from Rahul_India_Expenses.xlsx
CATEGORIES = ["Grocery", "Eat Out", "Bills", "Travel", "Transport", "Fun", "Shopping", "Others", "Rent", "Uncategorised"]
MAPPING_FILE = "category_mapping.json"

def load_mappings():
    if os.path.exists(MAPPING_FILE):
        with open(MAPPING_FILE, "r") as f:
            return json.load(f)
    # Default starter guesses
    return {"amazon": "Shopping", "swiggy": "Eat Out", "zomato": "Eat Out", "uber": "Transport", "jio": "Bills"}

def save_mappings(mappings):
    with open(MAPPING_FILE, "w") as f:
        json.dump(mappings, f, indent=4)

def guess_category(description, mappings):
    desc_lower = str(description).lower()
    for keyword, category in mappings.items():
        if keyword in desc_lower:
            return category
    return "Uncategorised"

st.title("Local Secure Financial Manager")
st.write("Data processed locally. No internet connection required.")

uploaded_file = st.file_uploader("Upload Bank Statement (PDF)", type="pdf")

if uploaded_file:
    mappings = load_mappings()
    
    # PDF Parsing Logic (Generic Tabular Extraction)
    # Note: Column indices [0, 1, 2] may need adjustment based on your specific bank's PDF layout
    raw_data = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table:
                for row in table:
                    # Basic filter to skip empty rows or headers
                    if row[0] and len(row) >= 3: 
                        raw_data.append({
                            "Date": row[0],
                            "Description": row[1],
                            "Amount": row[2]
                        })
    
    if not raw_data:
        st.error("Could not find a standard table in this PDF. Bank formats vary.")
    else:
        df = pd.DataFrame(raw_data)
        
        # Apply smart guesses
        df["Category"] = df["Description"].apply(lambda x: guess_category(x, mappings))
        
        # Add column for Payment Method (UPI vs CARD) based on your Excel structure
        df["Payment Method"] = df["Description"].apply(lambda x: "UPI" if "upi" in str(x).lower() else "CARD")
        
        st.subheader("Review and Confirm Categories")
        
        # Make the dataframe editable
        edited_df = st.data_editor(
            df,
            column_config={
                "Category": st.column_config.SelectboxColumn(
                    "Category",
                    help="Select the correct category",
                    options=CATEGORIES,
                    required=True
                )
            },
            hide_index=True,
            use_container_width=True
        )
        
        if st.button("Save Data & Export to Excel"):
            # Update the learning database with new user-confirmed mappings
            for index, row in edited_df.iterrows():
                if row["Category"] != "Uncategorised":
                    # Use the first word of the description as a simple keyword for future learning
                    keyword = str(row["Description"]).split()[0].lower()
                    mappings[keyword] = row["Category"]
            
            save_mappings(mappings)
            st.success("Learning database updated with your confirmed categories!")
            
            # Export to Excel
            export_file = "Processed_Statement.xlsx"
            edited_df.to_excel(export_file, index=False)
            
            with open(export_file, "rb") as file:
                st.download_button(
                    label="Download Excel File",
                    data=file,
                    file_name=export_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )