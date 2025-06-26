#!/usr/bin/env python3
"""
Preprocess Drugs CSV Script
Adds care_uuid column to the drugs CSV by looking up UUIDs for each procedure code
"""

import requests
import pandas as pd
import json
import time
import logging
import os
import subprocess
from typing import Dict, Optional

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/preprocess_drugs.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DrugUUIDProcessor:
    def __init__(self):
        self.token = self.get_token()
        self.member_uuid = self.get_member_uuid()
        self.headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json; charset=utf-8',
            'origin': 'https://dev-app.sidecarhealth.com',
            'priority': 'u=1, i',
            'referer': 'https://dev-app.sidecarhealth.com/',
            'sec-ch-ua': '"Brave";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'sec-gpc': '1',
            'token': self.token,
            'tz': 'PDT',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36'
        }
        
        # UUID lookup cache
        self.uuid_cache_file = 'uuid_cache.json'
        self.uuid_cache = self.load_uuid_cache()
    
    def get_token(self) -> str:
        """Get token from environment variable or by running grab_token.sh"""
        # First, try to get token from environment variable
        token = os.environ.get('TOKEN')
        if token:
            logger.info("Using TOKEN from environment variable")
            return token
        
        # If not found, try to run grab_token.sh to get the token
        logger.info("TOKEN not found in environment, running grab_token.sh...")
        try:
            # Run the grab_token.sh script
            result = subprocess.run(['./grab_token.sh'], 
                                  capture_output=True, 
                                  text=True, 
                                  check=True)
            
            # Parse the output to extract the token
            output_lines = result.stdout.strip().split('\n')
            for line in output_lines:
                if line.startswith('TOKEN='):
                    token = line.split('=', 1)[1]
                    logger.info("Successfully obtained TOKEN from grab_token.sh")
                    return token
            
            raise ValueError("Could not extract TOKEN from grab_token.sh output")
            
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            raise
    
    def get_member_uuid(self) -> str:
        """Get memberUUID from environment variable or by running grab_token.sh"""
        # First, try to get memberUUID from environment variable
        member_uuid = os.environ.get('MEMBERUUID')
        if member_uuid:
            logger.info("Using MEMBERUUID from environment variable")
            return member_uuid
        
        # If not found, try to run grab_token.sh to get the memberUUID
        logger.info("MEMBERUUID not found in environment, running grab_token.sh...")
        try:
            # Run the grab_token.sh script
            result = subprocess.run(['./grab_token.sh'], 
                                  capture_output=True, 
                                  text=True, 
                                  check=True)
            
            # Parse the output to extract the memberUUID
            output_lines = result.stdout.strip().split('\n')
            for line in output_lines:
                if line.startswith('MEMBERUUID='):
                    member_uuid = line.split('=', 1)[1]
                    logger.info("Successfully obtained MEMBERUUID from grab_token.sh")
                    return member_uuid
            
            raise ValueError("Could not extract MEMBERUUID from grab_token.sh output")
            
        except Exception as e:
            logger.error(f"Error getting memberUUID: {e}")
            raise
    
    def load_uuid_cache(self) -> Dict:
        """Load UUID cache from file"""
        if os.path.exists(self.uuid_cache_file):
            try:
                with open(self.uuid_cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load UUID cache: {e}")
        return {}
    
    def save_uuid_cache(self):
        """Save UUID cache to file"""
        try:
            with open(self.uuid_cache_file, 'w') as f:
                json.dump(self.uuid_cache, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save UUID cache: {e}")
    
    def get_care_uuid_for_procedure_code(self, procedure_code: str) -> Optional[str]:
        """Get care UUID for a given procedure code using the search API"""
        # Check cache first
        if procedure_code in self.uuid_cache:
            logger.info(f"Using cached UUID for {procedure_code}: {self.uuid_cache[procedure_code]}")
            return self.uuid_cache[procedure_code]
        
        try:
            search_url = "https://dev-api.sidecarhealth.com/care/v1/cares/search"
            params = {
                'memberUuid': self.member_uuid,
                'query': procedure_code,
                'page': 0,
                'size': 25
            }
            
            logger.info(f"Looking up UUID for procedure code: {procedure_code}")
            response = requests.get(
                search_url,
                params=params,
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('content') and len(data['content']) > 0:
                    uuid = data['content'][0].get('uuid')
                    if uuid:
                        # Cache the result
                        self.uuid_cache[procedure_code] = uuid
                        self.save_uuid_cache()
                        logger.info(f"✅ Found UUID for {procedure_code}: {uuid}")
                        return uuid
                
                logger.warning(f"❌ No UUID found for procedure code: {procedure_code}")
                return None
            else:
                logger.error(f"❌ UUID lookup failed for {procedure_code}: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error looking up UUID for {procedure_code}: {e}")
            return None
    
    def process_csv(self, input_file: str, output_file: str = None):
        """Process the CSV file and add care_uuid column"""
        if output_file is None:
            output_file = input_file.replace('.csv', '_with_uuids.csv')
        
        logger.info(f"Processing {input_file}...")
        
        try:
            # Read the CSV
            df = pd.read_csv(input_file)
            logger.info(f"Loaded {len(df)} drugs from {input_file}")
            
            # Add care_uuid column
            care_uuids = []
            successful_lookups = 0
            failed_lookups = 0
            
            for i, row in df.iterrows():
                procedure_code = str(row['PROCEDURE_CODE'])
                drug_name = row['DRUG_NAME_WITH_FORM_STRENGTH']
                
                logger.info(f"Processing {i+1}/{len(df)}: {procedure_code} - {drug_name}")
                
                uuid = self.get_care_uuid_for_procedure_code(procedure_code)
                care_uuids.append(uuid)
                
                if uuid:
                    successful_lookups += 1
                else:
                    failed_lookups += 1
                
                # Progress update every 10 items
                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i+1}/{len(df)} - Success: {successful_lookups}, Failed: {failed_lookups}")
                
                # Rate limiting - be respectful to the API
                time.sleep(0.5)
            
            # Add the new column
            df['CARE_UUID'] = care_uuids
            
            # Save the updated CSV
            df.to_csv(output_file, index=False)
            
            logger.info(f"✅ Processing complete!")
            logger.info(f"📊 Results:")
            logger.info(f"   - Total drugs processed: {len(df)}")
            logger.info(f"   - Successful UUID lookups: {successful_lookups}")
            logger.info(f"   - Failed UUID lookups: {failed_lookups}")
            logger.info(f"   - Success rate: {successful_lookups/len(df)*100:.1f}%")
            logger.info(f"📁 Output saved to: {output_file}")
            
            # Save final cache
            self.save_uuid_cache()
            logger.info(f"💾 UUID cache saved with {len(self.uuid_cache)} entries")
            
        except Exception as e:
            logger.error(f"Error processing CSV: {e}")
            raise

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Preprocess drugs CSV to add care_uuid column')
    parser.add_argument('--input', '-i', default='top_100_drugs.csv',
                       help='Input CSV file (default: top_100_drugs.csv)')
    parser.add_argument('--output', '-o', 
                       help='Output CSV file (default: input_with_uuids.csv)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        logger.error(f"Input file not found: {args.input}")
        return
    
    processor = DrugUUIDProcessor()
    processor.process_csv(args.input, args.output)

if __name__ == "__main__":
    main() 