#!/usr/bin/env python3
import re
import pandas as pd
from pathlib import Path

def extract_failed_data_errors(log_file_path):
    """
    Extract lines with failed data extraction errors from the log file.
    Pattern: ❌ Failed to get data for [drug name] in [zipcode] (Total failures: X, Consecutive: Y)
    """
    
    # Check if log file exists
    if not Path(log_file_path).exists():
        print(f"Error: Log file '{log_file_path}' not found.")
        return
    
    # Pattern to match the error lines
    pattern = r'❌ Failed to get data for (.+?) in (\d+) \(Total failures: \d+, Consecutive: \d+\)'
    
    matched_lines = []
    extracted_data = []
    
    print(f"Reading log file: {log_file_path}")
    
    try:
        with open(log_file_path, 'r', encoding='utf-8') as file:
            for line_num, line in enumerate(file, 1):
                # Check if line matches our pattern
                if '❌ Failed to get data for' in line and 'Total failures:' in line:
                    matched_lines.append(line.strip())
                    
                    # Extract drug name and zipcode using regex
                    match = re.search(pattern, line)
                    if match:
                        drug_name = match.group(1).strip()
                        zipcode = match.group(2).strip()
                        extracted_data.append({
                            'zipcode': zipcode,
                            'drug_name': drug_name
                        })
                    else:
                        print(f"Warning: Could not parse line {line_num}: {line.strip()}")
        
        print(f"Found {len(matched_lines)} matching error lines")
        
        # Save to text file
        text_output_file = "failed_data_extraction_errors.txt"
        with open(text_output_file, 'w', encoding='utf-8') as f:
            for line in matched_lines:
                f.write(line + '\n')
        print(f"Raw error lines saved to: {text_output_file}")
        
        # Create CSV with structured data
        if extracted_data:
            df = pd.DataFrame(extracted_data)
            
            # Remove duplicates if any
            df_unique = df.drop_duplicates()
            
            csv_output_file = "failed_data_extraction.csv"
            df_unique.to_csv(csv_output_file, index=False)
            print(f"Structured data saved to: {csv_output_file}")
            
            print(f"\nSummary:")
            print(f"  - Total error lines: {len(matched_lines)}")
            print(f"  - Unique combinations: {len(df_unique)}")
            print(f"  - Unique zip codes: {df_unique['zipcode'].nunique()}")
            print(f"  - Unique drugs: {df_unique['drug_name'].nunique()}")
            
            # Show sample of data
            print(f"\nFirst 10 entries:")
            print(df_unique.head(10).to_string(index=False))
            
        else:
            print("No structured data could be extracted from the matching lines.")
            
    except Exception as e:
        print(f"Error reading log file: {e}")

if __name__ == "__main__":
    log_file_path = "/Users/cindyhardi/Documents/Sidecar/sidecar-care-coverage/logs/sidecar_api_collection.log"
    extract_failed_data_errors(log_file_path) 