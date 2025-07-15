#!/usr/bin/env python3
"""
Script to find sidecarCode values from gfi_ga_202507_increases.xlsx 
that exist in the PROCEDURE_CODE column of top_100_drugs.csv
"""

import pandas as pd
import sys

def find_matching_sidecar_codes():
    """
    Find sidecarCode values that exist in both files
    """
    try:
        # Read the Excel file
        print("Reading Excel file: gfi_ga_202507_increases.xlsx")
        excel_df = pd.read_excel('gfi_ga_202507_increases.xlsx')
        print(f"Excel file loaded: {len(excel_df)} rows, columns: {list(excel_df.columns)}")
        
        # Read the CSV file
        print("\nReading CSV file: top_100_drugs.csv")
        csv_df = pd.read_csv('top_100_drugs.csv')
        print(f"CSV file loaded: {len(csv_df)} rows, columns: {list(csv_df.columns)}")
        
        # Extract the sidecarCode values from Excel file
        sidecar_codes = set(excel_df['sidecarCode'].astype(str))
        print(f"\nTotal unique sidecarCode values: {len(sidecar_codes)}")
        
        # Extract the PROCEDURE_CODE values from CSV file
        procedure_codes = set(csv_df['PROCEDURE_CODE'].astype(str))
        print(f"Total unique PROCEDURE_CODE values: {len(procedure_codes)}")
        
        # Find matching codes
        matching_codes = sidecar_codes.intersection(procedure_codes)
        print(f"\nMatching codes found: {len(matching_codes)}")
        
        if matching_codes:
            print("\nMatching sidecarCode values that exist in PROCEDURE_CODE:")
            print("=" * 60)
            
            # Get detailed information for matching codes
            matching_sidecar_data = excel_df[excel_df['sidecarCode'].astype(str).isin(matching_codes)]
            matching_procedure_data = csv_df[csv_df['PROCEDURE_CODE'].astype(str).isin(matching_codes)]
            
            # Display results
            for code in sorted(matching_codes):
                print(f"\nCode: {code}")
                
                # Show sidecar data
                sidecar_row = matching_sidecar_data[matching_sidecar_data['sidecarCode'].astype(str) == code]
                if not sidecar_row.empty:
                    avg_price = sidecar_row['averageUnitPrice'].iloc[0]
                    print(f"  From Excel - Average Unit Price: ${avg_price:.2f}")
                
                # Show procedure data
                procedure_row = matching_procedure_data[matching_procedure_data['PROCEDURE_CODE'].astype(str) == code]
                if not procedure_row.empty:
                    drug_name = procedure_row['DRUG_NAME_WITH_FORM_STRENGTH'].iloc[0]
                    benefit_amount = procedure_row['TOTAL_BENEFIT_AMOUNT'].iloc[0]
                    print(f"  From CSV - Drug: {drug_name}")
                    print(f"  From CSV - Total Benefit Amount: {benefit_amount}")
            
            # Save results to file
            print(f"\nSaving results to 'matching_sidecar_codes.csv'")
            results_df = pd.DataFrame({
                'matching_code': sorted(matching_codes)
            })
            
            # Add detailed information
            detailed_results = []
            for code in sorted(matching_codes):
                sidecar_row = matching_sidecar_data[matching_sidecar_data['sidecarCode'].astype(str) == code]
                procedure_row = matching_procedure_data[matching_procedure_data['PROCEDURE_CODE'].astype(str) == code]
                
                detailed_results.append({
                    'code': code,
                    'excel_avg_unit_price': sidecar_row['averageUnitPrice'].iloc[0] if not sidecar_row.empty else None,
                    'csv_drug_name': procedure_row['DRUG_NAME_WITH_FORM_STRENGTH'].iloc[0] if not procedure_row.empty else None,
                    'csv_total_benefit_amount': procedure_row['TOTAL_BENEFIT_AMOUNT'].iloc[0] if not procedure_row.empty else None,
                    'csv_benefit_percentage': procedure_row['BENEFIT_PERCENTAGE'].iloc[0] if not procedure_row.empty else None,
                    'csv_claim_count': procedure_row['CLAIM_COUNT'].iloc[0] if not procedure_row.empty else None
                })
            
            detailed_df = pd.DataFrame(detailed_results)
            detailed_df.to_csv('matching_sidecar_codes_detailed.csv', index=False)
            print("Detailed results saved to 'matching_sidecar_codes_detailed.csv'")
            
        else:
            print("\nNo matching codes found between the two files.")
            
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    find_matching_sidecar_codes() 