#!/usr/bin/env python3
import pandas as pd
import glob
from pathlib import Path

def count_zipcode_drug_combinations():
    """Count unique zipcode + drug combinations across all analysis report files"""
    
    # Get all CSV files from analysis_report directory
    csv_files = glob.glob("analysis_report/*.csv")
    
    if not csv_files:
        print("No CSV files found in analysis_report directory")
        return
    
    all_combinations = []
    
    print("Processing files:")
    for file in csv_files:
        print(f"  - {file}")
        df = pd.read_csv(file)
        
        # Get unique zipcode + drug combinations from this file
        unique_combinations = df[['zip_code', 'drug_name']].drop_duplicates()
        all_combinations.append(unique_combinations)
        
        print(f"    Found {len(unique_combinations)} unique zipcode + drug combinations")
    
    # Combine all dataframes and get unique combinations across all files
    combined_df = pd.concat(all_combinations, ignore_index=True)
    unique_across_all = combined_df.drop_duplicates()
    
    print(f"\n📊 Summary:")
    print(f"  - Total unique zipcode + drug combinations: {len(unique_across_all)}")
    print(f"  - Unique zip codes: {unique_across_all['zip_code'].nunique()}")
    print(f"  - Unique drugs: {unique_across_all['drug_name'].nunique()}")
    
    # Show some examples
    print(f"\n🔍 Sample combinations:")
    print(unique_across_all.head(10).to_string(index=False))
    
    return unique_across_all

if __name__ == "__main__":
    count_zipcode_drug_combinations() 