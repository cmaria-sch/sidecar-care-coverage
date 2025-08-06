#!/usr/bin/env python3
"""
Provider API Comparison Test for Sidecar Provider Search
Compares our ProviderPriceInformation results with the dev API endpoint
"""

import pandas as pd
import requests
import json
import sys
import logging
import os
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime

# Import our provider search implementation
from ProviderPriceInformation import ProviderPriceInformation
from enhanced_benefit_calculator import EnhancedBenefitCalculator
from config import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class ProviderTestCase:
    """Test case structure for provider search"""
    sidecar_code: str
    zipcode: str
    latitude: float
    longitude: float
    radius: float = 8.0
    page: int = 0
    size: int = 50  # Compare top 50 providers with price
    test_name: str = ""
    specialties: List[str] = None
    
    def __post_init__(self):
        # Don't set default specialties - they should come from Snowflake CARE_REIMBURSEMENT_INFO.SPECIALTIES
        if self.specialties is None:
            self.specialties = []

@dataclass
class APIProviderResult:
    """Structure for API provider response"""
    providers: List[Dict[str, Any]]
    total_count: int
    page: int
    size: int
    success: bool = True
    error_message: str = ""

@dataclass
class PythonProviderResult:
    """Structure for our Python provider response"""
    providers: List[Dict[str, Any]]
    total_count: int
    success: bool = True
    error_message: str = ""

@dataclass
class ComparisonResult:
    """Provider comparison result structure"""
    test_case: ProviderTestCase
    python_result: Optional[PythonProviderResult]
    api_result: Optional[APIProviderResult]
    comparison_summary: Dict[str, Any]
    npi_order_match: bool
    common_npis: List[str]
    python_only_npis: List[str]
    api_only_npis: List[str]
    match_percentage: float

class ProviderAPITester:
    """Provider API comparison tester"""
    
    def __init__(self, es_endpoint: str = None, api_base_url: str = None):
        # Use centralized config as defaults
        api_config = config.get_api_config()
        
        self.es_endpoint = es_endpoint or config.get_elasticsearch_config().endpoint
        self.api_base_url = api_base_url or api_config.base_url
        self.login_url = f"{self.api_base_url}{api_config.auth_endpoint}"
        
        # Initialize our Python provider service using centralized config
        # Enable Snowflake filtering to match Java's CareReimbursementInfo.careSearchSpecialties filtering
        self.provider_service = ProviderPriceInformation(
            es_endpoint=self.es_endpoint,
            max_results=200,  # Increased to get all available providers for comparison
            enable_snowflake_filtering=True  # Enable to match Java filtering behavior
        )
        
        # Initialize benefit calculator for rating area and radius lookups (optional)
        self.benefit_calculator = None
        try:
            self.benefit_calculator = EnhancedBenefitCalculator()
            logger.info("Benefit calculator initialized for dynamic radius calculation")
        except Exception as e:
            logger.warning(f"Could not initialize benefit calculator (will use CSV radius): {e}")
            self.benefit_calculator = None
        
        # Authentication state
        self.auth_token = None
        self.member_uuid = None
        self.last_curl_command = None
        
        # Base API headers (will be updated with token)
        self.base_headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json; charset=utf-8',
            'fingerprint': '1696329321.1743525802',
            'origin': 'https://dev-app.sidecarhealth.com',
            'priority': 'u=1, i',
            'referer': 'https://dev-app.sidecarhealth.com/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'tz': 'PDT',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
        }
    
    def _get_auth_token(self) -> Optional[str]:
        """Get authentication token and memberUuid from login endpoint"""
        if self.auth_token and self.member_uuid:
            return self.auth_token
            
        try:
            # Basic auth header - using existing test credentials
            headers = {
                'accept': '*/*',
                'authorization': 'Basic dGVzdF9hc29fc2FuZHVza3lfb2gwMDZAeW9wbWFpbC5jb206VGVzdDEyMzQh',
                'content-type': 'application/json; charset=utf-8',
                'fingerprint': '1696329321.1743525802',
                'tz': 'PDT',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
            }
            
            logger.info("Getting authentication token and memberUuid from login...")
            response = requests.post(self.login_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            auth_data = response.json()
            logger.info(f"Login response keys: {list(auth_data.keys())}")
            
            # Extract authentication token
            self.auth_token = (auth_data.get('accessToken') or 
                              auth_data.get('access_token') or 
                              auth_data.get('token') or
                              auth_data.get('authToken'))
            
            # Extract memberUuid from login response
            possible_member_fields = ['sub', 'memberUuid', 'member_uuid', 'memberId', 'member_id', 'uuid', 'userId', 'user_id']
            self.member_uuid = ''
            
            for field in possible_member_fields:
                if field in auth_data and auth_data[field]:
                    self.member_uuid = str(auth_data[field])
                    logger.info(f"Found memberUuid from login: {self.member_uuid}")
                    break
            
            if self.auth_token:
                logger.info("Successfully obtained authentication token")
                if self.member_uuid:
                    logger.info(f"Successfully obtained memberUuid: {self.member_uuid}")
                else:
                    logger.warning("No memberUuid found in login response")
                return self.auth_token
            else:
                logger.error(f"No access token in login response. Available keys: {list(auth_data.keys())}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get authentication token: {str(e)}")
            return None

    # Removed _get_proper_radius method - now using ProviderPriceInformation's Snowflake-based radius calculation

    def call_python_provider_search(self, test_case: ProviderTestCase) -> PythonProviderResult:
        """Call our Python provider search implementation"""
        try:
            logger.info(f"Calling Python provider search for {test_case.test_name}")
            
            # Get the actual radius from Snowflake to match what we'll use for API call
            snowflake_radius = self.provider_service.get_radius_for_zipcode(test_case.zipcode)
            logger.info(f"Snowflake radius for zipcode {test_case.zipcode}: {snowflake_radius} miles")
            
            # Store the radius for use in API call
            test_case.calculated_radius = snowflake_radius
            
            # Get specialties from Snowflake CARE_REIMBURSEMENT_INFO.SPECIALTIES if not provided
            if not test_case.specialties and hasattr(self.provider_service, 'care_lookup') and self.provider_service.care_lookup:
                snowflake_specialties = self.provider_service.care_lookup.get_care_specialties(test_case.sidecar_code)
                if snowflake_specialties:
                    test_case.specialties = snowflake_specialties
                    logger.info(f"Got specialties from Snowflake for {test_case.sidecar_code}: {snowflake_specialties}")
                else:
                    logger.warning(f"No specialties found in Snowflake for {test_case.sidecar_code}")
            elif not test_case.specialties:
                logger.warning(f"No specialties available for {test_case.sidecar_code} - Snowflake not available")
            
            # Use ProviderPriceInformation's Snowflake-based radius calculation
            # Pass zipcode so it can calculate proper radius via Snowflake lookup
            providers = self.provider_service.getProviders(
                sidecar_code=test_case.sidecar_code,
                specialties=test_case.specialties,
                lat=test_case.latitude,
                lon=test_case.longitude,
                radius=None,  # Let it calculate from zipcode via Snowflake
                zipcode=test_case.zipcode,
                insurance_filing_uuid=None  # Could be enhanced later if needed
            )
            

            
            # Keep all providers from Python implementation - size limiting will be done before comparison
            limited_providers = providers[:25]  # Limit to top 25 providers for comparison
            
            # Remove price information as requested
            clean_providers = []
            for provider in limited_providers:
                clean_provider = {
                    'npi': provider.get('_id'),
                    'es_score': provider.get('_score', 0),
                    'query_source': provider.get('_query_source', 'unknown'),
                    'source': provider.get('_source', {})
                }
                # Remove pricing info from source
                if 'careRates' in clean_provider['source']:
                    del clean_provider['source']['careRates']
                if 'providerRate' in clean_provider['source']:
                    del clean_provider['source']['providerRate']
                
                clean_providers.append(clean_provider)
            
            return PythonProviderResult(
                providers=clean_providers,
                total_count=len(limited_providers),
                success=True
            )
            
        except Exception as e:
            logger.error(f"Python provider search failed: {e}")
            return PythonProviderResult(
                providers=[],
                total_count=0,
                success=False,
                error_message=str(e)
            )

    def _get_state_from_zipcode(self, zipcode: str) -> str:
        """Get state abbreviation from zipcode"""
        # Common Ohio zipcodes from test data
        ohio_zipcodes = ['44870', '44114', '43215', '45202', '43604', '45402', 
                        '44308', '44503', '44702', '45801', '44902', '44052', 
                        '44035', '45840', '43420', '43537', '43623', '43551', '43606', '43615', '43608']
        
        # Tennessee zipcodes
        tennessee_zipcodes = ['37209', '37203', '37204', '37205', '37206', '37207', '37208', '37210']
        
        if zipcode in ohio_zipcodes:
            return 'OH'
        elif zipcode in tennessee_zipcodes:
            return 'TN'
        else:
            # Default based on zipcode ranges
            if zipcode.startswith('37'):
                return 'TN'
            elif zipcode.startswith('4'):
                return 'OH'
            else:
                return 'OH'  # Default fallback

    def call_api_provider_search(self, test_case: ProviderTestCase) -> APIProviderResult:
        """Call the dev API endpoint for provider search"""
        try:
            logger.info(f"Calling API provider search for {test_case.test_name}")
            
            # Get authentication token first
            auth_token = self._get_auth_token()
            if not auth_token:
                return APIProviderResult(
                    providers=[],
                    total_count=0,
                    page=test_case.page,
                    size=test_case.size,
                    success=False,
                    error_message="Failed to get authentication token"
                )
            
            # Build API headers with token
            api_headers = self.base_headers.copy()
            api_headers['token'] = auth_token
            api_headers['tz'] = 'PDT'  # Add timezone header as in the curl command
            
            # Use the Snowflake-calculated radius if available, otherwise fall back to CSV radius
            api_radius = getattr(test_case, 'calculated_radius', test_case.radius)
            logger.info(f"Using radius for API call: {api_radius} miles (Snowflake: {hasattr(test_case, 'calculated_radius')})")
            
            # Build API URL - Use the correct rates/cares/doctors endpoint from config
            api_config = config.get_api_config()
            url = f"{self.api_base_url}{api_config.doctors_endpoint}"
            params = {
                'memberUuid': self.member_uuid,
                'sidecarCode': test_case.sidecar_code,
                'receiveAt': 'home-or-office',  # Default receive option
                'zipCode': test_case.zipcode,
                'state': self._get_state_from_zipcode(test_case.zipcode),
                'lat': test_case.latitude,
                'lon': test_case.longitude,
                'radius': api_radius,  # Use Snowflake-calculated radius
                'priceSort': 'ASC',
                'monitoringId': f'test-{test_case.test_name}',  # Use test name as monitoring ID
                'sessionId': '934703029460751',  # Static session ID for testing
                'page': test_case.page,
                'size': 50  # Get 50 providers from API for comparison
            }
            
            logger.info(f"API call: {url} with memberUuid: {self.member_uuid}")
            
            # API request ready - curl logging disabled
            
            # Make API call
            response = requests.get(url, headers=api_headers, params=params, timeout=30)
            response.raise_for_status()
            
            api_data = response.json()
            
            # Extract providers from API response
            providers = []
            if isinstance(api_data, dict):
                if 'content' in api_data:
                    providers = api_data['content']
                elif 'data' in api_data:
                    providers = api_data['data']
                elif 'providers' in api_data:
                    providers = api_data['providers']
                else:
                    # If it's a list of providers directly
                    if isinstance(api_data.get('items'), list):
                        providers = api_data['items']
            elif isinstance(api_data, list):
                providers = api_data
            
            logger.info(f"API returned {len(providers)} providers")
            
            # Filter out providers with empty or null careRates arrays
            providers_with_care_rates = []
            for provider in providers:
                care_rates = provider.get('careRates', [])
                
                # Check if careRates exists and is not empty
                if care_rates and isinstance(care_rates, list) and len(care_rates) > 0:
                    # Additional check: make sure at least one rate has actual data
                    has_valid_rate = False
                    for rate in care_rates:
                        if isinstance(rate, dict) and rate.get('sidecarCode'):
                            has_valid_rate = True
                            break
                    if has_valid_rate:
                        providers_with_care_rates.append(provider)
                elif care_rates and isinstance(care_rates, dict) and care_rates.get('sidecarCode'):
                    # Handle case where careRates is a single dict instead of list
                    providers_with_care_rates.append(provider)
            
            logger.info(f"API providers after filtering (with non-empty careRates): {len(providers_with_care_rates)} out of {len(providers)}")
            
            # Take top 50 providers for comparison and log NPIs
            top_50_providers = providers_with_care_rates[:50]
            api_npis = []
            for provider in top_50_providers:
                npi = provider.get('npi') or provider.get('id') or provider.get('providerId')
                if npi:
                    api_npis.append(str(npi))
            
            logger.info(f"\n=== TOP 50 API NPIs ===")
            logger.info(f"API NPIs: {','.join(api_npis)}")
            
            return APIProviderResult(
                providers=top_50_providers,
                total_count=len(providers_with_care_rates),
                page=test_case.page,
                size=test_case.size,
                success=True
            )
            
        except Exception as e:
            logger.error(f"API provider search failed: {e}")
            return APIProviderResult(
                providers=[],
                total_count=0,
                page=test_case.page,
                size=test_case.size,
                success=False,
                error_message=str(e)
            )

    def compare_provider_results(self, test_case: ProviderTestCase, 
                                python_result: PythonProviderResult, 
                                api_result: APIProviderResult) -> ComparisonResult:
        """Compare Python and API provider results"""
        
        # Use 25 Python providers and up to 50 API providers for comparison
        api_provider_count = len(api_result.providers)
        python_provider_count = len(python_result.providers)
        
        # Limit Python to 25 and API to 50 for comparison
        limited_python_providers = python_result.providers[:25]
        limited_api_providers = api_result.providers[:50]
        
        logger.info(f"Comparison: {len(limited_python_providers)} Python providers vs {len(limited_api_providers)} API providers")
        
        # Extract NPIs from both limited results
        python_npis = [p.get('npi', '') for p in limited_python_providers if p.get('npi')]
        api_npis = []
        
        # Extract NPIs from API response (handle different response formats)
        for provider in limited_api_providers:
            npi = None
            if isinstance(provider, dict):
                npi = provider.get('npi') or provider.get('id') or provider.get('providerId')
            if npi:
                api_npis.append(str(npi))
        
        # Compare NPIs
        common_npis = [npi for npi in python_npis if npi in api_npis]
        python_only_npis = [npi for npi in python_npis if npi not in api_npis]
        api_only_npis = [npi for npi in api_npis if npi not in python_npis]
        
        # Check order match (for common NPIs)
        npi_order_match = False
        if common_npis:
            # Get the order of common NPIs in both lists
            python_common_order = [npi for npi in python_npis if npi in common_npis]
            api_common_order = [npi for npi in api_npis if npi in common_npis]
            npi_order_match = python_common_order == api_common_order
        
        # Calculate match percentage based on Python NPIs (how many Python NPIs are found in API)
        match_percentage = (len(common_npis) / len(python_npis) * 100) if len(python_npis) > 0 else 0
        
        # Determine if test passes (>50% match)
        test_passes = match_percentage > 50.0
        
        # Create comparison summary
        comparison_summary = {
            'python_provider_count': len(python_npis),
            'api_provider_count': len(api_npis),
            'python_total_count': python_provider_count,
            'api_total_count': api_provider_count,
            'common_providers': len(common_npis),
            'python_only_providers': len(python_only_npis),
            'api_only_providers': len(api_only_npis),
            'order_matches': npi_order_match,
            'match_percentage': round(match_percentage, 2),
            'test_passes': test_passes,
            'python_success': python_result.success,
            'api_success': api_result.success
        }
        
        return ComparisonResult(
            test_case=test_case,
            python_result=python_result,
            api_result=api_result,
            comparison_summary=comparison_summary,
            npi_order_match=npi_order_match,
            common_npis=common_npis,
            python_only_npis=python_only_npis,
            api_only_npis=api_only_npis,
            match_percentage=match_percentage
        )

    def run_single_test(self, test_case: ProviderTestCase) -> ComparisonResult:
        """Run a single provider comparison test"""
        logger.info(f"Running test: {test_case.test_name}")
        
        # Call both implementations
        python_result = self.call_python_provider_search(test_case)
        api_result = self.call_api_provider_search(test_case)
        
        # Compare results
        comparison = self.compare_provider_results(test_case, python_result, api_result)
        
        # Log summary
        logger.info(f"Test {test_case.test_name} completed:")
        logger.info(f"  Python: {comparison.comparison_summary['python_provider_count']} providers")
        logger.info(f"  API: {comparison.comparison_summary['api_provider_count']} providers")
        logger.info(f"  Common: {comparison.comparison_summary['common_providers']} providers")
        logger.info(f"  Match %: {comparison.match_percentage:.1f}%")
        logger.info(f"  Order Match: {comparison.npi_order_match}")
        
        return comparison

    def run_tests_from_csv(self, csv_file: str) -> List[ComparisonResult]:
        """Run tests from CSV file"""
        logger.info(f"Loading test cases from {csv_file}")
        
        try:
            df = pd.read_csv(csv_file)
            test_results = []
            
            for index, row in df.iterrows():
                # Create test case from CSV row
                specialties = []
                if 'specialties' in row and pd.notna(row['specialties']):
                    specialties = [s.strip() for s in str(row['specialties']).split(',')]
                
                test_case = ProviderTestCase(
                    sidecar_code=str(row['sidecar_code']),
                    zipcode=str(row['zipcode']),
                    latitude=float(row['latitude']),
                    longitude=float(row['longitude']),
                    radius=float(row.get('radius', 0.0)) if row.get('radius') and float(row.get('radius', 0.0)) > 0 else None,
                    page=int(row.get('page', 0)),
                    size=int(row.get('size', 50)),
                    test_name=str(row.get('test_name', f'Test_{index+1}')),
                    specialties=specialties if specialties else None
                )
                
                # Run the test
                result = self.run_single_test(test_case)
                test_results.append(result)
            
            return test_results
            
        except Exception as e:
            logger.error(f"Failed to run tests from CSV: {e}")
            return []

    def save_results_to_csv(self, results: List[ComparisonResult], output_file: str):
        """Save comparison results to CSV"""
        logger.info(f"Saving results to {output_file}")
        
        # Prepare data for CSV - simplified output with only essential columns
        rows = []
        for result in results:
            # Extract NPIs for this result
            python_npis = [p.get('npi', '') for p in result.python_result.providers if p.get('npi')]
            api_npis = []
            for provider in result.api_result.providers:
                npi = provider.get('npi') or provider.get('id') or provider.get('providerId')
                if npi:
                    api_npis.append(str(npi))
            
            row = {
                'sidecar_code': result.test_case.sidecar_code,
                'zipcode': result.test_case.zipcode,
                'latitude': result.test_case.latitude,
                'longitude': result.test_case.longitude,
                'radius': getattr(result.test_case, 'calculated_radius', result.test_case.radius),
                'match_percentage': result.match_percentage,
                'test_passes': result.comparison_summary.get('test_passes', False),
                'python_provider_count': len(python_npis),
                'api_provider_count': len(api_npis)
            }
            rows.append(row)
        
        # Save to CSV
        df = pd.DataFrame(rows)
        df.to_csv(output_file, index=False)
        logger.info(f"Results saved to {output_file}")
    
    def close(self):
        """Clean up resources"""
        if hasattr(self, 'benefit_calculator') and self.benefit_calculator:
            self.benefit_calculator.close_connection()

def main():
    """Main function"""
    if len(sys.argv) < 3:
        print("Usage: python compare_provider_test.py <input_csv> <output_csv>")
        print("Example: python compare_provider_test.py provider_test_cases.csv test_results/provider_comparison_results.csv")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    output_csv = sys.argv[2]
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    
    # Initialize tester
    tester = ProviderAPITester()
    
    try:
        # Run tests
        results = tester.run_tests_from_csv(input_csv)
        
        if results:
            # Save results
            tester.save_results_to_csv(results, output_csv)
            
            # Print summary
            print(f"\n{'='*60}")
            print("PROVIDER COMPARISON TEST SUMMARY")
            print(f"{'='*60}")
            print(f"Total tests run: {len(results)}")
            
            successful_tests = [r for r in results if r.python_result.success and r.api_result.success]
            print(f"Successful tests: {len(successful_tests)}")
            
            if successful_tests:
                avg_match = sum(r.match_percentage for r in successful_tests) / len(successful_tests)
                order_matches = sum(1 for r in successful_tests if r.npi_order_match)
                
                print(f"Average match percentage: {avg_match:.1f}%")
                print(f"Order matches: {order_matches}/{len(successful_tests)}")
                
                print(f"\nDetailed Results:")
                for result in results:
                    status = "✅" if result.python_result.success and result.api_result.success else "❌"
                    print(f"  {status} {result.test_case.test_name}: {result.match_percentage:.1f}% match, Order: {result.npi_order_match}")
            
            print(f"\nResults saved to: {output_csv}")
        else:
            print("❌ No test results generated")
            sys.exit(1)
    finally:
        tester.close()

if __name__ == "__main__":
    main()