import streamlit as st
import pandas as pd
import pdfplumber
import re

st.set_page_config(page_title="GSTR-1 to Excel", page_icon="📄")

st.title("📄 GSTR-1 PDF to Excel Converter")
st.write("Upload your GSTR-1 PDF to instantly extract your Total Taxable Sales, IGST, CGST, and SGST.")

# File uploader widget
uploaded_file = st.file_uploader("Drop your GSTR-1 PDF here", type="pdf")

if uploaded_file is not None:
    try:
        with st.spinner('Extracting data...'):
            # 1. Open and read the PDF
            with pdfplumber.open(uploaded_file) as pdf:
                full_text = ""
                for page in pdf.pages:
                    full_text += page.extract_text() + "\n"
            
            # 2. Extract the numbers
            taxable_value, igst, cgst, sgst = 0.0, 0.0, 0.0, 0.0
            
            # We split the text line by line and hunt for the "Total Liability" line
            lines = full_text.split('\n')
            for line in lines:
                if "Total Liability" in line:
                    # Find all numbers with decimals in that specific line
                    amounts = re.findall(r'[\d,]+\.\d{2}', line)
                    if len(amounts) >= 4:
                        # Clean the commas and convert to math numbers
                        taxable_value = float(amounts[0].replace(',', ''))
                        igst = float(amounts[1].replace(',', ''))
                        cgst = float(amounts[2].replace(',', ''))
                        sgst = float(amounts[3].replace(',', ''))
                        break

            st.success("✅ PDF Processed Successfully!")
            
            # 3. Format into a clean table
            df = pd.DataFrame({
                "Source": ["Portal (GSTR-1)"],
                "Total Sales": [taxable_value],
                "Total IGST": [igst],
                "Total CGST": [cgst],
                "Total SGST": [sgst]
            })
            
            # Show the table on the website
            st.dataframe(df)
            
            # 4. Create the Download Button
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Clean Excel (CSV) File",
                data=csv,
                file_name="GSTR1_Portal_Extracted.csv",
                mime="text/csv",
            )
            
    except Exception as e:
        st.error(f"Oops! Something went wrong: {e}")
