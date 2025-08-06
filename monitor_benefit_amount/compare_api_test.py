#!/usr/bin/env python3
"""
API Comparison Test for Sidecar Benefit Calculator - Fixed Version
Compares benefit calculator results with API endpoint responses
"""

import pandas as pd
import requests
import json
import sys
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# Import the enhanced benefit calculator - FIXED IMPORT
from enhanced_benefit_calculator import EnhancedBenefitCalculator, EnhancedBenefitResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class TestCase:
    """Test case structure"""
    sidecar_code: str
    insurance_filing_uuid: str
    zipcode: str
    member_uuid: str
    quantity: float = 1.0
    search_radius: int = 8

@dataclass
class APIResponse:
    """API response structure for comparison"""
    facility_benefit_amount: float
    non_facility_benefit_amount: float
    rx_benefit_amount: float
    facility_should_cost: float
    non_facility_should_cost: float
    provider_price: float
    estimated_member_responsibility: float
    earned_benefit: float
    category_slug: str = ""
    selected_ndc: str = ""

@dataclass
class ComparisonResult:
    """Comparison result structure"""
    test_case: TestCase
    calculator_result: Optional[EnhancedBenefitResult]  # FIXED TYPE
    api_result: Optional[APIResponse]
    api_error: Optional[str]
    calculator_error: Optional[str]
    differences: Dict
    match_status: str

class APIComparator:
    """Compares benefit calculator with API responses"""

    def __init__(self):
        # FIXED: Complete API endpoint
        self.api_base_url = "https://dev-api.sidecarhealth.com/care/v1/cares/detail"
        self.login_url = "https://dev-api.sidecarhealth.com/auth/v1/login?type=password"
        # FIXED: Initialize the benefit calculator
        self.benefit_calculator = EnhancedBenefitCalculator()
        self.auth_token = None

    def _get_auth_token(self) -> Optional[str]:
        """Get authentication token and memberUuid from login endpoint"""
        if self.auth_token and hasattr(self, 'member_uuid'):
            return self.auth_token
            
        try:
            # Basic auth header - base64 encoded credentials from your curl command
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
            
            # Debug: Print full login response to understand structure
            print(f"\n🔍 FULL LOGIN RESPONSE DEBUG:")
            print(f"📋 Response Keys: {list(auth_data.keys())}")
            for key, value in auth_data.items():
                print(f"  {key}: {value}")
            
            # Extract authentication token
            self.auth_token = (auth_data.get('accessToken') or 
                              auth_data.get('access_token') or 
                              auth_data.get('token') or
                              auth_data.get('authToken'))
            
            # Extract memberUuid from login response
            # Based on the actual response structure, memberUuid is in the 'sub' field (JWT subject)
            possible_member_fields = ['sub', 'memberUuid', 'member_uuid', 'memberId', 'member_id', 'uuid', 'userId', 'user_id']
            self.member_uuid = ''
            
            print(f"\n🔍 SEARCHING FOR MEMBER UUID:")
            for field in possible_member_fields:
                if field in auth_data and auth_data[field]:
                    print(f"  ✅ Found {field}: {auth_data[field]}")
                    self.member_uuid = str(auth_data[field])
                    break
                else:
                    print(f"  ❌ {field}: {'not found' if field not in auth_data else 'empty/null'}")
            
            if not self.member_uuid:
                print(f"  ⚠️  No memberUuid found - will need to use from test case or handle gracefully")
            else:
                print(f"  ✅ Successfully extracted memberUuid: {self.member_uuid}")
            
            if self.auth_token:
                logger.info("Successfully obtained authentication token")
                if self.member_uuid:
                    logger.info(f"Successfully obtained memberUuid from login: {self.member_uuid}")
                else:
                    logger.warning("No memberUuid found in login response")
                return self.auth_token
            else:
                logger.error(f"No access token in login response. Available keys: {list(auth_data.keys())}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get authentication token: {str(e)}")
            return None

    def _get_care_uuid_from_calculator(self, sidecar_code: str, insurance_filing_uuid: str, zipcode: str) -> Optional[str]:
        """Get care UUID by running a partial calculation"""
        try:
            # This is a bit of a workaround - we run the calculation to get the care_uuid
            result = self.benefit_calculator.calculate_benefit(
                sidecar_code=sidecar_code,
                insurance_filing_uuid=insurance_filing_uuid,
                zipcode=zipcode,
                quantity=1.0
            )
            return result.care_uuid
        except Exception as e:
            logger.error(f"Failed to get care UUID: {str(e)}")
            return None

    def _call_api(self, test_case: TestCase) -> Tuple[Optional[APIResponse], Optional[str]]:
        """Call the API endpoint and return parsed response"""
        try:
            # Get authentication token first
            auth_token = self._get_auth_token()
            if not auth_token:
                return None, "Failed to get authentication token"

            # Get care_uuid from our calculator
            care_uuid = self._get_care_uuid_from_calculator(
                test_case.sidecar_code,
                test_case.insurance_filing_uuid,
                test_case.zipcode
            )

            if not care_uuid:
                logger.info(f"Care not available for filing - Sidecar code: {test_case.sidecar_code}, Insurance filing: {test_case.insurance_filing_uuid}")
                print(f"Insurance filing info: {test_case.insurance_filing_uuid} - Care not available for sidecar code: {test_case.sidecar_code}")
                return None, f"Care not available for filing - Sidecar code: {test_case.sidecar_code}"

            # Get category slug from calculator result (no normalization needed)
            try:
                temp_result = self.benefit_calculator.calculate_benefit(
                    sidecar_code=test_case.sidecar_code,
                    insurance_filing_uuid=test_case.insurance_filing_uuid,
                    zipcode=test_case.zipcode,
                    quantity=1.0
                )
                # Need to get the category_slug from the care_data directly since it's not in the result
                care_data = self.benefit_calculator._get_comprehensive_care_data(
                    test_case.sidecar_code, 
                    test_case.insurance_filing_uuid, 
                    temp_result.rating_area
                )
                category = care_data.get('CATEGORY_SLUG', 'doctor-visit')
            except Exception:
                category = "doctor-visit"  # Default fallback

            # Use memberUuid from login response, fallback to test case if not available
            login_member_uuid = getattr(self, 'member_uuid', '')
            member_uuid_to_use = login_member_uuid if login_member_uuid else test_case.member_uuid
            
            print(f"\n🔍 MEMBER UUID SELECTION:")
            print(f"  Login memberUuid: '{login_member_uuid}'")
            print(f"  Test case memberUuid: '{test_case.member_uuid}'")
            print(f"  Selected memberUuid: '{member_uuid_to_use}'")
            
            if not member_uuid_to_use or member_uuid_to_use == 'from_login':
                error_msg = "No valid memberUuid available (neither from login nor test case)"
                logger.error(error_msg)
                return None, error_msg
            
            params = {
                'uuid': care_uuid,
                'zipCode': test_case.zipcode,
                'memberUuid': member_uuid_to_use,
                'category': category,
                'searchRadius': test_case.search_radius,
                'qty': test_case.quantity  # Add quantity parameter
            }
            
            logger.info(f"Using memberUuid: {member_uuid_to_use} ({'from login' if login_member_uuid else 'from test case'})")

            # Set up headers with token (matching the correct curl command)
            headers = {
                'accept': '*/*',
                'content-type': 'application/json; charset=utf-8',
                'origin': 'https://dev-app.sidecarhealth.com',
                'referer': 'https://dev-app.sidecarhealth.com/',
                'token': auth_token,  # Use 'token' header instead of 'Authorization: Bearer'
            }

            logger.info(f"Calling API with params: {params}")
            response = requests.get(self.api_base_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()

            api_data = response.json()
            logger.info(f"API Response received for {test_case.sidecar_code}")
            
            # Debug: Log full API response structure for prescription NDC analysis
            category_slug = api_data.get('categorySlug', '')
            if category_slug == 'prescriptions':
                print(f"\n🔍 PRESCRIPTION API RESPONSE DEBUG for {test_case.sidecar_code}:")
                print(f"📋 Full API Response Keys: {list(api_data.keys())}")
                print(f"🏷️ Category Slug: {category_slug}")
                
                # Check for various possible NDC field names
                possible_ndc_fields = ['selectedNDC', 'selected_ndc', 'selectedNdc', 'ndc', 'drug_ndc', 'actualNDC', 'drugNDC']
                print(f"🔍 Checking for NDC fields:")
                for field in possible_ndc_fields:
                    if field in api_data:
                        print(f"  ✅ {field}: {api_data[field]}")
                    else:
                        print(f"  ❌ {field}: not found")
                
                # Log key prescription-specific fields
                print(f"💊 Prescription Details:")
                print(f"  facilityBenefitAmount: {api_data.get('facilityBenefitAmount', 'N/A')}")
                print(f"  nonFacilityBenefitAmount: {api_data.get('nonFacilityBenefitAmount', 'N/A')}")
                print(f"  rxBenefitAmount: {api_data.get('rxBenefitAmount', 'N/A')}")
                print(f"  Input NDC: {test_case.sidecar_code}")
                print(f"  Quantity: {test_case.quantity}")

            # Try multiple possible field names for selectedNDC
            selected_ndc = (api_data.get('selectedNDC') or 
                          api_data.get('selected_ndc') or 
                          api_data.get('selectedNdc') or 
                          api_data.get('ndc') or 
                          api_data.get('drug_ndc') or 
                          api_data.get('actualNDC') or 
                          api_data.get('drugNDC') or '')

            # Extract benefit amounts from API response
            # Note: For prescriptions, rxBenefitAmount field doesn't exist in API response
            # Instead, prescription benefits are returned in facilityBenefitAmount/nonFacilityBenefitAmount
            api_response = APIResponse(
                facility_benefit_amount=api_data.get('facilityBenefitAmount', 0.0),
                non_facility_benefit_amount=api_data.get('nonFacilityBenefitAmount', 0.0),
                rx_benefit_amount=api_data.get('rxBenefitAmount', 0.0),  # This field doesn't exist for prescriptions
                facility_should_cost=api_data.get('facilityShouldCost', 0.0),
                non_facility_should_cost=api_data.get('nonFacilityShouldCost', 0.0),
                provider_price=api_data.get('providerPrice', 0.0),
                estimated_member_responsibility=api_data.get('estimatedMemberResponsibility', 0.0),
                earned_benefit=api_data.get('earnedBenefit', 0.0),
                category_slug=category_slug,
                selected_ndc=selected_ndc
            )
            
            return api_response, None

        except Exception as e:
            logger.error(f"API call failed: {str(e)}")
            return None, str(e)

    def _calculate_differences(self, calc_result: EnhancedBenefitResult, api_result: APIResponse) -> Dict:
        """Calculate differences between calculator and API results"""
        differences = {}

        # Use API's categorySlug to reliably detect prescription drugs
        is_prescription = api_result.category_slug == "prescriptions"

        if is_prescription:
            # For prescriptions, compare our RX benefit against API's facility benefit
            # Since prescription API responses return benefits in facilityBenefitAmount, not rxBenefitAmount
            comparisons = [
                ('rx_benefit_amount', calc_result.rx_benefit_amount, api_result.facility_benefit_amount)
            ]
            print(f"    🔍 Prescription detected (categorySlug='{api_result.category_slug}') - comparing calculator RX benefit vs API facility benefit")
            print(f"        Calculator rx_benefit_amount: ${calc_result.rx_benefit_amount:.2f}")
            print(f"        API facilityBenefitAmount: ${api_result.facility_benefit_amount:.2f}")
            print(f"        API rxBenefitAmount (should be 0): ${api_result.rx_benefit_amount:.2f}")
        else:
            # For non-prescriptions, compare facility/non-facility benefits
            comparisons = [
                ('facility_benefit_amount', calc_result.facility_benefit_amount, api_result.facility_benefit_amount),
                ('non_facility_benefit_amount', calc_result.non_facility_benefit_amount, api_result.non_facility_benefit_amount),
                ('rx_benefit_amount', calc_result.rx_benefit_amount, api_result.rx_benefit_amount),
                ('facility_should_cost', calc_result.facility_should_cost, api_result.facility_should_cost),
                ('non_facility_should_cost', calc_result.non_facility_should_cost, api_result.non_facility_should_cost)
            ]
            print(f"    🔍 Non-prescription detected (categorySlug='{api_result.category_slug}') - comparing all benefit fields")

        for field_name, calc_value, api_value in comparisons:
            diff = abs(calc_value - api_value)
            percent_diff = (diff / max(abs(api_value), 0.01)) * 100 if api_value != 0 else 0

            differences[field_name] = {
                'calculator': calc_value,
                'api': api_value,
                'difference': diff,
                'percent_difference': percent_diff
            }

        return differences

    def _handle_prescription_ndc_difference(self, test_case: TestCase, api_result: APIResponse) -> Tuple[Optional[EnhancedBenefitResult], str]:
        """Handle prescription cases where API returns different selectedNDC"""
        input_ndc = test_case.sidecar_code
        selected_ndc = api_result.selected_ndc.strip() if api_result.selected_ndc else ""
        
        print(f"\n🔍 NDC COMPARISON for {input_ndc}:")
        print(f"  Input NDC: '{input_ndc}'")
        print(f"  Selected NDC: '{selected_ndc}'")
        print(f"  Selected NDC empty: {not selected_ndc}")
        print(f"  NDCs equal: {input_ndc == selected_ndc}")
        
        if not selected_ndc or input_ndc == selected_ndc:
            # No NDC difference, use original calculation
            print(f"  ✅ Using original NDC for calculation: {input_ndc}")
            calc_result = self.benefit_calculator.calculate_benefit(
                sidecar_code=test_case.sidecar_code,
                insurance_filing_uuid=test_case.insurance_filing_uuid,
                zipcode=test_case.zipcode,
                quantity=test_case.quantity
            )
            return calc_result, test_case.sidecar_code
        else:
            # NDC difference - calculate benefit for selectedNDC
            print(f"  🔄 NDC DIFFERENCE DETECTED!")
            print(f"  📊 Recalculating benefit amount using selectedNDC: {selected_ndc}")
            
            try:
                calc_result = self.benefit_calculator.calculate_benefit(
                    sidecar_code=selected_ndc,
                    insurance_filing_uuid=test_case.insurance_filing_uuid,
                    zipcode=test_case.zipcode,
                    quantity=test_case.quantity
                )
                # Create display code showing both NDCs with clear prefix
                display_code = f"{input_ndc} (NDC override: {selected_ndc})"
                print(f"  ✅ Successfully calculated benefit for selectedNDC")
                print(f"  📝 Display code: {display_code}")
                return calc_result, display_code
            except Exception as e:
                print(f"  ❌ Failed to calculate benefit for selectedNDC {selected_ndc}: {str(e)}")
                print(f"  🔄 Falling back to original NDC: {input_ndc}")
                # Fallback to original NDC
                calc_result = self.benefit_calculator.calculate_benefit(
                    sidecar_code=test_case.sidecar_code,
                    insurance_filing_uuid=test_case.insurance_filing_uuid,
                    zipcode=test_case.zipcode,
                    quantity=test_case.quantity
                )
                display_code = f"{input_ndc} (NDC override: {selected_ndc}, calc failed)"
                print(f"  📝 Fallback display code: {display_code}")
                return calc_result, display_code

    def run_test_case(self, test_case: TestCase) -> ComparisonResult:
        """Run a single test case comparison"""
        logger.info(f"Running test case: {test_case.sidecar_code}")

        calculator_result = None
        calculator_error = None
        display_sidecar_code = test_case.sidecar_code

        # Call API first (required for prescriptions to check selectedNDC)
        api_result, api_error = self._call_api(test_case)

        # Run benefit calculator with prescription NDC handling
        try:
            if api_result and api_result.category_slug == "prescriptions":
                # For prescriptions, handle potential NDC differences
                calculator_result, display_sidecar_code = self._handle_prescription_ndc_difference(test_case, api_result)
            else:
                # For non-prescriptions, use standard calculation
                calculator_result = self.benefit_calculator.calculate_benefit(
                    sidecar_code=test_case.sidecar_code,
                    insurance_filing_uuid=test_case.insurance_filing_uuid,
                    zipcode=test_case.zipcode,
                    quantity=test_case.quantity
                )
        except Exception as e:
            calculator_error = str(e)
            logger.error(f"Calculator failed: {calculator_error}")

        # Calculate differences if both succeeded
        differences = {}
        match_status = "UNKNOWN"

        if calculator_error:
            match_status = "CALCULATOR_ERROR"
        elif api_error:
            match_status = "API_ERROR"
        elif calculator_result and api_result:
            differences = self._calculate_differences(calculator_result, api_result)

            # Determine match status
            max_percent_diff = max([d['percent_difference'] for d in differences.values()] + [0])
            if max_percent_diff < 1.0:  # Less than 1% difference
                match_status = "MATCH"
            elif max_percent_diff < 5.0:  # Less than 5% difference
                match_status = "CLOSE_MATCH"
            else:
                match_status = "MISMATCH"

        # Create a modified test case for display if NDC changed
        display_test_case = test_case
        if display_sidecar_code != test_case.sidecar_code:
            display_test_case = TestCase(
                sidecar_code=display_sidecar_code,
                insurance_filing_uuid=test_case.insurance_filing_uuid,
                zipcode=test_case.zipcode,
                member_uuid=test_case.member_uuid,
                quantity=test_case.quantity,
                search_radius=test_case.search_radius
            )

        return ComparisonResult(
            test_case=display_test_case,
            calculator_result=calculator_result,
            api_result=api_result,
            api_error=api_error,
            calculator_error=calculator_error,
            differences=differences,
            match_status=match_status
        )

    def load_test_cases_from_csv(self, csv_file: str) -> List[TestCase]:
        """Load test cases from CSV file"""
        test_cases = []

        try:
            df = pd.read_csv(csv_file)
            # member_uuid is now obtained from login response, so not required in CSV
            required_columns = ['sidecar_code', 'insurance_filing_uuid', 'zipcode']

            # Check if all required columns exist
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")

            # Ensure columns exist and fill missing values with defaults
            if 'quantity' not in df.columns:
                df['quantity'] = 1.0
            else:
                df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(1.0)

            if 'search_radius' not in df.columns:
                df['search_radius'] = 8
            else:
                df['search_radius'] = pd.to_numeric(df['search_radius'], errors='coerce').fillna(8)

            # Clean the data - remove rows with NaN in required columns
            df = df.dropna(subset=required_columns)

            for _, row in df.iterrows():
                # Skip rows with invalid data
                if pd.isna(row['sidecar_code']) or pd.isna(row['insurance_filing_uuid']):
                    continue

                # member_uuid is optional - use from CSV if available, otherwise will use login response
                member_uuid = str(row['member_uuid']).strip() if 'member_uuid' in df.columns and not pd.isna(row['member_uuid']) else 'from_login'

                test_case = TestCase(
                    sidecar_code=str(row['sidecar_code']).strip(),
                    insurance_filing_uuid=str(row['insurance_filing_uuid']).strip(),
                    zipcode=str(row['zipcode']).strip(),
                    member_uuid=member_uuid,
                    quantity=float(row['quantity']),
                    search_radius=int(row['search_radius'])
                )
                test_cases.append(test_case)

            logger.info(f"Loaded {len(test_cases)} test cases from {csv_file}")
            return test_cases

        except Exception as e:
            logger.error(f"Failed to load test cases from CSV: {str(e)}")
            raise

    def run_comparison_tests(self, csv_file: str, output_file: str = None):
        """Run all comparison tests and generate report"""
        test_cases = self.load_test_cases_from_csv(csv_file)
        results = []

        print(f"\n🧪 Running {len(test_cases)} comparison tests...")
        print("="*80)

        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[{i}/{len(test_cases)}] Testing: {test_case.sidecar_code}")
            result = self.run_test_case(test_case)
            results.append(result)

            # Print immediate status
            status_emoji = {
                "MATCH": "✅",
                "CLOSE_MATCH": "⚠️",
                "MISMATCH": "❌",
                "API_ERROR": "🔴",
                "CALCULATOR_ERROR": "💥"
            }
            print(f"Status: {status_emoji.get(result.match_status, '❓')} {result.match_status}")

            if result.calculator_error:
                print(f"Calculator Error: {result.calculator_error}")
            if result.api_error:
                print(f"API Error: {result.api_error}")

        # Generate summary report
        self._generate_report(results, output_file)
        return results

    def _generate_report(self, results: List[ComparisonResult], output_file: str = None):
        """Generate comparison report"""
        print("\n" + "="*80)
        print("COMPARISON TEST RESULTS SUMMARY")
        print("="*80)

        # Count by status
        status_counts = {}
        for result in results:
            status_counts[result.match_status] = status_counts.get(result.match_status, 0) + 1

        print(f"Total Tests: {len(results)}")
        for status, count in status_counts.items():
            percentage = (count / len(results)) * 100
            print(f"{status}: {count} ({percentage:.1f}%)")

        # Detailed results
        print("\nDETAILED RESULTS:")
        print("-"*80)

        for result in results:
            print(f"\n📋 Sidecar Code: {result.test_case.sidecar_code}")
            print(f"   Status: {result.match_status}")

            if result.calculator_error:
                print(f"   Calculator Error: {result.calculator_error}")
            elif result.api_error:
                print(f"   API Error: {result.api_error}")
            elif result.differences:
                print("   Key Differences:")
                for field, diff in result.differences.items():
                    if diff['percent_difference'] > 1.0:  # Only show significant differences
                        print(f"     {field}: Calculator=${diff['calculator']:.2f}, "
                              f"API=${diff['api']:.2f} ({diff['percent_difference']:.1f}% diff)")

                # Show calculator results summary
                if result.calculator_result:
                    calc = result.calculator_result
                    print(f"   Calculator Results:")
                    print(f"     Facility Benefit: ${calc.facility_benefit_amount:.2f}")
                    print(f"     Non-Facility Benefit: ${calc.non_facility_benefit_amount:.2f}")
                    print(f"     RX Benefit: ${calc.rx_benefit_amount:.2f}")
                    print(f"     Rating Area: {calc.rating_area}")
                    print(f"     Provider Override Used: {'Yes' if calc.has_provider_override else 'No'}")

        # Save to CSV if requested
        if output_file:
            self._save_results_to_csv(results, output_file)
            print(f"\n💾 Detailed results saved to: {output_file}")

    def _save_results_to_csv(self, results: List[ComparisonResult], output_file: str):
        """Save results to CSV file"""
        rows = []
        for result in results:
            row = {
                'sidecar_code': result.test_case.sidecar_code,
                'insurance_filing_uuid': result.test_case.insurance_filing_uuid,
                'zipcode': result.test_case.zipcode,
                'member_uuid': result.test_case.member_uuid,
                'quantity': result.test_case.quantity,
                'match_status': result.match_status,
                'api_error': result.api_error or '',
                'calculator_error': result.calculator_error or ''
            }

            # Add calculator results
            if result.calculator_result:
                calc = result.calculator_result
                row.update({
                    'calc_facility_benefit_amount': calc.facility_benefit_amount,
                    'calc_non_facility_benefit_amount': calc.non_facility_benefit_amount,
                    'calc_rx_benefit_amount': calc.rx_benefit_amount,
                    'calc_facility_should_cost': calc.facility_should_cost,
                    'calc_non_facility_should_cost': calc.non_facility_should_cost,
                    'calc_rating_area': calc.rating_area,
                    'calc_has_provider_override': calc.has_provider_override,
                    'calc_has_coverage_override': calc.has_coverage_override,
                    'calc_provider_area_factor': calc.provider_area_factor,
                    'calc_coverage_area_factor': calc.coverage_area_factor,
                    'calc_is_prescription': calc.is_prescription
                })

            # Add API results if available
            if result.api_result:
                api = result.api_result
                row.update({
                    'api_facility_benefit_amount': api.facility_benefit_amount,
                    'api_non_facility_benefit_amount': api.non_facility_benefit_amount,
                    'api_rx_benefit_amount': api.rx_benefit_amount,
                    'api_facility_should_cost': api.facility_should_cost,
                    'api_non_facility_should_cost': api.non_facility_should_cost,
                    'api_provider_price': api.provider_price,
                    'api_estimated_member_responsibility': api.estimated_member_responsibility,
                    'api_earned_benefit': api.earned_benefit,
                    'api_category_slug': api.category_slug,
                    'api_selected_ndc': api.selected_ndc
                })

            # Add differences
            for field, diff in result.differences.items():
                row[f'diff_{field}_percent'] = diff['percent_difference']
                row[f'diff_{field}_absolute'] = diff['difference']

            rows.append(row)

        df = pd.DataFrame(rows)
        df.to_csv(output_file, index=False)

    def close(self):
        """Clean up resources"""
        if hasattr(self, 'benefit_calculator'):
            self.benefit_calculator.close_connection()

def create_sample_csv():
    """Create a sample test cases CSV file"""
    sample_data = [
        {
            'sidecar_code': '90834',
            'insurance_filing_uuid': 'gfi_ga_202507',
            'zipcode': '30309',
            'member_uuid': 'mem_yTXoyxJwWcsguSGrWFj44SwjIzUZ1r',
            'quantity': 1.0,
            'search_radius': 8
        },
        {
            'sidecar_code': 'J3420',
            'insurance_filing_uuid': 'gfi_ga_202507',
            'zipcode': '44870',
            'member_uuid': 'mem_yTXoyxJwWcsguSGrWFj44SwjIzUZ1r',
            'quantity': 1.0,
            'search_radius': 8
        },
        {
            'sidecar_code': '99214',
            'insurance_filing_uuid': 'gfi_ga_202507',
            'zipcode': '10001',
            'member_uuid': 'mem_yTXoyxJwWcsguSGrWFj44SwjIzUZ1r',
            'quantity': 1.0,
            'search_radius': 8
        }
    ]

    df = pd.DataFrame(sample_data)
    df.to_csv('sample_test_cases.csv', index=False)
    print("✅ Created sample_test_cases.csv")

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python compare_api_test.py <csv_file> [output_file]")
        print("Or: python compare_api_test.py --create-sample")
        print("\nThe CSV file should contain columns:")
        print("  - sidecar_code")
        print("  - insurance_filing_uuid")
        print("  - zipcode")
        print("  - member_uuid (optional - will use memberUuid from login if not provided)")
        print("  - quantity (optional, defaults to 1.0)")
        print("  - search_radius (optional, defaults to 8)")
        sys.exit(1)

    if sys.argv[1] == '--create-sample':
        create_sample_csv()
        return

    csv_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'comparison_results.csv'

    comparator = APIComparator()
    try:
        comparator.run_comparison_tests(csv_file, output_file)
    finally:
        comparator.close()

if __name__ == "__main__":
    main()