#!/usr/bin/env python3
import pandas as pd
import sys
import argparse
from pathlib import Path

def find_no_favorable_pharmacies(input_file, output_file):
    """
    Find zip codes and procedure codes that have no favorable pharmacies.
    Favorable pharmacy is defined as: estimated_member_responsibility <= 0
    """
    
    # Check if input file exists
    if not Path(input_file).exists():
        print(f"Error: Input file '{input_file}' not found.")
        sys.exit(1)
    
    try:
        # Read the CSV file
        print(f"Reading data from {input_file}...")
        df = pd.read_csv(input_file)
        
        # Check if required columns exist
        required_columns = ['zip_code', 'procedure_code', 'estimated_member_responsibility', 'drug_name']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            print(f"Error: Missing required columns: {missing_columns}")
            print(f"Available columns: {list(df.columns)}")
            sys.exit(1)
        
        print(f"Loaded {len(df)} rows of data")
        
        # Convert columns to numeric, handling any non-numeric values
        df['estimated_member_responsibility'] = pd.to_numeric(df['estimated_member_responsibility'], errors='coerce')
        
        # Define favorable pharmacy criteria
        df['is_favorable'] = (df['estimated_member_responsibility'] <= 0)
        
        # Group by zipcode and procedure_code
        print("Analyzing zip codes and procedure codes...")
        grouped = df.groupby(['zip_code', 'procedure_code'])
        
        # Find combinations with no favorable pharmacies
        no_favorable_combinations = []
        
        for (zip_code, procedure_code), group in grouped:
            # Check if any pharmacy in this group is favorable
            has_favorable_pharmacy = group['is_favorable'].any()
            
            if not has_favorable_pharmacy:
                # Get the drug name (should be same for all rows in this group)
                drug_name = group['drug_name'].iloc[0]
                no_favorable_combinations.append({
                    'zip_code': zip_code,
                    'procedure_code': procedure_code,
                    'drug_name': drug_name
                })
        
        # Create output DataFrame
        result_df = pd.DataFrame(no_favorable_combinations)
        
        if len(result_df) == 0:
            print("Great news! All zip code and procedure code combinations have at least one favorable pharmacy.")
        else:
            print(f"Found {len(result_df)} zip code and procedure code combinations with no favorable pharmacies")
            
            # Save to CSV
            result_df.to_csv(output_file, index=False)
            print(f"Results saved to {output_file}")
            
            # Display some statistics
            unique_zipcodes = result_df['zip_code'].nunique()
            unique_procedures = result_df['procedure_code'].nunique()
            print(f"Summary:")
            print(f"  - Unique zip codes affected: {unique_zipcodes}")
            print(f"  - Unique procedure codes affected: {unique_procedures}")
            
    except Exception as e:
        print(f"Error processing data: {e}")
        sys.exit(1)

def generate_output_filename(input_file):
    """Generate output filename based on input filename"""
    input_path = Path(input_file)
    input_name = input_path.stem  # Get filename without extension
    
    # Extract state from filename if possible
    if 'OH_COMPLETE' in input_name:
        state = 'OH'
    elif 'GA_COMPLETE' in input_name:
        state = 'GA'
    elif 'FL_COMPLETE_PT1' in input_name:
        state = 'FL_PT1'
    elif 'FL_COMPLETE_PT2' in input_name:
        state = 'FL_PT2'
    else:
        state = 'UNKNOWN'
    
    # Create analysis_report directory if it doesn't exist
    output_dir = Path("analysis_report")
    output_dir.mkdir(exist_ok=True)
    
    return output_dir / f"zipcode_procedure_no_benefits_{state}.csv"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Find zip codes and procedure codes with no favorable pharmacies')
    parser.add_argument('input_file', help='Path to the input CSV file to analyze')
    parser.add_argument('-o', '--output', help='Output CSV file name (optional, will be auto-generated if not provided)')
    
    args = parser.parse_args()
    
    # Generate output filename if not provided
    if args.output:
        # Create analysis_report directory if it doesn't exist
        output_dir = Path("analysis_report")
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / args.output
    else:
        output_file = generate_output_filename(args.input_file)
    
    find_no_favorable_pharmacies(args.input_file, output_file) 