#!/usr/bin/env python3
"""
Sidecar Health API Data Collection Script
Collects drug pricing and benefit data for FL, GA, OH zip codes

Environment: PRODUCTION API
Rate Limits (SAFE Configuration):
- 10,000 requests per hour
- Up to 20 requests per second
- Current setting: 2.5 req/sec (0.4s delay) - SAFE under hourly limit
"""

import requests
import pandas as pd
import json
import time
import logging
import csv
import os
import subprocess
import argparse
from datetime import datetime
import uuid
from typing import Dict, List, Optional, Tuple

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/sidecar_api_collection.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SidecarAPICollector:
    def __init__(self, test_mode: bool = False, states_filter: List[str] = None, batch_info: dict = None):
        self.test_mode = test_mode
        self.states_filter = states_filter
        self.batch_info = batch_info
        self.base_url = "https://prod-api.sidecarhealth.com/care/v1/cares/detail"
        
        # Create results directory if it doesn't exist
        os.makedirs('results', exist_ok=True)
        
        self.token = self.get_token()
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
        
        # Static API parameters (without UUID - will be added per drug)
        self.static_params = {
            'memberUuid': self.get_member_uuid(),
            'category': 'prescriptions',
            'searchRadius': '8',
            'prescriptionInitialLoad': 'true'
        }
        
        # Rate limiting - SAFE configuration for API limits: 10k/hour, 20/second max
        # Safe rate: 0.4 sec delay = 2.5 req/sec = 9,000 req/hour (safe buffer under 10k/hour)
        # This prevents hitting the hourly limit while staying well under per-second limit
        self.request_delay = 0.4  # seconds between requests (2.5 req/sec = 9k req/hour - SAFE)
        self.max_retries = 3
        self.retry_delay = 2.0  # seconds between retries
        
        # Progress tracking - data files go in results/, logs go in logs/
        mode_suffix = "_test" if test_mode else ""
        states_suffix = "_" + "_".join(states_filter) if states_filter else ""
        batch_suffix = f"_batch{batch_info['batch_num']}of{batch_info['total_batches']}" if batch_info else ""
        self.output_file = f'results/sidecar_data{mode_suffix}{states_suffix}{batch_suffix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        self.progress_file = f'results/progress{mode_suffix}{states_suffix}{batch_suffix}.json'
        self.error_file = 'logs/errors.log'
        
        # Failure tracking for auto-stop functionality
        self.failed_combinations = []
        self.consecutive_failures = 0
        self.max_consecutive_failures = 10
        self.auto_stop_triggered = False
        
        # Geocoding cache - now in results folder
        self.geocoding_cache_file = 'results/geocoding_cache.json'
        self.geocoding_cache = self.load_geocoding_cache()
        
        # UUID cache
        self.uuid_cache_file = 'uuid_cache.json'
        self.uuid_cache = self.load_uuid_cache()

        
    def load_geocoding_cache(self) -> Dict:
        """Load geocoding cache from file"""
        if os.path.exists(self.geocoding_cache_file):
            try:
                with open(self.geocoding_cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load geocoding cache: {e}")
        return {}
    
    def save_geocoding_cache(self):
        """Save geocoding cache to file"""
        try:
            with open(self.geocoding_cache_file, 'w') as f:
                json.dump(self.geocoding_cache, f)
        except Exception as e:
            logger.error(f"Could not save geocoding cache: {e}")
    
    def load_uuid_cache(self) -> Dict:
        """Load UUID cache from file"""
        if os.path.exists(self.uuid_cache_file):
            try:
                with open(self.uuid_cache_file, 'r') as f:
                    cache = json.load(f)
                    logger.info(f"Loaded UUID cache with {len(cache)} entries from {self.uuid_cache_file}")
                    return cache
            except Exception as e:
                logger.warning(f"Could not load UUID cache: {e}")
        else:
            logger.warning(f"UUID cache file not found: {self.uuid_cache_file}")
        return {}

    def geocode_zipcode(self, zipcode: str, state: str) -> Optional[Tuple[float, float, str]]:
        """Get coordinates and city for a zip code using a free geocoding service"""
        cache_key = f"{zipcode}_{state}"
        
        # Check cache first
        if cache_key in self.geocoding_cache:
            cached = self.geocoding_cache[cache_key]
            return cached['lat'], cached['lng'], cached['city']
        
        try:
            # Using OpenStreetMap Nominatim API (free)
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': f"{zipcode}, {state}, USA",
                'format': 'json',
                'limit': 1,
                'addressdetails': 1
            }
            
            headers = {
                'User-Agent': 'SidecarHealthDataCollection/1.0'
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data:
                    result = data[0]
                    lat = float(result['lat'])
                    lng = float(result['lon'])
                    
                    # Extract city from address components
                    city = ""
                    if 'display_name' in result:
                        parts = result['display_name'].split(', ')
                        if len(parts) > 1:
                            city = parts[1] if parts[1] != zipcode else (parts[2] if len(parts) > 2 else "")
                    
                    # Cache the result
                    self.geocoding_cache[cache_key] = {
                        'lat': lat,
                        'lng': lng,
                        'city': city
                    }
                    
                    # Add a small delay to be respectful to the free API
                    time.sleep(0.1)
                    
                    return lat, lng, city
            
        except Exception as e:
            logger.warning(f"Geocoding failed for {zipcode}, {state}: {e}")
        
        return None
    
    def read_zipcode_file(self, filename: str, state: str, batch_info: dict = None) -> List[str]:
        """Read zip codes from a text file, optionally filtering by batch"""
        try:
            with open(filename, 'r') as f:
                zipcodes = [line.strip() for line in f if line.strip()]
            
            # Apply batch filtering if specified
            if batch_info and batch_info.get('batch_num') and batch_info.get('total_batches'):
                batch_num = batch_info['batch_num']
                total_batches = batch_info['total_batches']
                
                # Calculate batch size and start/end indices
                total_zips = len(zipcodes)
                batch_size = total_zips // total_batches
                remainder = total_zips % total_batches
                
                # Calculate start index for this batch
                start_idx = (batch_num - 1) * batch_size
                if batch_num <= remainder:
                    start_idx += (batch_num - 1)
                else:
                    start_idx += remainder
                
                # Calculate end index for this batch
                current_batch_size = batch_size + (1 if batch_num <= remainder else 0)
                end_idx = start_idx + current_batch_size
                
                # Extract the batch
                zipcodes = zipcodes[start_idx:end_idx]
                logger.info(f"🎯 {state} Batch {batch_num}/{total_batches}: {len(zipcodes)} zip codes (indices {start_idx}-{end_idx-1})")
            
            # In test mode, only take first 2 zip codes
            if self.test_mode:
                zipcodes = zipcodes[:2]
                logger.info(f"TEST MODE: Using only first {len(zipcodes)} zip codes from {filename}")
            else:
                if not batch_info:
                    logger.info(f"Loaded {len(zipcodes)} zip codes from {filename}")
            
            return zipcodes
        except Exception as e:
            logger.error(f"Error reading {filename}: {e}")
            return []

    def get_zip_codes_with_coordinates(self, states_filter: List[str] = None, batch_info: dict = None) -> List[Dict]:
        """Return list of zip codes with their coordinates for specified states"""
        all_zip_data = []
        
        # State mapping
        state_files = {
            'FL': 'zipcodes/zipcode_fl.txt',
            'GA': 'zipcodes/zipcode_ga.txt', 
            'OH': 'zipcodes/zipcode_oh.txt'
        }
        
        # Filter states if specified
        if states_filter:
            state_files = {k: v for k, v in state_files.items() if k in states_filter}
            logger.info(f"🎯 Processing only states: {', '.join(states_filter)}")
        
        if batch_info:
            logger.info(f"📦 Processing batch {batch_info['batch_num']}/{batch_info['total_batches']}")
        
        if self.test_mode:
            logger.info("🧪 TEST MODE: Processing only 2 zip codes per state")
        
        for state, filename in state_files.items():
            if not os.path.exists(filename):
                logger.warning(f"Zip code file not found: {filename}, skipping {state}")
                continue
                
            zipcodes = self.read_zipcode_file(filename, state, batch_info)
            if not batch_info:
                logger.info(f"Processing {len(zipcodes)} zip codes for {state}")
            
            for i, zipcode in enumerate(zipcodes):
                if not self.test_mode and i % 100 == 0:
                    logger.info(f"Geocoding progress for {state}: {i}/{len(zipcodes)}")
                    # Save cache periodically
                    self.save_geocoding_cache()
                
                coordinates = self.geocode_zipcode(zipcode, state)
                if coordinates:
                    lat, lng, city = coordinates
                    all_zip_data.append({
                        'zip': zipcode,
                        'lat': lat,
                        'lng': lng,
                        'state': state,
                        'city': city or f"{state}_City"
                    })
                    
                    if self.test_mode:
                        logger.info(f"✅ Test geocoded: {zipcode}, {state} -> {city} ({lat}, {lng})")
                else:
                    logger.warning(f"Could not geocode {zipcode}, {state}")
            
            # Save cache after each state
            self.save_geocoding_cache()
            logger.info(f"Completed geocoding for {state}")
        
        if self.test_mode:
            logger.info(f"🧪 TEST MODE: Total zip codes with coordinates: {len(all_zip_data)}")
        else:
            logger.info(f"Total zip codes with coordinates: {len(all_zip_data)}")
        
        return all_zip_data
        
    def get_token(self) -> str:
        """Get token from environment variable or by running grab_token.sh"""
        # First, try to get token from environment variable
        token = os.environ.get('TOKEN')
        if token:
            logger.info("Using TOKEN from environment variable")
            # Clean the token of any extra whitespace, quotes, or newlines
            return token.strip().strip('"').strip("'")
        
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
                    # Clean the token of any extra whitespace, quotes, or newlines
                    token = token.strip().strip('"').strip("'")
                    logger.info("Successfully obtained TOKEN from grab_token.sh")
                    return token
            
            # If we couldn't find TOKEN= in the output, try to get it from environment
            # after running the script (in case it was exported)
            token = os.environ.get('TOKEN')
            if token:
                logger.info("Using TOKEN from environment after running grab_token.sh")
                # Clean the token of any extra whitespace, quotes, or newlines
                return token.strip().strip('"').strip("'")
            
            raise ValueError("Could not extract TOKEN from grab_token.sh output")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to run grab_token.sh: {e}")
            logger.error(f"stderr: {e.stderr}")
            raise
        except FileNotFoundError:
            logger.error("grab_token.sh not found. Please ensure the script exists and is executable.")
            raise
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            raise
    
    def get_member_uuid(self) -> str:
        """Get memberUUID from environment variable or by running grab_token.sh"""
        # First, try to get memberUUID from environment variable
        member_uuid = os.environ.get('MEMBERUUID')
        if member_uuid:
            logger.info("Using MEMBERUUID from environment variable")
            # Clean the member_uuid of any extra whitespace, quotes, or newlines
            return member_uuid.strip().strip('"').strip("'")
        
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
                    # Clean the member_uuid of any extra whitespace, quotes, or newlines
                    member_uuid = member_uuid.strip().strip('"').strip("'")
                    logger.info("Successfully obtained MEMBERUUID from grab_token.sh")
                    return member_uuid
            
            # If we couldn't find MEMBERUUID= in the output, try to get it from environment
            # after running the script (in case it was exported)
            member_uuid = os.environ.get('MEMBERUUID')
            if member_uuid:
                logger.info("Using MEMBERUUID from environment after running grab_token.sh")
                # Clean the member_uuid of any extra whitespace, quotes, or newlines
                return member_uuid.strip().strip('"').strip("'")
            
            raise ValueError("Could not extract MEMBERUUID from grab_token.sh output")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to run grab_token.sh: {e}")
            logger.error(f"stderr: {e.stderr}")
            raise
        except FileNotFoundError:
            logger.error("grab_token.sh not found. Please ensure the script exists and is executable.")
            raise
        except Exception as e:
            logger.error(f"Error getting memberUUID: {e}")
            raise
    

    def load_drugs_from_excel(self, filepath: str) -> List[Dict]:
        """Load drug data from CSV file and lookup UUIDs from cache"""
        try:
            # Read CSV with PROCEDURE_CODE as string to preserve leading zeros
            df = pd.read_csv(filepath, dtype={'PROCEDURE_CODE': str})
            drugs = []
            
            # In test mode, only take first 10 drugs
            if self.test_mode:
                df = df.head(10)
                logger.info(f"🧪 TEST MODE: Using only first 10 drugs from CSV file")
            else:
                logger.info(f"Loaded {len(df)} drugs from CSV file")
            
            skipped_count = 0
            skipped_drugs = []
            loaded_count = 0
            
            for idx, row in df.iterrows():
                procedure_code = str(row['PROCEDURE_CODE'])
                drug_name = row['DRUG_NAME_WITH_FORM_STRENGTH']
                
                # Look up UUID from cache
                care_uuid = self.uuid_cache.get(procedure_code)
                
                if not care_uuid:
                    skipped_count += 1
                    skipped_drugs.append(f"{procedure_code} - {drug_name}")
                    logger.error(f"❌ SKIPPING drug #{idx+1}: No UUID in cache for {procedure_code} - {drug_name}")
                    continue
                
                drugs.append({
                    'procedure_code': procedure_code,
                    'uuid': care_uuid,
                    'drug_name': drug_name,
                    'dosage_form': row['DOSAGE_FORM'],
                    'total_benefit_amount': row['TOTAL_BENEFIT_AMOUNT'],
                    'claim_count': row['CLAIM_COUNT']
                })
                
                loaded_count += 1
                if self.test_mode and loaded_count <= 5:
                    logger.info(f"✅ Loaded drug #{idx+1}: {drug_name} -> UUID: {care_uuid}")
            
            # Summary logging
            if skipped_count > 0:
                logger.error(f"📊 SUMMARY: Skipped {skipped_count} drugs due to missing UUID in cache")
                logger.error("📋 Skipped drugs list:")
                for i, skipped_drug in enumerate(skipped_drugs, 1):
                    logger.error(f"   {i}. {skipped_drug}")
                logger.error("💡 To get UUIDs for these drugs, run: ./preprocess_drugs.sh")
            else:
                logger.info("✅ All drugs have UUIDs in cache")
            
            logger.info(f"Successfully loaded {len(drugs)} drugs with UUIDs from cache")
            return drugs
            
        except Exception as e:
            logger.error(f"Error loading CSV file: {e}")
            raise
    
    def load_progress(self) -> Dict:
        """Load progress from file"""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load progress file: {e}")
        return {'completed': [], 'total_processed': 0}
    
    def save_progress(self, progress: Dict):
        """Save progress to file"""
        try:
            with open(self.progress_file, 'w') as f:
                json.dump(progress, f)
        except Exception as e:
            logger.error(f"Could not save progress: {e}")
    
    def refresh_token(self) -> bool:
        """Refresh token by running grab_token.sh"""
        try:
            logger.info("🔄 Token expired or invalid. Refreshing token...")
            
            # Run the grab_token.sh script
            result = subprocess.run(['./grab_token.sh'], 
                                  capture_output=True, 
                                  text=True, 
                                  check=True)
            
            # Parse the output to extract the new token and memberUUID
            output_lines = result.stdout.strip().split('\n')
            new_token = None
            new_member_uuid = None
            
            for line in output_lines:
                if line.startswith('TOKEN='):
                    new_token = line.split('=', 1)[1].strip().strip('"').strip("'")
                elif line.startswith('MEMBERUUID='):
                    new_member_uuid = line.split('=', 1)[1].strip().strip('"').strip("'")
            
            if new_token and new_member_uuid:
                # Update instance variables
                self.token = new_token
                self.headers['token'] = new_token
                self.static_params['memberUuid'] = new_member_uuid
                
                # Also update environment variables
                os.environ['TOKEN'] = new_token
                os.environ['MEMBERUUID'] = new_member_uuid
                
                logger.info("✅ Token refreshed successfully!")
                return True
            else:
                logger.error("❌ Failed to extract new token from grab_token.sh output")
                return False
                
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to run grab_token.sh: {e}")
            logger.error(f"stderr: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"❌ Error refreshing token: {e}")
            return False

    def make_api_request(self, zip_code: str, lat: float, lng: float, drug_uuid: str, drug_name: str = '') -> Optional[Dict]:
        """Make API request with retry logic and automatic token refresh"""
        params = self.static_params.copy()
        params.update({
            'uuid': drug_uuid,
            'zipCode': zip_code,
            'locationLat': str(lat), 
            'locationLong': str(lng),
            'searchedQuery': drug_name.lower() if drug_name else 'prescription',
            'intentCallId': str(uuid.uuid4())
        })
        
        token_refreshed_this_request = False
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Making API request for zip {zip_code} (attempt {attempt + 1})")
                response = requests.get(
                    self.base_url, 
                    params=params, 
                    headers=self.headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:  # Unauthorized - token expired
                    logger.warning(f"🔑 Authentication failed for zip {zip_code} - token expired/invalid")
                    if not token_refreshed_this_request:  # Only refresh once per request
                        logger.info("🔄 Attempting token refresh...")
                        if self.refresh_token():
                            token_refreshed_this_request = True
                            logger.info("✅ Token refreshed, retrying request...")
                            continue  # Retry with new token
                        else:
                            logger.error("❌ Token refresh failed, cannot continue")
                            return None
                    else:
                        logger.error("❌ Still getting 401 after token refresh - may be an auth issue")
                        return None
                elif response.status_code == 403:  # Forbidden - could be token issue
                    logger.warning(f"🚫 Access forbidden for zip {zip_code} - checking token...")
                    if not token_refreshed_this_request:
                        logger.info("🔄 Attempting token refresh for 403 error...")
                        if self.refresh_token():
                            token_refreshed_this_request = True
                            logger.info("✅ Token refreshed, retrying request...")
                            continue
                        else:
                            logger.error("❌ Token refresh failed for 403 error")
                            return None
                    else:
                        logger.error("❌ Still getting 403 after token refresh")
                        return None
                elif response.status_code == 429:  # Rate limited
                    logger.warning(f"⏳ Rate limited for zip {zip_code}, waiting longer...")
                    time.sleep(self.retry_delay * 2)  # Wait 4 seconds on rate limit
                    continue
                else:
                    logger.error(f"❌ API request failed for zip {zip_code}: {response.status_code} - {response.text}")
                    # Check if error message indicates token issues
                    if 'token' in response.text.lower() or 'unauthorized' in response.text.lower():
                        if not token_refreshed_this_request:
                            logger.info("🔄 Error mentions token, attempting refresh...")
                            if self.refresh_token():
                                token_refreshed_this_request = True
                                continue
                    
            except requests.exceptions.Timeout as e:
                logger.warning(f"⏰ Request timeout for zip {zip_code}: {e}")
                # Timeout could indicate token expiry, try refresh on first timeout
                if attempt == 0 and not token_refreshed_this_request:
                    logger.info("🔄 Timeout on first attempt, checking token...")
                    if self.refresh_token():
                        token_refreshed_this_request = True
                        logger.info("✅ Token refreshed after timeout, retrying...")
                        continue
                        
            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Request exception for zip {zip_code}: {e}")
                # Check if connection errors could be auth-related
                if 'unauthorized' in str(e).lower() and not token_refreshed_this_request:
                    logger.info("🔄 Connection error may be auth-related, trying token refresh...")
                    if self.refresh_token():
                        token_refreshed_this_request = True
                        continue
                
            if attempt < self.max_retries - 1:
                logger.info(f"⏳ Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)
        
        logger.error(f"❌ All retry attempts failed for zip {zip_code}")
        return None
    
    def extract_pharmacy_data(self, api_response: Dict, drug_info: Dict, zip_info: Dict) -> List[Dict]:
        """Extract pharmacy data from API response"""
        rows = []
        
        if not api_response or 'pharmacies' not in api_response:
            return rows
        
        # Extract facility benefit amount from top-level API response
        facility_benefit_amount = api_response.get('facilityBenefitAmount', 0)
            
        for pharmacy in api_response.get('pharmacies', []):
            row = {
                'timestamp': datetime.now().isoformat(),
                'state': zip_info['state'],
                'zip_code': zip_info['zip'],
                'city': zip_info['city'],
                'lat': zip_info['lat'],
                'lng': zip_info['lng'],
                
                # Drug information
                'procedure_code': drug_info['procedure_code'],
                'drug_name': drug_info['drug_name'],
                'dosage_form': drug_info['dosage_form'],
                'claim_count_orig': drug_info['claim_count'],
                
                # Pharmacy information
                'pharmacy_name': pharmacy.get('name', ''),
                'pharmacy_phone': pharmacy.get('phone', ''),
                'pharmacy_address': f"{pharmacy.get('address', {}).get('street', '')}, {pharmacy.get('address', {}).get('city', '')}, {pharmacy.get('address', {}).get('state', '')} {pharmacy.get('address', {}).get('zip', '')}",
                'pharmacy_distance': pharmacy.get('distance', 0),
                'pharmacy_rate': pharmacy.get('pharmacyRate', 0),
                'price_fairness': pharmacy.get('priceFairness', ''),
                
                # Benefit information
                'provider_price': pharmacy.get('careEstimateResult', {}).get('providerPrice', 0),
                'estimated_member_responsibility': pharmacy.get('careEstimateResult', {}).get('estimatedMemberResponsibility', 0),
                'earned_benefit': pharmacy.get('careEstimateResult', {}).get('earnedBenefit', 0),
                'applied_to_deductible': pharmacy.get('careEstimateResult', {}).get('appliedToDeductible', 0),
                'savings': pharmacy.get('careEstimateResult', {}).get('savings', 0),
                'bill_over_benefit_amount': pharmacy.get('careEstimateResult', {}).get('billOverBenefitAmount', 0),
                'facility_benefit_amount': facility_benefit_amount,
                
                # Additional fields from API response
                'gsn': pharmacy.get('gsn', ''),
                'ndc': pharmacy.get('ndc', ''),
                'qty': pharmacy.get('qty', 0),
            }
            rows.append(row)
            
        return rows
    
    def initialize_csv(self) -> List[str]:
        """Initialize CSV file with headers"""
        headers = [
            'timestamp', 'state', 'zip_code', 'city', 'lat', 'lng',
            'procedure_code', 'drug_name', 'dosage_form', 'claim_count_orig',
            'pharmacy_name', 'pharmacy_phone', 'pharmacy_address', 'pharmacy_distance', 'pharmacy_rate', 'price_fairness',
            'provider_price', 'estimated_member_responsibility', 'earned_benefit', 'applied_to_deductible', 
            'savings', 'bill_over_benefit_amount', 'facility_benefit_amount', 'gsn', 'ndc', 'qty'
        ]
        
        # Create CSV file with headers if it doesn't exist
        if not os.path.exists(self.output_file):
            with open(self.output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
        
        return headers
    
    def append_to_csv(self, rows: List[Dict]):
        """Append rows to CSV file"""
        if not rows:
            return
            
        with open(self.output_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.initialize_csv())
            writer.writerows(rows)
    
    def run_collection(self, csv_filepath: str, states_filter: List[str] = None):
        """Main collection process"""
        if self.test_mode:
            logger.info("🧪 Starting Sidecar API data collection in TEST MODE")
        else:
            logger.info("Starting Sidecar API data collection")
        
        # Load data
        drugs = self.load_drugs_from_excel(csv_filepath)
        zip_codes = self.get_zip_codes_with_coordinates(states_filter, self.batch_info)
        progress = self.load_progress()
        
        # Initialize CSV
        self.initialize_csv()
        
        total_combinations = len(drugs) * len(zip_codes)
        if self.test_mode:
            logger.info(f"🧪 TEST MODE: Total combinations to process: {total_combinations}")
            logger.info(f"🧪 TEST MODE: Using {len(drugs)} drugs × {len(zip_codes)} zip codes")
            logger.info(f"🧪 TEST MODE: Estimated runtime: {total_combinations * self.request_delay:.1f} seconds (~{(total_combinations * self.request_delay)/60:.1f} minutes)")
        else:
            logger.info(f"Total combinations to process: {total_combinations}")
            logger.info(f"Estimated runtime: {total_combinations * self.request_delay:.1f} seconds (~{(total_combinations * self.request_delay)/60:.1f} minutes)")
        
        processed_count = progress.get('total_processed', 0)
        
        for drug_idx, drug in enumerate(drugs):
            for zip_idx, zip_info in enumerate(zip_codes):
                combination_key = f"{drug['procedure_code']}_{zip_info['zip']}"
                
                # Skip if already processed
                if combination_key in progress.get('completed', []):
                    continue
                
                mode_indicator = "🧪 TEST: " if self.test_mode else ""
                logger.info(f"{mode_indicator}Processing {processed_count + 1}/{total_combinations}: {drug['drug_name']} in {zip_info['city']}, {zip_info['state']} ({zip_info['zip']})")
                
                # Check if auto-stop was triggered
                if self.auto_stop_triggered:
                    logger.error("🛑 AUTO-STOP: Collection halted due to too many consecutive API failures")
                    logger.error(f"📊 Total failed combinations: {len(self.failed_combinations)}")
                    logger.error(f"📊 Consecutive failures before stop: {self.consecutive_failures}")
                    logger.error("💡 Please check API status and restart manually when ready")
                    return
                
                # Make API request
                api_response = self.make_api_request(
                    zip_info['zip'], 
                    zip_info['lat'], 
                    zip_info['lng'],
                    drug['uuid'],
                    drug['drug_name']
                )
                
                if api_response:
                    # Reset consecutive failures on success
                    self.consecutive_failures = 0
                    
                    # Extract and save data
                    rows = self.extract_pharmacy_data(api_response, drug, zip_info)
                    if rows:
                        self.append_to_csv(rows)
                        logger.info(f"Saved {len(rows)} pharmacy records")
                    else:
                        logger.warning(f"No pharmacy data found for {drug['drug_name']} in {zip_info['zip']}")
                else:
                    # Track failed combination
                    self.failed_combinations.append(combination_key)
                    self.consecutive_failures += 1
                    logger.error(f"❌ Failed to get data for {drug['drug_name']} in {zip_info['zip']} (Total failures: {len(self.failed_combinations)}, Consecutive: {self.consecutive_failures})")
                    
                    # Check if we've hit the consecutive failure limit
                    if self.consecutive_failures >= self.max_consecutive_failures:
                        self.auto_stop_triggered = True
                        logger.error(f"🚨 CRITICAL: {self.consecutive_failures} consecutive API failures detected!")
                        logger.error("🛑 AUTO-STOP TRIGGERED: Too many consecutive failures")
                        logger.error("📋 Recent failed combinations:")
                        # Show last 10 failed combinations
                        recent_failures = self.failed_combinations[-self.max_consecutive_failures:]
                        for i, failed_combo in enumerate(recent_failures, 1):
                            logger.error(f"   {i}. {failed_combo}")
                        logger.error("💡 Collection will stop after updating progress")
                        logger.error("🔧 Please check API status, network, or authentication")
                        logger.error("🚀 Restart with: ./run_collection.sh")
                
                # Update progress (even for failed combinations to avoid retrying them)
                progress['completed'].append(combination_key)
                progress['total_processed'] = processed_count + 1
                self.save_progress(progress)
                
                processed_count += 1
                
                # Rate limiting
                time.sleep(self.request_delay)
        
        if self.auto_stop_triggered:
            logger.error("🛑 Collection stopped due to consecutive failure auto-stop trigger")
            logger.error(f"📊 Total failures: {len(self.failed_combinations)}")
            logger.error(f"📊 Consecutive failures: {self.consecutive_failures}")
            logger.error(f"📁 Output file: {self.output_file}")
            logger.error(f"🔄 Progress saved: {processed_count} combinations processed")
        elif self.test_mode:
            logger.info(f"🧪 TEST MODE: Collection completed! Output file: {self.output_file}")
            logger.info(f"🧪 TEST MODE: Total processed: {processed_count}")
            logger.info(f"🧪 Ready for full run! Remove --test flag to process all zip codes.")
        else:
            logger.info(f"Collection completed! Output file: {self.output_file}")
            logger.info(f"Total processed: {processed_count}")
            if len(self.failed_combinations) > 0:
                logger.warning(f"⚠️ Note: {len(self.failed_combinations)} combinations failed during collection")

def main():
    parser = argparse.ArgumentParser(description='Sidecar Health API Data Collection')
    parser.add_argument('--test', action='store_true', 
                       help='Run in test mode with only 2 zip codes per state (6 total)')
    parser.add_argument('--csv-file', default='top_100_drugs.csv',
                       help='Path to CSV file containing drug data (default: top_100_drugs.csv)')
    parser.add_argument('--states', nargs='+', choices=['FL', 'GA', 'OH'], 
                       help='Specify which states to process (default: all states). Example: --states OH or --states FL GA')
    parser.add_argument('--batch', type=int, 
                       help='Batch number to process (1-based). Must be used with --total-batches')
    parser.add_argument('--total-batches', type=int, 
                       help='Total number of batches to split each state into. Must be used with --batch')
    
    args = parser.parse_args()
    
    # Validate batch arguments
    if (args.batch and not args.total_batches) or (args.total_batches and not args.batch):
        logger.error("Both --batch and --total-batches must be specified together")
        return
    
    if args.batch and (args.batch < 1 or args.batch > args.total_batches):
        logger.error(f"Batch number must be between 1 and {args.total_batches}")
        return
    
    # Create batch info if specified
    batch_info = None
    if args.batch and args.total_batches:
        batch_info = {
            'batch_num': args.batch,
            'total_batches': args.total_batches
        }
    
    collector = SidecarAPICollector(test_mode=args.test, states_filter=args.states, batch_info=batch_info)
    
    if not os.path.exists(args.csv_file):
        logger.error(f"CSV file not found: {args.csv_file}")
        return
    
    try:
        collector.run_collection(args.csv_file, args.states)
    except KeyboardInterrupt:
        logger.info("Collection interrupted by user")
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        raise

if __name__ == "__main__":
    main()