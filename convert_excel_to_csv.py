#!/usr/bin/env python3
"""
Script to convert gfi_ga_202507_increases.xlsx to CSV format
"""

import pandas as pd
import sys

def convert_excel_to_csv():
    """
    Convert the Excel file to CSV format
    """
    try:
        # Input and output file names
        excel_file = 'gfi_ga_202507_increases.xlsx'
        csv_file = 'gfi_ga_202507_increases.csv'
        
        print(f"Reading Excel file: {excel_file}")
        
        # Read the Excel file
        df = pd.read_excel(excel_file)
        
        print(f"Excel file loaded successfully:")
        print(f"  - Rows: {len(df)}")
        print(f"  - Columns: {list(df.columns)}")
        print(f"  - Shape: {df.shape}")
        
        # Display first few rows
        print(f"\nFirst 5 rows:")
        print(df.head())
        
        # Save to CSV
        print(f"\nSaving to CSV file: {csv_file}")
        df.to_csv(csv_file, index=False)
        
        print(f"✅ Successfully converted {excel_file} to {csv_file}")
        print(f"CSV file contains {len(df)} rows and {len(df.columns)} columns")
        
        # Verify the CSV file was created correctly
        print(f"\nVerifying CSV file...")
        csv_df = pd.read_csv(csv_file)
        print(f"CSV verification - Rows: {len(csv_df)}, Columns: {len(csv_df.columns)}")
        
        if len(df) == len(csv_df) and len(df.columns) == len(csv_df.columns):
            print("✅ CSV file verification passed - data matches original Excel file")
        else:
            print("❌ CSV file verification failed - data mismatch")
            
    except FileNotFoundError:
        print(f"❌ Error: Excel file '{excel_file}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    convert_excel_to_csv() 