#!/usr/bin/env python3
"""
Enhanced Benefit Calculator - Implementing Java Business Logic
This version attempts to match the sophisticated logic from CareServiceBenefitCalculatorService.java
STANDALONE VERSION - No external imports needed
"""

import snowflake.connector
import json
import logging
import boto3
import os
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class EnhancedBenefitResult:
    """Enhanced benefit calculation result matching Java CareServiceBenefit"""
    # Input parameters
    sidecar_code: str
    insurance_filing_uuid: str
    zipcode: str
    quantity: float

    # Basic care info
    care_category: str
    care_uuid: str
    rating_area: str

    # Area factors (matching Java multiple factors)
    provider_area_factor: float
    provider_msa_factor: float
    coverage_area_factor: float

    # Should costs (matching Java structure)
    unit_should_cost: float
    should_cost: float  # marketRate in Java
    rx_should_cost: float
    facility_should_cost: float
    non_facility_should_cost: float
    facility_add_on_should_cost: float
    non_facility_add_on_should_cost: float

    # Benefit amounts (matching Java structure)
    facility_benefit_amount: float
    non_facility_benefit_amount: float
    facility_add_on_benefit_amount: float
    non_facility_add_on_benefit_amount: float
    rx_benefit_amount: float

    # Business logic indicators
    has_provider_override: bool
    has_coverage_override: bool
    is_prescription: bool
    is_facility_location: bool
    is_covered_by_maternity_care: bool
    is_care_calculation: bool  # vs expense calculation
    prescriptions_covered: bool

class EnhancedBenefitCalculator:
    """
    Enhanced benefit calculator implementing Java CareServiceBenefitCalculatorService logic
    STANDALONE VERSION - No dependencies on other calculator files
    """

    def __init__(self, aws_region: str = None):
        # Set up AWS region
        self.aws_region = aws_region or os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1'
        os.environ['AWS_DEFAULT_REGION'] = self.aws_region

        self.secrets_client = boto3.client('secretsmanager', region_name=self.aws_region)
        self.snowflake_config = self._get_snowflake_credentials()
        self.connection = None

    def _get_snowflake_credentials(self) -> Dict[str, str]:
        """Get Snowflake credentials from AWS Secrets Manager"""
        try:
            secret_response = self.secrets_client.get_secret_value(
                SecretId='sidecar-data-snowflake-etl-svc-account'
            )
            credentials = json.loads(secret_response['SecretString'])
            logger.info("Successfully retrieved Snowflake credentials")
            return credentials
        except Exception as e:
            logger.error(f"Failed to retrieve Snowflake credentials: {str(e)}")
            raise

    def _get_connection(self):
        """Create Snowflake connection"""
        if self.connection is None:
            self.connection = snowflake.connector.connect(
                user=self.snowflake_config['user'],
                password=self.snowflake_config['password'],
                account=self.snowflake_config['account'],
                warehouse=self.snowflake_config.get('warehouse', 'COMPUTE_WH'),
                database='FIVETRAN',
                schema='MYSQL_CARE_SIDECARHEALTH_CARE_DB',
                role=self.snowflake_config.get('role', 'SYSADMIN')
            )
        return self.connection

    def _round_double(self, value: float) -> float:
        """Round currency values to 2 decimal places (matching Java MathUtils.roundDouble)"""
        if value is None:
            return 0.0
        return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    def _get_rating_area_and_factors(self, zipcode: str, insurance_filing_uuid: str) -> Tuple[str, float, float, float]:
        """Get rating area and all area factors (provider, MSA, coverage)"""
        query = """
        SELECT 
            zcra.RATING_AREA,
            COALESCE(raf.MEDICAL_AREA_FACTOR, 1.0) as provider_area_factor,
            COALESCE(raf.MEDICAL_AREA_FACTOR, 1.0) as provider_msa_factor,  -- Assuming same as medical for now
            COALESCE(raf.MEDICAL_AREA_FACTOR, 1.0) as medical_area_factor,
            COALESCE(raf.RX_AREA_FACTOR, 1.0) as rx_area_factor
        FROM ZIP_CODE_RATING_AREA zcra
        LEFT JOIN RATING_AREA_FACTOR raf 
            ON zcra.RATING_AREA = raf.RATING_AREA 
            AND raf.INSURANCE_FILING = %s
        WHERE zcra.ZIP_CODE = %s
        LIMIT 1
        """

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(query, (insurance_filing_uuid, zipcode))
            result = cursor.fetchone()
            if result:
                return result[0], result[1], result[2], result[3], result[4]  # rating_area, provider_area_factor, provider_msa_factor, medical_area_factor, rx_area_factor
            else:
                logger.warning(f"No rating area found for zipcode: {zipcode}, using defaults")
                return "UNKNOWN", 1.0, 1.0, 1.0, 1.0
        finally:
            cursor.close()
    
    def _get_applicable_coverage_area_factor(self, category_slug: str, medical_area_factor: float, rx_area_factor: float) -> float:
        """Get applicable coverage area factor based on category - matching Java logic"""
        # Java: return CareType.PRESCRIPTIONS.getType().equals(selectedCategorySlug) ? 1d : ratingAreaFactor.getMedicalAreaFactor()
        if category_slug == "prescriptions":
            return 1.0
        else:
            return medical_area_factor

    def _get_comprehensive_care_data(self, sidecar_code: str, insurance_filing_uuid: str, rating_area: str) -> Dict:
        """Get comprehensive care data including both provider and coverage overrides"""

        # Base query for care info and rates
        base_query = """
        SELECT 
            cri.ID as CARE_ID,
            cri.UUID as CARE_UUID,
            cri.SIDECAR_CODE,
            cri.CATEGORY,
            cri.CATEGORY_SLUG,
            cri.IS_DRUG_COVERAGE_REQUIRED,
            
            -- Base rates
            cfr.FACILITY_SHOULD_COST,
            cfr.NON_FACILITY_SHOULD_COST,
            cfr.FACILITY_RATE,
            cfr.NON_FACILITY_RATE,
            cfr.ADD_ON_SHOULD_COST,
            cfr.ADD_ON_RATE,
            cfr.AVERAGE_UNIT_PRICE,
            cfr.UNIT_SHOULD_COST
            
        FROM CARE_REIMBURSEMENT_INFO cri
        INNER JOIN CARE_REIMBURSEMENT_FILING_RATE cfr 
            ON cri.ID = cfr.CARE_REIMBURSEMENT_INFO_ID
            AND cfr.INSURANCE_FILING_UUID = %s
            AND  cfr.ACTIVE = 'T'
            AND
            cri.IS_ACTIVE = 'T'
        WHERE cri.SIDECAR_CODE = %s
        LIMIT 1
        """

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Get base data
            logger.info(f"Executing query with insurance_filing_uuid: '{insurance_filing_uuid}', sidecar_code: '{sidecar_code}'")
            cursor.execute(base_query, (insurance_filing_uuid, sidecar_code))
            base_result = cursor.fetchone()

            if not base_result:
                logger.error(f"Sidecar code {sidecar_code} is not covered by insurance filing: {insurance_filing_uuid}")
                raise ValueError(f"Sidecar code {sidecar_code} is not covered by insurance filing: {insurance_filing_uuid}")

            base_columns = [desc[0] for desc in cursor.description]
            base_data = dict(zip(base_columns, base_result))

            # Get override data (simulating both provider and coverage overrides)
            override_data = {}
            if rating_area and rating_area != "UNKNOWN":
                override_query = """
                SELECT 
                    -- Provider override fields (for should costs)
                    FACILITY_SHOULD_COST as PROVIDER_FACILITY_SHOULD_COST,
                    NON_FACILITY_SHOULD_COST as PROVIDER_NON_FACILITY_SHOULD_COST,
                    ADD_ON_SHOULD_COST as PROVIDER_ADD_ON_SHOULD_COST,
                    UNIT_SHOULD_COST as PROVIDER_UNIT_SHOULD_COST,
                    
                    -- Coverage override fields (for benefit amounts)
                    FACILITY_RATE as COVERAGE_FACILITY_RATE,
                    NON_FACILITY_RATE as COVERAGE_NON_FACILITY_RATE,
                    ADD_ON_RATE as COVERAGE_ADD_ON_RATE,
                    AVERAGE_UNIT_PRICE as COVERAGE_AVERAGE_UNIT_PRICE
                FROM CARE_REIMBURSEMENT_FILING_RATE_OVERRIDE
                WHERE SIDECAR_CODE = %s
                AND INSURANCE_FILING_UUID = %s
                AND RATING_AREA = %s
                AND (ACTIVE IS NULL OR ACTIVE = 'T')
                LIMIT 1
                """

                cursor.execute(override_query, (sidecar_code, insurance_filing_uuid, rating_area))
                override_result = cursor.fetchone()

                if override_result:
                    override_columns = [desc[0] for desc in cursor.description]
                    override_data = dict(zip(override_columns, override_result))

            # Combine all data
            combined_data = {**base_data, **override_data}
            combined_data['has_provider_override'] = any(
                override_data.get(f'{field}') is not None and override_data.get(f'{field}') > 0
                for field in ['PROVIDER_FACILITY_SHOULD_COST', 'PROVIDER_NON_FACILITY_SHOULD_COST', 'PROVIDER_ADD_ON_SHOULD_COST', 'PROVIDER_UNIT_SHOULD_COST']
            )
            combined_data['has_coverage_override'] = any(
                override_data.get(f'{field}') is not None and override_data.get(f'{field}') > 0
                for field in ['COVERAGE_FACILITY_RATE', 'COVERAGE_NON_FACILITY_RATE', 'COVERAGE_ADD_ON_RATE', 'COVERAGE_AVERAGE_UNIT_PRICE']
            )

            return combined_data

        finally:
            cursor.close()

    def _get_effective_value_with_filter(self, base_value: float, override_value: float) -> float:
        """Get effective value with Java-like filtering (override > 0 takes precedence)"""
        if override_value is not None and override_value > 0:
            return float(override_value)
        return float(base_value) if base_value is not None else 0.0

    def _calculate_should_cost_java_style(self, base_should_cost: float, override_should_cost: Optional[float],
                                          add_on_should_cost: float, add_on_override: Optional[float],
                                          units: float, provider_area_factor: float, provider_msa_factor: float,
                                          ignore_rating_area_factor: bool) -> float:
        """Calculate should cost using Java-style logic with Optional pattern"""

        # Get effective values (Java Optional.map().filter().orElse() pattern)
        effective_should_cost = self._get_effective_value_with_filter(base_should_cost, override_should_cost)
        effective_add_on = self._get_effective_value_with_filter(add_on_should_cost, add_on_override)

        # Calculate total cost
        total_cost = (effective_should_cost * units) + effective_add_on

        # Apply area factors (matching Java logic)
        if ignore_rating_area_factor:
            return total_cost
        else:
            # Use MSA factor for final calculation (as seen in Java)
            return total_cost * provider_msa_factor

    def _calculate_benefit_amount_java_style(self, base_rate: float, override_rate: Optional[float],
                                             add_on_rate: float, add_on_override: Optional[float],
                                             units: float, coverage_area_factor: float,
                                             ignore_rating_area_factor: bool,
                                             is_covered_by_maternity_care: bool,
                                             is_care_calculation: bool) -> float:
        """Calculate benefit amount using Java-style logic"""

        # Java: return 0 if care calculation and not covered by maternity care
        if is_care_calculation and not is_covered_by_maternity_care:
            return 0.0

        # Get effective values
        effective_rate = self._get_effective_value_with_filter(base_rate, override_rate)
        effective_add_on = self._get_effective_value_with_filter(add_on_rate, add_on_override)

        # Calculate benefit
        total_benefit = (effective_rate * units) + effective_add_on

        # Apply area factors
        if ignore_rating_area_factor:
            return total_benefit
        else:
            return total_benefit * coverage_area_factor

    def calculate_benefit(self, sidecar_code: str, insurance_filing_uuid: str,
                          zipcode: str, quantity: float = 1.0,
                          is_facility_location: bool = True,
                          ignore_rating_area_factor: bool = False,
                          is_care_calculation: bool = True,
                          prescriptions_covered: bool = True) -> EnhancedBenefitResult:
        """
        Enhanced benefit calculation implementing Java business logic

        Args:
            sidecar_code: Sidecar procedure/drug code
            insurance_filing_uuid: Insurance filing identifier
            zipcode: ZIP code for rating area lookup
            quantity: Quantity/units (default 1.0)
            is_facility_location: Whether this is a facility location
            ignore_rating_area_factor: Whether to ignore rating area factors
            is_care_calculation: True for care, False for expense calculation
            prescriptions_covered: Whether prescriptions are covered
        """
        print(f"\n{'='*80}")
        print(f"🧮 ENHANCED BENEFIT CALCULATOR - DETAILED DEBUG LOG")
        print(f"{'='*80}")
        
        print(f"📋 INPUT PARAMETERS:")
        print(f"  sidecar_code: {sidecar_code}")
        print(f"  insurance_filing_uuid: {insurance_filing_uuid}")
        print(f"  zipcode: {zipcode}")
        print(f"  quantity: {quantity}")
        print(f"  is_facility_location: {is_facility_location}")
        print(f"  ignore_rating_area_factor: {ignore_rating_area_factor}")
        print(f"  is_care_calculation: {is_care_calculation}")
        print(f"  prescriptions_covered: {prescriptions_covered}")
        
        logger.info(f"Enhanced calculation for sidecar_code: {sidecar_code}")

        # Get rating area and all area factors
        rating_area, provider_area_factor, provider_msa_factor, medical_area_factor, rx_area_factor = \
            self._get_rating_area_and_factors(zipcode, insurance_filing_uuid)

        # Get comprehensive care data first to determine category
        care_data = self._get_comprehensive_care_data(sidecar_code, insurance_filing_uuid, rating_area)
        
        # Apply Java-style coverage area factor logic based on category
        category_slug = care_data.get('CATEGORY_SLUG', '')
        coverage_area_factor = self._get_applicable_coverage_area_factor(category_slug, medical_area_factor, rx_area_factor)

        print(f"\n🗺️ RATING AREA & FACTORS:")
        print(f"  rating_area: {rating_area}")
        print(f"  provider_area_factor: {provider_area_factor}")
        print(f"  provider_msa_factor: {provider_msa_factor}")
        print(f"  medical_area_factor: {medical_area_factor}")
        print(f"  rx_area_factor: {rx_area_factor}")
        print(f"  category_slug: {category_slug}")
        print(f"  coverage_area_factor (Java logic applied): {coverage_area_factor}")
        
        print(f"\n📊 RAW DATABASE VALUES:")
        for key, value in care_data.items():
            if key.startswith(('FACILITY', 'NON_FACILITY', 'ADD_ON', 'UNIT', 'AVERAGE', 'PROVIDER', 'COVERAGE')):
                print(f"  {key}: {value}")
        
        print(f"\n🏥 CARE DATA SUMMARY:")
        print(f"  CARE_UUID: {care_data.get('CARE_UUID', 'N/A')}")
        print(f"  CATEGORY: {care_data.get('CATEGORY', 'N/A')}")
        print(f"  CATEGORY_SLUG: {care_data.get('CATEGORY_SLUG', 'N/A')}")
        print(f"  IS_DRUG_COVERAGE_REQUIRED: {care_data.get('IS_DRUG_COVERAGE_REQUIRED', 'N/A')}")
        print(f"  has_provider_override: {care_data.get('has_provider_override', False)}")
        print(f"  has_coverage_override: {care_data.get('has_coverage_override', False)}")

        # Business logic determinations
        is_prescription = (care_data.get('AVERAGE_UNIT_PRICE', 0) > 0 or
                           care_data.get('COVERAGE_AVERAGE_UNIT_PRICE', 0) > 0)
        is_drug_coverage_required = care_data.get('IS_DRUG_COVERAGE_REQUIRED') == 'T'
        is_covered_by_maternity_care = True  # TODO: Implement proper maternity care logic

        print(f"\n🔍 BUSINESS LOGIC DETERMINATIONS:")
        print(f"  is_prescription: {is_prescription}")
        print(f"  is_drug_coverage_required: {is_drug_coverage_required}")
        print(f"  is_covered_by_maternity_care: {is_covered_by_maternity_care}")

        # Unit should cost calculation (Java style)
        unit_should_cost_base = care_data.get('UNIT_SHOULD_COST', 0)
        unit_should_cost_override = care_data.get('PROVIDER_UNIT_SHOULD_COST')
        unit_should_cost = self._get_effective_value_with_filter(unit_should_cost_base, unit_should_cost_override)
        
        print(f"\n💲 UNIT SHOULD COST CALCULATION:")
        print(f"  base_value: {unit_should_cost_base}")
        print(f"  override_value: {unit_should_cost_override}")
        print(f"  effective_value: {unit_should_cost}")
        
        if not ignore_rating_area_factor:
            unit_should_cost_before_factor = unit_should_cost
            unit_should_cost *= provider_area_factor
            print(f"  after provider_area_factor ({provider_area_factor}): {unit_should_cost_before_factor} * {provider_area_factor} = {unit_should_cost}")
        else:
            print(f"  ignore_rating_area_factor=True, no factor applied")

        # Market rate calculation (for should_cost field)
        if is_facility_location:
            market_rate_base = care_data.get('FACILITY_SHOULD_COST', 0)
            market_rate_override = care_data.get('PROVIDER_FACILITY_SHOULD_COST')
            print(f"\n🏥 MARKET RATE (FACILITY):")
        else:
            market_rate_base = care_data.get('NON_FACILITY_SHOULD_COST', 0)
            market_rate_override = care_data.get('PROVIDER_NON_FACILITY_SHOULD_COST')
            print(f"\n🏥 MARKET RATE (NON-FACILITY):")

        print(f"  base_value: {market_rate_base}")
        print(f"  override_value: {market_rate_override}")
        
        market_rate = self._get_effective_value_with_filter(market_rate_base, market_rate_override)
        print(f"  effective_value: {market_rate}")
        
        if not ignore_rating_area_factor:
            market_rate_before_factor = market_rate
            market_rate *= provider_area_factor
            print(f"  after provider_area_factor ({provider_area_factor}): {market_rate_before_factor} * {provider_area_factor} = {market_rate}")
        else:
            print(f"  ignore_rating_area_factor=True, no factor applied")

        # Should costs calculation
        facility_should_cost = self._round_double(
            self._calculate_should_cost_java_style(
                care_data.get('FACILITY_SHOULD_COST', 0),
                care_data.get('PROVIDER_FACILITY_SHOULD_COST'),
                care_data.get('ADD_ON_SHOULD_COST', 0),
                care_data.get('PROVIDER_ADD_ON_SHOULD_COST'),
                quantity, provider_area_factor, provider_msa_factor, ignore_rating_area_factor
            )
        )

        non_facility_should_cost = self._round_double(
            self._calculate_should_cost_java_style(
                care_data.get('NON_FACILITY_SHOULD_COST', 0),
                care_data.get('PROVIDER_NON_FACILITY_SHOULD_COST'),
                care_data.get('ADD_ON_SHOULD_COST', 0),
                care_data.get('PROVIDER_ADD_ON_SHOULD_COST'),
                quantity, provider_area_factor, provider_msa_factor, ignore_rating_area_factor
            )
        )

        # Add-on should cost
        add_on_should_cost_base = self._get_effective_value_with_filter(
            care_data.get('ADD_ON_SHOULD_COST', 0),
            care_data.get('PROVIDER_ADD_ON_SHOULD_COST')
        )
        if not ignore_rating_area_factor:
            add_on_should_cost_base *= provider_area_factor

        # Average unit price (for RX calculations)
        average_unit_price = self._get_effective_value_with_filter(
            care_data.get('AVERAGE_UNIT_PRICE', 0),
            care_data.get('COVERAGE_AVERAGE_UNIT_PRICE')
        )
        
        print(f"\n💊 RX CALCULATION INPUTS:")
        print(f"  base_average_unit_price: {care_data.get('AVERAGE_UNIT_PRICE', 0)}")
        print(f"  override_average_unit_price: {care_data.get('COVERAGE_AVERAGE_UNIT_PRICE')}")
        print(f"  effective_average_unit_price: {average_unit_price}")
        print(f"  category_slug: {category_slug}")
        print(f"  coverage_area_factor_for_rx: {coverage_area_factor} ({'1.0 for prescriptions' if category_slug == 'prescriptions' else 'medical_area_factor for non-prescriptions'})")


        rx_benefit_amount = 0.0
        
        if is_care_calculation:
            # For CARE calculations: Optional chain with filters
            if prescriptions_covered or not is_drug_coverage_required:
                if average_unit_price > 0:
                    # Apply coverage_area_factor and quantity for total RX benefit
                    potential_rx_benefit = average_unit_price * coverage_area_factor * quantity
                    if potential_rx_benefit > 0:
                        rx_benefit_amount = potential_rx_benefit
                        print(f"\n💊 RX BENEFIT (CARE): average_unit_price({average_unit_price}) * coverage_area_factor({coverage_area_factor}) * quantity({quantity}) = {rx_benefit_amount}")
        else:
            # For EXPENSE calculations: Direct calculation with units
            rx_benefit_amount = average_unit_price * coverage_area_factor * quantity
            print(f"\n💊 RX BENEFIT (EXPENSE): average_unit_price({average_unit_price}) * coverage_area_factor({coverage_area_factor}) * quantity({quantity}) = {rx_benefit_amount}")

        # Benefit amounts calculation
        print(f"\n🎯 BENEFIT AMOUNT CALCULATIONS:")
        
        print(f"\n  FACILITY BENEFIT:")
        facility_base_rate = care_data.get('FACILITY_RATE', 0)
        facility_override_rate = care_data.get('COVERAGE_FACILITY_RATE')
        facility_add_on_base = care_data.get('ADD_ON_RATE', 0)
        facility_add_on_override = care_data.get('COVERAGE_ADD_ON_RATE')
        
        print(f"    base_rate: {facility_base_rate}")
        print(f"    override_rate: {facility_override_rate}")
        print(f"    add_on_base: {facility_add_on_base}")
        print(f"    add_on_override: {facility_add_on_override}")
        print(f"    quantity: {quantity}")
        print(f"    coverage_area_factor: {coverage_area_factor}")
        print(f"    ignore_rating_area_factor: {ignore_rating_area_factor}")
        print(f"    is_covered_by_maternity_care: {is_covered_by_maternity_care}")
        print(f"    is_care_calculation: {is_care_calculation}")
        
        facility_benefit_amount_raw = self._calculate_benefit_amount_java_style(
            facility_base_rate, facility_override_rate,
            facility_add_on_base, facility_add_on_override,
            quantity, coverage_area_factor, ignore_rating_area_factor,
            is_covered_by_maternity_care, is_care_calculation
        )
        facility_benefit_amount = self._round_double(facility_benefit_amount_raw)
        print(f"    raw_result: {facility_benefit_amount_raw}")
        print(f"    rounded_result: {facility_benefit_amount}")

        print(f"\n  NON-FACILITY BENEFIT:")
        non_facility_base_rate = care_data.get('NON_FACILITY_RATE', 0)
        non_facility_override_rate = care_data.get('COVERAGE_NON_FACILITY_RATE')
        
        print(f"    base_rate: {non_facility_base_rate}")
        print(f"    override_rate: {non_facility_override_rate}")
        print(f"    add_on_base: {facility_add_on_base}")
        print(f"    add_on_override: {facility_add_on_override}")
        print(f"    quantity: {quantity}")
        print(f"    coverage_area_factor: {coverage_area_factor}")
        print(f"    ignore_rating_area_factor: {ignore_rating_area_factor}")
        print(f"    is_covered_by_maternity_care: {is_covered_by_maternity_care}")
        print(f"    is_care_calculation: {is_care_calculation}")
        
        non_facility_benefit_amount_raw = self._calculate_benefit_amount_java_style(
            non_facility_base_rate, non_facility_override_rate,
            facility_add_on_base, facility_add_on_override,
            quantity, coverage_area_factor, ignore_rating_area_factor,
            is_covered_by_maternity_care, is_care_calculation
        )
        non_facility_benefit_amount = self._round_double(non_facility_benefit_amount_raw)
        print(f"    raw_result: {non_facility_benefit_amount_raw}")
        print(f"    rounded_result: {non_facility_benefit_amount}")

        # Add-on benefit amount (Java: 0 if not covered by maternity care)
        raw_add_on_benefit = self._get_effective_value_with_filter(
            care_data.get('ADD_ON_RATE', 0),
            care_data.get('COVERAGE_ADD_ON_RATE')
        )
        if not ignore_rating_area_factor:
            raw_add_on_benefit *= coverage_area_factor

        add_on_benefit_amount = 0.0 if not is_covered_by_maternity_care else raw_add_on_benefit

        print(f"\n📋 FINAL RESULTS SUMMARY:")
        print(f"  facility_should_cost: ${facility_should_cost:.2f}")
        print(f"  non_facility_should_cost: ${non_facility_should_cost:.2f}")
        print(f"  facility_benefit_amount: ${facility_benefit_amount:.2f}")
        print(f"  non_facility_benefit_amount: ${non_facility_benefit_amount:.2f}")
        print(f"  rx_benefit_amount: ${self._round_double(rx_benefit_amount):.2f}")
        print(f"{'='*80}")

        return EnhancedBenefitResult(
            # Input parameters
            sidecar_code=sidecar_code,
            insurance_filing_uuid=insurance_filing_uuid,
            zipcode=zipcode,
            quantity=quantity,

            # Basic care info
            care_category=care_data.get('CATEGORY', ''),
            care_uuid=care_data.get('CARE_UUID', ''),  # Snowflake returns uppercase column names
            rating_area=rating_area,

            # Area factors
            provider_area_factor=provider_area_factor,
            provider_msa_factor=provider_msa_factor,
            coverage_area_factor=coverage_area_factor,

            # Should costs
            unit_should_cost=self._round_double(unit_should_cost),
            should_cost=self._round_double(market_rate),
            rx_should_cost=self._round_double(unit_should_cost * quantity),
            facility_should_cost=facility_should_cost,
            non_facility_should_cost=non_facility_should_cost,
            facility_add_on_should_cost=self._round_double(add_on_should_cost_base),
            non_facility_add_on_should_cost=self._round_double(add_on_should_cost_base),

            # Benefit amounts
            facility_benefit_amount=facility_benefit_amount,
            non_facility_benefit_amount=non_facility_benefit_amount,
            facility_add_on_benefit_amount=self._round_double(add_on_benefit_amount),
            non_facility_add_on_benefit_amount=self._round_double(add_on_benefit_amount),
            rx_benefit_amount=self._round_double(rx_benefit_amount),

            # Business logic indicators
            has_provider_override=care_data.get('has_provider_override', False),
            has_coverage_override=care_data.get('has_coverage_override', False),
            is_prescription=is_prescription,
            is_facility_location=is_facility_location,
            is_covered_by_maternity_care=is_covered_by_maternity_care,
            is_care_calculation=is_care_calculation,
            prescriptions_covered=prescriptions_covered
        )

    def close_connection(self):
        """Close Snowflake connection"""
        if self.connection and not self.connection.is_closed():
            self.connection.close()

def print_enhanced_result(result: EnhancedBenefitResult):
    """Pretty print enhanced benefit calculation results"""
    print("\n" + "="*70)
    print("ENHANCED SIDECAR BENEFIT CALCULATION RESULTS")
    print("="*70)

    print(f"Sidecar Code: {result.sidecar_code}")
    print(f"Care Category: {result.care_category}")
    print(f"Insurance Filing: {result.insurance_filing_uuid}")
    print(f"ZIP Code: {result.zipcode}")
    print(f"Rating Area: {result.rating_area}")
    print(f"Quantity: {result.quantity}")

    print(f"\n📋 Business Logic Status:")
    print(f"  Provider Override Used: {'Yes' if result.has_provider_override else 'No'}")
    print(f"  Coverage Override Used: {'Yes' if result.has_coverage_override else 'No'}")
    print(f"  Is Prescription: {'Yes' if result.is_prescription else 'No'}")
    print(f"  Is Facility Location: {'Yes' if result.is_facility_location else 'No'}")
    print(f"  Covered by Maternity Care: {'Yes' if result.is_covered_by_maternity_care else 'No'}")
    print(f"  Is Care Calculation: {'Yes' if result.is_care_calculation else 'No'}")
    print(f"  Prescriptions Covered: {'Yes' if result.prescriptions_covered else 'No'}")

    print(f"\n🏭 Area Factors (Java Style):")
    print(f"  Provider Area Factor: {result.provider_area_factor:.4f}")
    print(f"  Provider MSA Factor: {result.provider_msa_factor:.4f}")
    print(f"  Coverage Area Factor: {result.coverage_area_factor:.4f}")

    print(f"\n💰 Should Costs:")
    print(f"  Unit Should Cost: ${result.unit_should_cost:.2f}")
    print(f"  Should Cost (Market Rate): ${result.should_cost:.2f}")
    print(f"  RX Should Cost: ${result.rx_should_cost:.2f}")
    print(f"  Facility Should Cost: ${result.facility_should_cost:.2f}")
    print(f"  Non-Facility Should Cost: ${result.non_facility_should_cost:.2f}")
    print(f"  Add-on Should Cost: ${result.facility_add_on_should_cost:.2f}")

    print(f"\n🎯 Benefit Amounts:")
    print(f"  Facility Benefit: ${result.facility_benefit_amount:.2f}")
    print(f"  Non-Facility Benefit: ${result.non_facility_benefit_amount:.2f}")
    print(f"  Add-on Benefit: ${result.facility_add_on_benefit_amount:.2f}")
    print(f"  RX Benefit: ${result.rx_benefit_amount:.2f}")

def main():
    """Example usage of enhanced calculator"""
    calculator = EnhancedBenefitCalculator()

    try:
        # Test with different scenarios
        print("🧮 Enhanced Java-Style Calculation Test")

        # Scenario 1: Facility location, care calculation
        result1 = calculator.calculate_benefit(
            sidecar_code='90834',
            insurance_filing_uuid='gfi_ga_202507',
            zipcode='30309',
            quantity=1.0,
            is_facility_location=True,
            is_care_calculation=True,
            prescriptions_covered=True
        )
        print_enhanced_result(result1)

        # Scenario 2: Non-facility location, expense calculation
        print("\n" + "="*70)
        print("SCENARIO 2: Non-Facility, Expense Calculation")
        result2 = calculator.calculate_benefit(
            sidecar_code='90834',
            insurance_filing_uuid='gfi_ga_202507',
            zipcode='30309',
            quantity=1.0,
            is_facility_location=False,
            is_care_calculation=False,  # Expense calculation
            prescriptions_covered=True
        )
        print_enhanced_result(result2)

    except Exception as e:
        logger.error(f"Enhanced calculation failed: {str(e)}")
        raise
    finally:
        calculator.close_connection()

if __name__ == "__main__":
    main()