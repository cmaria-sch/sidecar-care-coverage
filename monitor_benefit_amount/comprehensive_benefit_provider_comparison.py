#!/usr/bin/env python3
"""
Comprehensive Benefit vs Provider Price Comparison Script
=========================================================

This script performs a comprehensive comparison between benefit amounts calculated 
by the EnhancedBenefitCalculator and provider prices from Elasticsearch.

The script ensures state-specific matching:
- Each insurance filing is processed only against zip codes from the same state
- For example: gfi_oh_202507 is only compared against zip codes from zip_code_oh.csv

Process:
1. Read input CSV files (insurance fillings, medical codes, zip codes by state)
2. For each insurance filing:
   - Extract state from filing name (e.g., gfi_oh_202507 -> OH)
   - Load zip codes only for that state
   - For each combination of medical code and zipcode in that state:
     - Calculate benefit amount using EnhancedBenefitCalculator
     - Get provider prices from Elasticsearch
     - Compare benefit amount vs provider prices
3. Output results where provider price > benefit amount to database

Usage:
    python comprehensive_benefit_provider_comparison.py
"""

import pandas as pd
import json
import logging
import sys
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import traceback
import snowflake.connector
import uuid
import time
import functools

# Import our custom modules
from enhanced_benefit_calculator import EnhancedBenefitCalculator, EnhancedBenefitResult
from ProviderPriceInformation import ProviderPriceInformation

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def snowflake_retry_with_connection_refresh(max_retries: int = 3, backoff_factor: float = 2.0):
    """
    Decorator to retry Snowflake operations with connection refresh on failure.
    
    This handles IP access errors that are actually connection timeouts by:
    1. Detecting Snowflake connection errors (including misleading IP access errors)
    2. Refreshing connections by calling connection refresh methods
    3. Retrying the operation with exponential backoff
    
    Args:
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for exponential backoff delay
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(self, *args, **kwargs)
                    
                except Exception as e:
                    last_exception = e
                    error_str = str(e).lower()
                    
                    # Check if this is a Snowflake connection-related error
                    is_connection_error = any(keyword in error_str for keyword in [
                        'snowflake',
                        'connection',
                        'authentication', 
                        'timeout',
                        'network',
                        'ip/token',  # The specific IP access error that's actually a timeout
                        'is not allowed to access',
                        'socket',
                        'ssl',
                        'certificate'
                    ])
                    
                    if not is_connection_error:
                        # Not a connection error, don't retry
                        raise e
                    
                    if attempt == max_retries:
                        # Last attempt failed, give up
                        logger.error(f"🚨 FINAL RETRY FAILURE after {max_retries} attempts for {func.__name__}: {e}")
                        raise e
                    
                    # Log the retry attempt
                    retry_delay = backoff_factor ** attempt
                    logger.warning(f"🔄 RETRY {attempt + 1}/{max_retries} for {func.__name__} after connection error: {e}")
                    logger.warning(f"   Waiting {retry_delay:.1f}s before retry with connection refresh...")
                    
                    # Wait before retry
                    time.sleep(retry_delay)
                    
                    # Try to refresh connections
                    try:
                        logger.info(f"🔌 Refreshing Snowflake connections for retry {attempt + 1}")
                        self._refresh_connections()
                    except Exception as refresh_error:
                        logger.warning(f"⚠️ Connection refresh failed: {refresh_error}, will retry anyway")
                    
                    logger.info(f"🔄 Retrying {func.__name__} (attempt {attempt + 2}/{max_retries + 1})")
            
            # Should never reach here, but just in case
            raise last_exception
            
        return wrapper
    return decorator

@dataclass
class ComparisonResult:
    """Result of benefit vs provider price comparison"""
    sidecar_code: str
    npi: str
    insurance_filing_uuid: str
    zipcode: str
    state: str
    rating_area: str
    provider_price: float
    facility_benefit_amount: float
    non_facility_benefit_amount: float
    rx_benefit_amount: float
    provider_name: str = ""
    care_category: str = ""
    execution_id: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for CSV export"""
        return {
            'sidecar_code': self.sidecar_code,
            'npi': self.npi,
            'insurance_filing_uuid': self.insurance_filing_uuid,
            'zipcode': self.zipcode,
            'state': self.state,
            'rating_area': self.rating_area,
            'provider_price': self.provider_price,
            'facility_benefit_amount': self.facility_benefit_amount,
            'non_facility_benefit_amount': self.non_facility_benefit_amount,
            'rx_benefit_amount': self.rx_benefit_amount,
            'provider_name': self.provider_name,
            'care_category': self.care_category,
            'execution_id': self.execution_id
        }
    
    def to_snowflake_record(self) -> Dict:
        """Convert to dictionary for Snowflake database insert"""
        exceeds_facility = self.provider_price > self.facility_benefit_amount if self.facility_benefit_amount > 0 else False
        exceeds_non_facility = self.provider_price > self.non_facility_benefit_amount if self.non_facility_benefit_amount > 0 else False
        
        return {
            'EXECUTION_ID': self.execution_id,
            'SIDECAR_CODE': self.sidecar_code,
            'NPI': self.npi,
            'INSURANCE_FILING_UUID': self.insurance_filing_uuid,
            'ZIPCODE': self.zipcode,
            'STATE': self.state,
            'RATING_AREA': self.rating_area,
            'PROVIDER_PRICE': self.provider_price,
            'FACILITY_BENEFIT_AMOUNT': self.facility_benefit_amount,
            'NON_FACILITY_BENEFIT_AMOUNT': self.non_facility_benefit_amount,
            'RX_BENEFIT_AMOUNT': self.rx_benefit_amount,
            'PROVIDER_NAME': self.provider_name[:500] if self.provider_name else '',  # Truncate to fit VARCHAR(500)
            'CARE_CATEGORY': self.care_category[:100] if self.care_category else '',  # Truncate to fit VARCHAR(100)
            'EXCEEDS_FACILITY': exceeds_facility,
            'EXCEEDS_NON_FACILITY': exceeds_non_facility, 
            'PRICE_VS_FACILITY_DIFF': self.provider_price - self.facility_benefit_amount if exceeds_facility else 0,
            'PRICE_VS_NON_FACILITY_DIFF': self.provider_price - self.non_facility_benefit_amount if exceeds_non_facility else 0
        }

class ComprehensiveBenefitProviderComparison:
    """
    Main class for performing comprehensive benefit vs provider price comparison
    """
    
    def __init__(self, data_dir: str = "data", batch_size: int = 200):
        """
        Initialize the comparison system
        
        Args:
            data_dir: Directory containing input CSV files
            batch_size: Number of results to accumulate before writing to database
        """
        self.data_dir = data_dir
        self.batch_size = batch_size
        self.results_batch = []  # Current batch of results waiting to be written
        self.total_results_written = 0  # Running counter of total results written
        self.results_by_state = {
            'FL': [],
            'GA': [], 
            'OH': []
        }
        
        # Generate unique execution ID for this run
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]  # First 8 characters of UUID for brevity
        self.execution_id = f"COMP_{timestamp}_{unique_id}"
        logger.info(f"🆔 Generated execution ID: {self.execution_id}")
        logger.info(f"📅 Job started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Initialize components
        logger.info("Initializing EnhancedBenefitCalculator...")
        self.benefit_calculator = EnhancedBenefitCalculator()
        
        logger.info("Initializing ProviderPriceInformation...")
        self.provider_service = ProviderPriceInformation(
            es_endpoint="https://vpc-sidecar-api-doctor-gxax5tlshqikfefzncefjs4ubi.us-east-1.es.amazonaws.com",
            region="us-east-1",
            use_aws_auth=False,
            max_results=100,
            enable_snowflake_filtering=True
        )
        
        # Initialize Snowflake connection for result storage
        self.results_connection = None
        self.table_has_execution_id = False  # Will be set during initialization
        self._initialize_results_database()
        
        # Initialize caches to reduce database calls
        self._rating_area_cache = {}
        self._radius_cache = {}
        self._zipcode_coordinates_cache = {}
        
        # Initialize persistent database cursors to avoid creating/closing cursors for every query
        self._main_cursor = None
        self._doctor_cursor = None
        self._results_cursor = None
        self._initialize_persistent_cursors()
        
        logger.info("Connection optimization: Caching enabled for rating areas, radius, and coordinates")
        logger.info("Connection optimization: Persistent cursors initialized to avoid cursor overhead")
        logger.info("🔄 Retry mechanism: Snowflake connection retry with refresh enabled")
        
        # Load input data
        self.insurance_fillings = self._load_insurance_fillings()
        self.medical_codes = self._load_medical_codes()
        self.zip_codes_by_state = self._load_zip_codes_by_state()
        
        logger.info(f"Loaded {len(self.insurance_fillings)} insurance fillings")
        logger.info(f"Loaded {len(self.medical_codes)} medical codes")
        logger.info(f"Loaded zip codes: FL={len(self.zip_codes_by_state['FL'])}, GA={len(self.zip_codes_by_state['GA'])}, OH={len(self.zip_codes_by_state['OH'])}")
        
        logger.info(f"🎯 Database Integration: Results will be written to WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST")
        logger.info(f"🆔 Execution ID: {self.execution_id}")
        logger.info(f"📦 Batch Size: {self.batch_size} records (results saved in batches for efficiency)")
        logger.info(f"📊 Query your results: SELECT * FROM WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST WHERE EXECUTION_ID = '{self.execution_id}';")
        logger.info(f"🔍 Count results: SELECT COUNT(*) FROM WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST WHERE EXECUTION_ID = '{self.execution_id}';")
        logger.info(f"📈 Summary by state: SELECT STATE, COUNT(*) FROM WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST WHERE EXECUTION_ID = '{self.execution_id}' GROUP BY STATE;")

    def _load_insurance_fillings(self) -> List[str]:
        """Load insurance filing UUIDs from CSV"""
        try:
            df = pd.read_csv(os.path.join(self.data_dir, "insurance_fillings.csv"), header=None)
            fillings = df.iloc[:, 0].tolist()
            logger.info(f"Loaded insurance fillings: {fillings}")
            return fillings
        except Exception as e:
            logger.error(f"Failed to load insurance fillings: {e}")
            raise

    def _load_medical_codes(self) -> List[str]:
        """Load medical codes from CSV"""
        try:
            df = pd.read_csv(os.path.join(self.data_dir, "medical_codes_non_rx.csv"))
            codes = df['sidecar_code'].tolist()
            logger.info(f"Loaded {len(codes)} medical codes")
            return codes
        except Exception as e:
            logger.error(f"Failed to load medical codes: {e}")
            raise

    def _load_zip_codes_by_state(self) -> Dict[str, List[str]]:
        """Load zip codes grouped by state"""
        zip_codes_by_state = {}
        
        states = ['FL', 'GA', 'OH']
        for state in states:
            try:
                df = pd.read_csv(os.path.join(self.data_dir, f"zip_code_{state.lower()}.csv"))
                zip_codes = df['zip'].astype(str).tolist()
                zip_codes_by_state[state] = zip_codes
                logger.info(f"Loaded {len(zip_codes)} zip codes for {state}")
            except Exception as e:
                logger.error(f"Failed to load zip codes for {state}: {e}")
                zip_codes_by_state[state] = []
        
        return zip_codes_by_state

    @snowflake_retry_with_connection_refresh(max_retries=3, backoff_factor=2.0)
    def _initialize_results_database(self):
        """Initialize Snowflake connection for writing results - ONLY to WORKSPACE.SCRATCH"""
        try:
            # Get credentials from the benefit calculator (which gets them from AWS Secrets Manager)
            # This ensures we use the same credentials that work for other components
            base_credentials = self.benefit_calculator.snowflake_config
            
            # SECURITY: Override database and schema to ensure we ONLY write to WORKSPACE.SCRATCH
            results_conn_params = {
                'user': base_credentials['user'],
                'password': base_credentials['password'],
                'account': base_credentials['account'],
                'warehouse': base_credentials.get('warehouse', 'COMPUTE_WH'),
                'database': 'WORKSPACE',  # HARDCODED - Never write anywhere else!
                'schema': 'SCRATCH',      # HARDCODED - Never write anywhere else!
                'role': base_credentials.get('role', 'SYSADMIN')
            }
            
            logger.info("🔒 SECURITY: Connecting ONLY to WORKSPACE.SCRATCH for results")
            logger.info(f"   Database: {results_conn_params['database']}")
            logger.info(f"   Schema: {results_conn_params['schema']}")
            logger.info(f"   User: {results_conn_params['user']}")
            logger.info(f"   Account: {results_conn_params['account']}")
            
            self.results_connection = snowflake.connector.connect(**results_conn_params)
            logger.info("✅ Results database connection initialized (WORKSPACE.SCRATCH only)")
            
            # Test the connection by checking the target table structure
            cursor = self.results_connection.cursor()
            cursor.execute("DESCRIBE TABLE BENEFIT_PROVIDER_COMPARISON_TEST")
            result = cursor.fetchall()
            
            if result:
                logger.info("✅ Target table WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST verified")
                
                # Check if table has EXECUTION_ID column
                column_names = [col[0].upper() for col in result]
                self.table_has_execution_id = 'EXECUTION_ID' in column_names
                
                if self.table_has_execution_id:
                    logger.info("✅ Table has EXECUTION_ID column - will include execution tracking")
                else:
                    logger.warning("⚠️ Table missing EXECUTION_ID column - will insert without execution tracking")
                    logger.info("💡 Consider running: python fix_execution_id_issue.py to add the column")
                    
                logger.info("🔒 CONFIRMED: All writes will go to WORKSPACE.SCRATCH only")
            else:
                raise Exception("Target table BENEFIT_PROVIDER_COMPARISON_TEST not found in WORKSPACE.SCRATCH")
                
            cursor.close()
            
        except Exception as e:
            logger.error(f"Failed to initialize results database connection: {e}")
            logger.error("🚨 SECURITY ERROR: Cannot write to WORKSPACE.SCRATCH - stopping execution")
            raise
    
    def _initialize_persistent_cursors(self):
        """Initialize persistent database cursors to avoid cursor creation overhead"""
        try:
            # Initialize main database cursor (for rating area and radius lookups)
            main_conn = self.benefit_calculator._get_connection()  
            self._main_cursor = main_conn.cursor()
            logger.info("✅ Main database cursor initialized")
            
            # Initialize results database cursor
            if self.results_connection:
                self._results_cursor = self.results_connection.cursor()
                logger.info("✅ Results database cursor initialized")
            
            # Initialize doctor database cursor (for provider lookups) - if needed
            # For now, we'll initialize this lazily since it might not always be used
            self._doctor_cursor = None
            
        except Exception as e:
            logger.warning(f"Failed to initialize persistent cursors: {e}")
            logger.warning("Will fall back to creating cursors on-demand")
            self._main_cursor = None
            self._doctor_cursor = None
            self._results_cursor = None

    def _refresh_connections(self):
        """
        Refresh all Snowflake connections to handle timeout/staleness issues
        
        This method is called by the retry decorator when connection errors occur.
        It closes existing connections and cursors, then reinitializes them.
        """
        logger.info("🔌 Starting connection refresh process...")
        
        try:
            # Close and refresh main database connection (via benefit calculator)
            if hasattr(self, 'benefit_calculator'):
                logger.info("   Refreshing benefit calculator connection...")
                self.benefit_calculator.close_connection()
                # The connection will be re-established on next use
                
            # Close and refresh main cursor
            if hasattr(self, '_main_cursor') and self._main_cursor:
                try:
                    self._main_cursor.close()
                    logger.info("   Closed main cursor")
                except:
                    pass
                self._main_cursor = None
                
            # Close and refresh results connection and cursor  
            if hasattr(self, '_results_cursor') and self._results_cursor:
                try:
                    self._results_cursor.close()
                    logger.info("   Closed results cursor")
                except:
                    pass
                self._results_cursor = None
                
            if hasattr(self, 'results_connection') and self.results_connection:
                try:
                    if not self.results_connection.is_closed():
                        self.results_connection.close()
                        logger.info("   Closed results connection")
                except:
                    pass
                self.results_connection = None
                
            # Close and refresh doctor connection and cursor
            if hasattr(self, '_doctor_cursor') and self._doctor_cursor:
                try:
                    self._doctor_cursor.close()
                    logger.info("   Closed doctor cursor")
                except:
                    pass
                self._doctor_cursor = None
                
            if hasattr(self, 'doctor_connection') and self.doctor_connection:
                try:
                    if not self.doctor_connection.is_closed():
                        self.doctor_connection.close()
                        logger.info("   Closed doctor connection")
                except:
                    pass
                self.doctor_connection = None
            
            # Reinitialize connections
            logger.info("   Reinitializing connections...")
            
            # Reinitialize results database connection
            try:
                self._initialize_results_database()
                logger.info("   ✅ Results database connection refreshed")
            except Exception as e:
                logger.warning(f"   Failed to refresh results database: {e}")
            
            # Reinitialize persistent cursors
            try:
                self._initialize_persistent_cursors()
                logger.info("   ✅ Persistent cursors refreshed")
            except Exception as e:
                logger.warning(f"   Failed to refresh cursors: {e}")
                
            logger.info("🔌 Connection refresh completed successfully")
            
        except Exception as e:
            logger.warning(f"⚠️ Connection refresh encountered errors: {e}")
            logger.warning("Will attempt to continue with new connections on retry")

    @snowflake_retry_with_connection_refresh(max_retries=3, backoff_factor=2.0)
    def _calculate_benefit_amount(self, sidecar_code: str, insurance_filing_uuid: str, zipcode: str) -> Optional[EnhancedBenefitResult]:
        """
        Calculate benefit amount for given parameters

        Returns:
            EnhancedBenefitResult or None if calculation fails
        """
        try:
            logger.debug(f"Calculating benefit for: {sidecar_code} + {insurance_filing_uuid} + {zipcode}")
            result = self.benefit_calculator.calculate_benefit(
                sidecar_code=sidecar_code,
                insurance_filing_uuid=insurance_filing_uuid,
                zipcode=zipcode,
                quantity=1.0,
                is_facility_location=True,
                ignore_rating_area_factor=False,
                is_care_calculation=True,
                prescriptions_covered=True
            )
            logger.debug(f"Benefit calculation succeeded for {sidecar_code}")
            return result
        except Exception as e:
            logger.info(f"Benefit calculation failed for {sidecar_code}/{insurance_filing_uuid}/{zipcode}: {e}")
            return None


    def _get_doctor_connection(self):
        """Create Snowflake connection to Doctor database for provider information"""
        if not hasattr(self, 'doctor_connection') or self.doctor_connection is None or self.doctor_connection.is_closed():
            # Use same credentials but connect to Doctor database
            self.doctor_connection = snowflake.connector.connect(
                user=self.benefit_calculator.snowflake_config['user'],
                password=self.benefit_calculator.snowflake_config['password'],
                account=self.benefit_calculator.snowflake_config['account'],
                warehouse=self.benefit_calculator.snowflake_config.get('warehouse', 'COMPUTE_WH'),
                database='FIVETRAN',  # PROD database
                schema='MYSQL_DOCTOR_SIDECARHEALTH_DOCTOR_V2_DB',
                role=self.benefit_calculator.snowflake_config.get('role', 'SYSADMIN')
            )
        return self.doctor_connection

    @snowflake_retry_with_connection_refresh(max_retries=3, backoff_factor=2.0)
    def _get_rating_area_for_zipcode(self, zipcode: str, insurance_filing_uuid: str) -> str:
        """
        Get rating area for zipcode and insurance filing (same logic as benefit calculator)
        Uses cached results to avoid excessive database calls
        
        Args:
            zipcode: ZIP code
            insurance_filing_uuid: Insurance filing UUID
            
        Returns:
            Rating area code or "UNKNOWN" if not found
        """
        # Initialize cache if not exists
        if not hasattr(self, '_rating_area_cache'):
            self._rating_area_cache = {}
        
        # Check cache first
        cache_key = f"{zipcode}_{insurance_filing_uuid}"
        if cache_key in self._rating_area_cache:
            return self._rating_area_cache[cache_key]
        
        try:
            # Use persistent cursor if available, otherwise create one
            if self._main_cursor:
                cursor = self._main_cursor
            else:
                # Fallback to creating a cursor (if persistent initialization failed)
                conn = self.benefit_calculator._get_connection()
                cursor = conn.cursor()
            
            query = """
            SELECT zcra.RATING_AREA
            FROM ZIP_CODE_RATING_AREA zcra
            WHERE zcra.ZIP_CODE = %s
            LIMIT 1
            """
            
            cursor.execute(query, (zipcode,))
            result = cursor.fetchone()
            
            if result and result[0] is not None:
                rating_area = result[0]
                logger.debug(f"Found rating area {rating_area} for zipcode {zipcode}")
            else:
                logger.debug(f"No rating area found for zipcode {zipcode}, using UNKNOWN")
                rating_area = "UNKNOWN"
            
            # Cache the result
            self._rating_area_cache[cache_key] = rating_area
            return rating_area
                
        except Exception as e:
            logger.debug(f"Failed to get rating area for zipcode {zipcode}: {e}, using UNKNOWN")
            rating_area = "UNKNOWN"
            self._rating_area_cache[cache_key] = rating_area
            return rating_area
        finally:
            # Only close cursor if we created it (not using persistent cursor)
            if not self._main_cursor and 'cursor' in locals():
                cursor.close()

    @snowflake_retry_with_connection_refresh(max_retries=3, backoff_factor=2.0)
    def _get_radius_for_rating_area(self, rating_area: str) -> float:
        """
        Get radius for rating area from RATING_AREA_DEFAULT_RADIUS table
        Uses cached results to avoid excessive database calls
        
        Args:
            rating_area: Rating area code
            
        Returns:
            Radius value for the rating area, or 8.0 as default
        """
        # Initialize cache if not exists
        if not hasattr(self, '_radius_cache'):
            self._radius_cache = {}
        
        # Check cache first
        if rating_area in self._radius_cache:
            return self._radius_cache[rating_area]
        
        try:
            # Use persistent cursor if available, otherwise create one
            if self._main_cursor:
                cursor = self._main_cursor
            else:
                # Fallback to creating a cursor (if persistent initialization failed)
                conn = self.benefit_calculator._get_connection()
                cursor = conn.cursor()
            
            query = """
            SELECT DEFAULT_RADIUS 
            FROM RATING_AREA_DEFAULT_RADIUS
            WHERE RATING_AREA = %s
            """
            
            cursor.execute(query, (rating_area,))
            result = cursor.fetchone()
            
            if result and result[0] is not None:
                radius = float(result[0])
                logger.debug(f"Found radius {radius} for rating area {rating_area}")
            else:
                logger.debug(f"No radius found for rating area {rating_area}, using default 8.0")
                radius = 8.0
            
            # Cache the result
            self._radius_cache[rating_area] = radius
            return radius
                
        except Exception as e:
            logger.debug(f"Failed to get radius for rating area {rating_area}: {e}, using default 8.0")
            radius = 8.0
            self._radius_cache[rating_area] = radius
            return radius
        finally:
            # Only close cursor if we created it (not using persistent cursor)
            if not self._main_cursor and 'cursor' in locals():
                cursor.close()

    @snowflake_retry_with_connection_refresh(max_retries=3, backoff_factor=2.0)
    def _get_providers_from_doctor_db(self, sidecar_code: str, zipcode: str, radius: float) -> List[Dict]:
        """
        Get provider information from Doctor database
        
        Args:
            sidecar_code: Sidecar code to search for
            zipcode: ZIP code for geo filtering
            radius: Search radius in miles
            
        Returns:
            List of provider information from database
        """
        try:
            conn = self._get_doctor_connection()
            cursor = conn.cursor()
            
            # Query to get providers with rates for specific sidecar code
            # This is a placeholder query - you'll need to adjust based on actual table structure
            query = """
            SELECT DISTINCT
                d.NPI,
                d.DISPLAY_NAME,
                d.PROVIDER_TYPE,
                pl.ZIPCODE,
                pl.STATE,
                cr.AVERAGE_PROVIDER_RATE,
                cr.SIDECAR_CODE
            FROM DOCTOR d
            INNER JOIN PRACTICE_LOCATION pl ON d.ID = pl.DOCTOR_ID
            INNER JOIN CARE_RATE cr ON d.NPI = cr.NPI
            WHERE cr.SIDECAR_CODE = %s
            AND cr.AVERAGE_PROVIDER_RATE IS NOT NULL
            AND cr.AVERAGE_PROVIDER_RATE > 0
            AND pl.ZIPCODE IS NOT NULL
            LIMIT 1000
            """
            
            cursor.execute(query, (sidecar_code,))
            results = cursor.fetchall()
            
            if results:
                columns = [desc[0] for desc in cursor.description]
                providers = []
                
                for row in results:
                    provider_data = dict(zip(columns, row))
                    provider_info = {
                        'npi': provider_data.get('NPI', ''),
                        'name': provider_data.get('DISPLAY_NAME', ''),
                        'provider_type': provider_data.get('PROVIDER_TYPE', ''),
                        'zipcode': provider_data.get('ZIPCODE', ''),
                        'state': provider_data.get('STATE', ''),
                        'price': float(provider_data.get('AVERAGE_PROVIDER_RATE', 0)),
                        'sidecar_code': provider_data.get('SIDECAR_CODE', '')
                    }
                    providers.append(provider_info)
                
                logger.debug(f"Found {len(providers)} providers from Doctor DB for sidecar_code {sidecar_code}")
                return providers
            else:
                logger.debug(f"No providers found in Doctor DB for sidecar_code {sidecar_code}")
                return []
                
        except Exception as e:
            logger.debug(f"Failed to get providers from Doctor DB for {sidecar_code}: {e}")
            return []
        finally:
            if 'cursor' in locals():
                cursor.close()

    def _get_state_from_insurance_filing(self, insurance_filing_uuid: str) -> Optional[str]:
        """
        Extract state code from insurance filing UUID
        
        Args:
            insurance_filing_uuid: Insurance filing UUID (e.g., "gfi_oh_202507")
            
        Returns:
            State code (e.g., "OH") or None if pattern doesn't match
        """
        try:
            parts = insurance_filing_uuid.split('_')
            if len(parts) >= 2:
                state_code = parts[1].upper()
                if state_code in ['OH', 'GA', 'FL']:
                    return state_code
            logger.warning(f"Could not extract state from insurance filing: {insurance_filing_uuid}")
            return None
        except Exception as e:
            logger.error(f"Error extracting state from insurance filing {insurance_filing_uuid}: {e}")
            return None

    def _get_zipcode_coordinates(self, zipcode: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get latitude and longitude for zipcode from loaded ZIP code data
        Uses caching to avoid repeated file reads
        
        Args:
            zipcode: ZIP code
            
        Returns:
            Tuple of (latitude, longitude) or (None, None) if not found
        """
        # Check cache first
        if zipcode in self._zipcode_coordinates_cache:
            return self._zipcode_coordinates_cache[zipcode]
        
        try:
            # Search through all state ZIP codes for this zipcode
            for state, zip_data in self.zip_codes_by_state.items():
                # If zip_data is a list of strings, we need to load the full data
                # Load the CSV file for this state to get coordinates
                try:
                    import pandas as pd
                    zip_df = pd.read_csv(f"input_data/zip_code_{state.lower()}.csv")
                    zip_row = zip_df[zip_df['zip'].astype(str) == str(zipcode)]
                    
                    if not zip_row.empty:
                        lat = float(zip_row['lat'].iloc[0])
                        lon = float(zip_row['lon'].iloc[0])
                        logger.debug(f"Found coordinates for ZIP {zipcode}: lat={lat}, lon={lon}")
                        
                        # Cache the result
                        self._zipcode_coordinates_cache[zipcode] = (lat, lon)
                        return lat, lon
                        
                except Exception as e:
                    logger.debug(f"Error loading coordinates for {state}: {e}")
                    continue
            
            logger.debug(f"No coordinates found for ZIP code {zipcode}")
            # Cache the None result to avoid repeated lookups
            self._zipcode_coordinates_cache[zipcode] = (None, None)
            return None, None
            
        except Exception as e:
            logger.debug(f"Error getting coordinates for ZIP {zipcode}: {e}")
            # Cache the None result
            self._zipcode_coordinates_cache[zipcode] = (None, None)
            return None, None

    def _get_provider_prices(self, sidecar_code: str, rating_area: str, zipcode: str, specialties: Optional[List[str]] = None) -> List[Dict]:
        """
        Get provider prices from Elasticsearch for given sidecar code with geo filtering
        
        Args:
            sidecar_code: Sidecar code to search for
            rating_area: Rating area for radius lookup
            zipcode: ZIP code for geo coordinates
        
        Returns:
            List of provider documents with pricing information
        """
        try:
            # Get radius for this rating area
            radius = self._get_radius_for_rating_area(rating_area)
            
            # Get coordinates for zipcode (placeholder implementation)
            lat, lon = self._get_zipcode_coordinates(zipcode)
            
            # Get providers with geo filtering if coordinates available
            if lat is not None and lon is not None:
                logger.debug(f"Searching providers with geo filter: lat={lat}, lon={lon}, radius={radius}, specialties={specialties}")
                providers = self.provider_service.getProviders(
                    sidecar_code=sidecar_code,
                    specialties=specialties,
                    lat=lat,
                    lon=lon, 
                    radius=radius,
                    zipcode=zipcode
                )
            else:
                logger.debug(f"Searching providers without geo filter (no coordinates for zipcode {zipcode}), specialties={specialties}")
                providers = self.provider_service.getProviders(
                    sidecar_code=sidecar_code, 
                    specialties=specialties,
                    zipcode=zipcode, 
                    radius=radius
                )
            
            # # Filter providers that have pricing information
            # providers_with_prices = []
            # for provider in providers:
            #     source = provider.get('_source', {})
            #     care_rates = source.get('careRates', [])
            #
            #     if isinstance(care_rates, list):
            #         for rate in care_rates:
            #             if (rate.get('sidecarCode', '').upper() == sidecar_code.upper() and
            #                 rate.get('averageProviderRate') is not None and
            #                 rate.get('averageProviderRate') > 0):
            #
            #                 provider_info = {
            #                     'npi': source.get('npi', ''),
            #                     'name': source.get('displayName', ''),
            #                     'price': rate.get('averageProviderRate'),
            #                     'sidecar_code': rate.get('sidecarCode', '')
            #                 }
            #                 providers_with_prices.append(provider_info)
            #                 break
            #     elif isinstance(care_rates, dict):
            #         if (care_rates.get('sidecarCode', '').upper() == sidecar_code.upper() and
            #             care_rates.get('averageProviderRate') is not None and
            #             care_rates.get('averageProviderRate') > 0):
            #
            #             provider_info = {
            #                 'npi': source.get('npi', ''),
            #                 'name': source.get('displayName', ''),
            #                 'price': care_rates.get('averageProviderRate'),
            #                 'sidecar_code': care_rates.get('sidecarCode', '')
            #             }
            #             providers_with_prices.append(provider_info)
            # Keep all providers from Python implementation - size limiting will be done before comparison
            limited_providers = providers[:25]  # Limit to top 25 providers for comparison

            # Extract provider information including price for benefit comparison
            clean_providers = []
            for provider in limited_providers:
                # Extract price information before cleaning
                source = provider.get('_source', {})
                provider_price = 0.0
                provider_name = source.get('displayName', provider.get('fullName', 'Unknown Provider'))
                
                # First try to get price from the top-level providerRate field (this is the pre-calculated rate)
                if provider.get('providerRate') is not None and provider.get('providerRate') > 0:
                    provider_price = float(provider.get('providerRate'))
                else:
                    # Fallback: Get price from care rates array
                    care_rates = source.get('careRates', [])
                    if isinstance(care_rates, list):
                        for rate in care_rates:
                            if (isinstance(rate, dict) and 
                                rate.get('sidecarCode', '').upper() == sidecar_code.upper() and
                                rate.get('averageProviderRate') is not None and
                                rate.get('averageProviderRate') > 0):
                                provider_price = float(rate.get('averageProviderRate'))
                                break
                    elif isinstance(care_rates, dict):
                        if (care_rates.get('sidecarCode', '').upper() == sidecar_code.upper() and
                            care_rates.get('averageProviderRate') is not None and
                            care_rates.get('averageProviderRate') > 0):
                            provider_price = float(care_rates.get('averageProviderRate'))
                
                clean_provider = {
                    'npi': provider.get('_id'),
                    'name': provider_name,
                    'price': provider_price,
                    'es_score': provider.get('_score', 0),
                    'query_source': provider.get('_query_source', 'unknown'),
                    'source': provider.get('_source', {})
                }
                
                # Remove pricing info from source copy to avoid duplication
                if 'careRates' in clean_provider['source']:
                    del clean_provider['source']['careRates']
                if 'providerRate' in clean_provider['source']:
                    del clean_provider['source']['providerRate']

                clean_providers.append(clean_provider)
            
            return clean_providers
            
        except Exception as e:
            logger.debug(f"Provider price lookup failed for {sidecar_code}: {e}")
            return []

    def _process_combination(self, sidecar_code: str, insurance_filing_uuid: str, zipcode: str, state: str) -> List[ComparisonResult]:
        """
        Process a single combination of sidecar_code, insurance_filing, zipcode
        
        Returns:
            List of ComparisonResult objects where provider price > either benefit amount (one row per provider)
        """
        results = []

        logger.info(f"🔍 Processing: {sidecar_code} + {insurance_filing_uuid} + {zipcode}")
        
        # Calculate benefit amount
        benefit_result = self._calculate_benefit_amount(sidecar_code, insurance_filing_uuid, zipcode)
        if not benefit_result:
            logger.info(f"❌ No benefit calculated for {sidecar_code} + {insurance_filing_uuid} + {zipcode}")
            return results
        
        logger.info(f"💰 Benefit amounts for {sidecar_code}:")
        logger.info(f"   - Facility: ${benefit_result.facility_benefit_amount:.2f}")
        logger.info(f"   - Non-facility: ${benefit_result.non_facility_benefit_amount:.2f}")
        logger.info(f"   - RX: ${benefit_result.rx_benefit_amount:.2f}")
        logger.info(f"   - Rating area: {benefit_result.rating_area}")
        
        # Get specialties for this sidecar code if available
        specialties = None
        if hasattr(self.provider_service, 'care_lookup') and self.provider_service.care_lookup:
            try:
                specialties = self.provider_service.care_lookup.get_care_search_specialties(sidecar_code)
                if specialties:
                    logger.info(f"🎯 Found specialties for {sidecar_code}: {specialties}")
                else:
                    logger.debug(f"No specialties found for {sidecar_code}")
            except Exception as e:
                logger.debug(f"Failed to get specialties for {sidecar_code}: {e}")
        
        # Get rating area separately for provider search (to ensure we get the proper radius)
        provider_search_rating_area = self._get_rating_area_for_zipcode(zipcode, insurance_filing_uuid)
        logger.debug(f"Using rating area {provider_search_rating_area} for provider search radius lookup")
        
        # Get provider prices with rating area for radius lookup
        provider_prices = self._get_provider_prices(sidecar_code, provider_search_rating_area, zipcode, specialties)
        
        if not provider_prices:
            logger.info(f"❌ No providers found for {sidecar_code} in {zipcode}")
            return results  # No providers found
        
        logger.info(f"👩‍⚕️ Found {len(provider_prices)} providers with pricing for {sidecar_code}")
        
        # Compare each provider price with BOTH facility and non-facility benefit amounts
        # Capture provider if price exceeds either benefit amount
        logger.info(f"🔍 DETAILED COMPARISON for {sidecar_code}:")
        logger.info(f"   📊 Benefit amounts: Facility=${benefit_result.facility_benefit_amount:.2f}, Non-facility=${benefit_result.non_facility_benefit_amount:.2f}")
        logger.info(f"   👥 Comparing {len(provider_prices)} providers")
        
        captured_providers = 0
        for i, provider in enumerate(provider_prices, 1):
            provider_price = provider['price']
            provider_npi = provider.get('npi', 'UNKNOWN')
            provider_name = provider.get('name', 'Unknown Provider')
            
            # Check if provider price exceeds either facility or non-facility benefit amount
            exceeds_facility = (benefit_result.facility_benefit_amount > 0 and 
                              provider_price > benefit_result.facility_benefit_amount)
            exceeds_non_facility = (benefit_result.non_facility_benefit_amount > 0 and 
                                  provider_price > benefit_result.non_facility_benefit_amount)
            
            logger.info(f"   Provider {i}/{len(provider_prices)} - NPI: {provider_npi}")
            logger.info(f"     Name: {provider_name[:50]}")
            logger.info(f"     Price: ${provider_price:.2f}")
            logger.info(f"     vs Facility: ${benefit_result.facility_benefit_amount:.2f} ({'EXCEEDS' if exceeds_facility else 'below'})")
            logger.info(f"     vs Non-facility: ${benefit_result.non_facility_benefit_amount:.2f} ({'EXCEEDS' if exceeds_non_facility else 'below'})")
            
            if exceeds_facility or exceeds_non_facility:
                facility_diff = provider_price - benefit_result.facility_benefit_amount if exceeds_facility else 0
                non_facility_diff = provider_price - benefit_result.non_facility_benefit_amount if exceeds_non_facility else 0
                
                logger.info(f"     ✅ CAPTURED: Provider exceeds benefit amount(s)")
                if exceeds_facility:
                    logger.info(f"       - Exceeds facility by: ${facility_diff:.2f}")
                if exceeds_non_facility:
                    logger.info(f"       - Exceeds non-facility by: ${non_facility_diff:.2f}")
                
                # Capture the provider with all necessary information
                result = ComparisonResult(
                    sidecar_code=sidecar_code,
                    npi=provider_npi,
                    insurance_filing_uuid=insurance_filing_uuid,
                    zipcode=zipcode,
                    state=state,
                    rating_area=benefit_result.rating_area,
                    provider_price=provider_price,
                    facility_benefit_amount=benefit_result.facility_benefit_amount,
                    non_facility_benefit_amount=benefit_result.non_facility_benefit_amount,
                    rx_benefit_amount=benefit_result.rx_benefit_amount,
                    provider_name=provider_name,
                    care_category=benefit_result.care_category,
                    execution_id=self.execution_id
                )
                results.append(result)
                captured_providers += 1
            else:
                logger.info(f"     ❌ SKIPPED: Provider price below both benefit amounts")
        
        if captured_providers > 0:
            logger.info(f"🎯 SUMMARY: Captured {captured_providers}/{len(provider_prices)} providers for {sidecar_code}")
        else:
            logger.info(f"📊 SUMMARY: No providers exceeded benefit amounts for {sidecar_code}")
            logger.info(f"   All {len(provider_prices)} provider prices were below both benefit amounts")
        
        return results

    def run_comparison(self):
        """
        Run the comprehensive comparison by processing each insurance filing with its corresponding state's zip codes
        Each insurance filing is only matched against zip codes from the same state
        Implements error recovery to save partial results if process fails
        """
        logger.info("Starting comprehensive benefit vs provider price comparison")
        
        # Create output directory
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Track completed insurance filings for recovery purposes
        completed_filings = []
        
        # Process each insurance filing separately with state-specific zip codes
        for insurance_filing in self.insurance_fillings:
            try:
                # Extract state from insurance filing
                filing_state = self._get_state_from_insurance_filing(insurance_filing)
                
                if not filing_state:
                    logger.error(f"❌ Could not determine state for insurance filing: {insurance_filing}")
                    continue
                
                logger.info(f"\n{'='*60}")
                logger.info(f"🚀 PROCESSING INSURANCE FILING: {insurance_filing}")
                logger.info(f"📍 STATE: {filing_state}")
                logger.info(f"{'='*60}")
                
                # Get zip codes for this specific state only
                zip_codes = self.zip_codes_by_state[filing_state]
                
                if not zip_codes:
                    logger.warning(f"⚠️ No zip codes found for state {filing_state}, skipping filing {insurance_filing}")
                    continue
                
                filing_combinations = len(zip_codes) * len(self.medical_codes)
                
                logger.info(f"Insurance filing {insurance_filing} combinations to process: {filing_combinations:,}")
                logger.info(f"- ZIP codes ({filing_state}): {len(zip_codes)}")
                logger.info(f"- Medical codes: {len(self.medical_codes)}")
                logger.info(f"- Insurance filing: {insurance_filing} (state-specific)")
                
                filing_results = []
                processed_combinations = 0
                
                # Process each zipcode for this filing's state  
                for zip_idx, zipcode in enumerate(zip_codes, 1):
                    logger.info(f"📍 Processing ZIP code {zip_idx}/{len(zip_codes)}: {zipcode} (state: {filing_state})")
                    zipcode_results = []
                    
                    # For this zipcode, process all medical codes with this specific insurance filing
                    for medical_code in self.medical_codes:
                        processed_combinations += 1
                        
                        if processed_combinations % 100 == 0:
                            progress = (processed_combinations / filing_combinations) * 100
                            logger.info(f"  Progress for {insurance_filing}: {processed_combinations:,}/{filing_combinations:,} ({progress:.1f}%) - Current results: {len(filing_results)}")
                        
                        try:
                            results = self._process_combination(medical_code, insurance_filing, zipcode, filing_state)
                            # *** CRITICAL FIX: Add to batch IMMEDIATELY ***
                            if results:
                                logger.info(f"🔄 IMMEDIATE BATCH: Adding {len(results)} results for {medical_code}")
                                self._add_to_batch(results)  # ← This will auto-flush when batch_size=1
                                logger.info(f"📊 Total database records: {self.total_results_written:,}")

                                # Also keep for local tracking and stats
                                zipcode_results.extend(results)
                                self.results_by_state[filing_state].extend(results)

                        except Exception as e:
                            logger.error(f"Error processing combination {medical_code}/{insurance_filing}/{zipcode}: {e}")
                            continue
                    
                    if zipcode_results:
                        logger.info(f"  ZIP {zipcode}: Found {len(zipcode_results)} providers with price > benefit amount")
                    filing_results.extend(zipcode_results)
                
                # Store and immediately export results for this insurance filing
                self.results_by_state[filing_state].extend(filing_results)
                logger.info(f"\n✅ COMPLETED {insurance_filing}: Found {len(filing_results):,} total results where provider price > benefit amount")
                
                # Write filing results to database immediately
                self._write_state_results_to_database(filing_state, filing_results)
                
                completed_filings.append(insurance_filing)
                
                logger.info(f"🎉 Insurance filing {insurance_filing} processing complete and results exported!")
                
            except Exception as e:
                logger.error(f"❌ CRITICAL ERROR processing insurance filing {insurance_filing}: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Try to save any partial results for this filing if we have any
                filing_state = self._get_state_from_insurance_filing(insurance_filing)
                if filing_state and hasattr(self, 'results_by_state') and filing_state in self.results_by_state and self.results_by_state[filing_state]:
                    try:
                        partial_results = self.results_by_state[filing_state]
                        logger.warning(f"🚨 Attempting to save {len(partial_results)} partial results for {insurance_filing}")
                        self._write_state_results_to_database(filing_state, partial_results)
                        # Force flush any remaining partial results
                        logger.warning(f"🔄 Flushing partial batch for {insurance_filing}...")
                        self._flush_batch(force=True)
                        logger.info(f"✅ Partial results for {insurance_filing} saved to database successfully")
                    except Exception as export_error:
                        logger.error(f"❌ Failed to save partial results for {insurance_filing}: {export_error}")
                
                # Check for database connection issues specifically - STOP GRACEFULLY
                if ("snowflake" in str(e).lower() or 
                    "connection" in str(e).lower() or 
                    "authentication" in str(e).lower() or
                    "timeout" in str(e).lower() or
                    "network" in str(e).lower()):
                    
                    logger.error(f"🛑 SNOWFLAKE/DATABASE CONNECTION FAILURE DETECTED!")
                    logger.error(f"🔌 Connection issue: {str(e)}")
                    logger.error(f"🛑 STOPPING PROCESSING GRACEFULLY - No point continuing without database access")
                    logger.error(f"✅ Successfully completed filings: {completed_filings}")
                    logger.error(f"❌ Failed on filing: {insurance_filing}")
                    
                    # Ensure we don't try to process more filings - break immediately
                    logger.info(f"🚨 Job stopped gracefully due to database connection failure")
                    logger.info(f"💾 All completed results have been saved to database with execution_id: {self.execution_id}")
                    break  # STOP - don't waste time trying other filings without DB access
                else:
                    logger.warning(f"⚠️ Non-database error in {insurance_filing}: {str(e)}")
                    logger.warning(f"⚠️ Continuing with next insurance filing despite error in {insurance_filing}")
                    continue
        
        # Final summary
        if completed_filings:
            logger.info(f"\n🎊 PROCESSING COMPLETED!")
            logger.info(f"✅ Successfully completed insurance filings: {completed_filings}")
            if len(completed_filings) < len(self.insurance_fillings):
                logger.warning(f"⚠️ Some insurance filings were not completed. Check logs for details.")
        else:
            logger.error(f"❌ No insurance filings were completed successfully")
        
        # Flush any remaining results in the batch
        logger.info(f"🔄 Flushing any remaining results...")
        self._flush_batch(force=True)
        
        logger.info(f"💾 All available results have been written to WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST")
        logger.info(f"📊 Total results written: {self.total_results_written:,}")
        logger.info(f"🆔 Use execution_id '{self.execution_id}' to query your results")
        
    def _add_to_batch(self, results: List[ComparisonResult]):
        """Add results to the current batch and write to database if batch is full"""
        if not results:
            return
            
        # Add results to current batch
        self.results_batch.extend(results)
        logger.debug(f"📦 Added {len(results)} results to batch. Batch size: {len(self.results_batch)}/{self.batch_size}")
        
        # Check if we need to flush the batch
        if len(self.results_batch) >= self.batch_size:
            self._flush_batch()
    
    @snowflake_retry_with_connection_refresh(max_retries=3, backoff_factor=2.0)
    def _flush_batch(self, force: bool = False):
        """Write current batch to database and clear the batch"""
        if not self.results_batch:
            if force:
                logger.info("📦 No pending results to flush")
            return
            
        if not force and len(self.results_batch) < self.batch_size:
            logger.debug(f"📦 Batch not full ({len(self.results_batch)}/{self.batch_size}), waiting for more results")
            return
            
        try:
            batch_size = len(self.results_batch)
            logger.info(f"💾 Writing batch of {batch_size} results to database...")
            
            # Convert results to Snowflake records
            records = [result.to_snowflake_record() for result in self.results_batch]
            
            # Get database cursor
            cursor = self._results_cursor if self._results_cursor else self.results_connection.cursor()
            
            # Prepare INSERT statement based on table structure
            if self.table_has_execution_id:
                # Table has EXECUTION_ID column - include it
                insert_sql = """
                INSERT INTO WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST (
                    EXECUTION_ID, SIDECAR_CODE, NPI, INSURANCE_FILING_UUID, ZIPCODE, STATE,
                    RATING_AREA, PROVIDER_PRICE, FACILITY_BENEFIT_AMOUNT, NON_FACILITY_BENEFIT_AMOUNT,
                    RX_BENEFIT_AMOUNT, PROVIDER_NAME, CARE_CATEGORY, EXCEEDS_FACILITY,
                    EXCEEDS_NON_FACILITY, PRICE_VS_FACILITY_DIFF, PRICE_VS_NON_FACILITY_DIFF
                ) VALUES (
                    %(EXECUTION_ID)s, %(SIDECAR_CODE)s, %(NPI)s, %(INSURANCE_FILING_UUID)s,
                    %(ZIPCODE)s, %(STATE)s, %(RATING_AREA)s, %(PROVIDER_PRICE)s,
                    %(FACILITY_BENEFIT_AMOUNT)s, %(NON_FACILITY_BENEFIT_AMOUNT)s,
                    %(RX_BENEFIT_AMOUNT)s, %(PROVIDER_NAME)s, %(CARE_CATEGORY)s,
                    %(EXCEEDS_FACILITY)s, %(EXCEEDS_NON_FACILITY)s, %(PRICE_VS_FACILITY_DIFF)s,
                    %(PRICE_VS_NON_FACILITY_DIFF)s
                )
                """
                # Use records as-is (they include EXECUTION_ID)
                insert_records = records
            else:
                # Table doesn't have EXECUTION_ID column - exclude it
                insert_sql = """
                INSERT INTO WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST (
                    SIDECAR_CODE, NPI, INSURANCE_FILING_UUID, ZIPCODE, STATE,
                    RATING_AREA, PROVIDER_PRICE, FACILITY_BENEFIT_AMOUNT, NON_FACILITY_BENEFIT_AMOUNT,
                    RX_BENEFIT_AMOUNT, PROVIDER_NAME, CARE_CATEGORY, EXCEEDS_FACILITY,
                    EXCEEDS_NON_FACILITY, PRICE_VS_FACILITY_DIFF, PRICE_VS_NON_FACILITY_DIFF
                ) VALUES (
                    %(SIDECAR_CODE)s, %(NPI)s, %(INSURANCE_FILING_UUID)s,
                    %(ZIPCODE)s, %(STATE)s, %(RATING_AREA)s, %(PROVIDER_PRICE)s,
                    %(FACILITY_BENEFIT_AMOUNT)s, %(NON_FACILITY_BENEFIT_AMOUNT)s,
                    %(RX_BENEFIT_AMOUNT)s, %(PROVIDER_NAME)s, %(CARE_CATEGORY)s,
                    %(EXCEEDS_FACILITY)s, %(EXCEEDS_NON_FACILITY)s, %(PRICE_VS_FACILITY_DIFF)s,
                    %(PRICE_VS_NON_FACILITY_DIFF)s
                )
                """
                # Remove EXECUTION_ID from records
                insert_records = []
                for record in records:
                    record_copy = record.copy()
                    if 'EXECUTION_ID' in record_copy:
                        del record_copy['EXECUTION_ID']
                    insert_records.append(record_copy)
            
            # Execute batch insert
            cursor.executemany(insert_sql, insert_records)
            
            # Commit the transaction
            self.results_connection.commit()
            
            # Close cursor if using temporary cursor
            if not self._results_cursor:
                cursor.close()
            
            # Update counters
            self.total_results_written += batch_size
            
            # Get state distribution for this batch
            state_counts = {}
            for result in self.results_batch:
                state = result.state
                state_counts[state] = state_counts.get(state, 0) + 1
            
            state_summary = ", ".join([f"{state}:{count}" for state, count in state_counts.items()])
            
            logger.info(f"✅ Successfully wrote batch: {batch_size} records ({state_summary})")
            logger.info(f"📊 Total results written so far: {self.total_results_written:,}")
            
            # Clear the batch
            self.results_batch = []
            
        except Exception as e:
            logger.error(f"❌ Failed to write batch to database: {e}")
            logger.error(f"📊 Batch contained {len(self.results_batch)} records")
            logger.error(f"🔍 Error details: {traceback.format_exc()}")
            raise
    
    def _write_state_results_to_database(self, state: str, results: List[ComparisonResult]):
        """Add state results to batch for writing to database"""
        if not results:
            logger.info(f"No results to add for {state}")
            return
        
        logger.info(f"📦 Adding {len(results)} results from {state} to batch queue")
        
        # Add results to batch (will automatically flush if batch is full)
        self._add_to_batch(results)
        
        # Print summary statistics for this state
        if len(results) > 0:
            avg_provider_price = sum(r.provider_price for r in results) / len(results)
            max_provider_price = max(r.provider_price for r in results)
            avg_facility_benefit = sum(r.facility_benefit_amount for r in results) / len(results)
            avg_non_facility_benefit = sum(r.non_facility_benefit_amount for r in results) / len(results)
            unique_npis = len(set(r.npi for r in results))
            
            logger.info(f"📊 {state} Summary:")
            logger.info(f"  - Average provider price: ${avg_provider_price:.2f}")
            logger.info(f"  - Maximum provider price: ${max_provider_price:.2f}")
            logger.info(f"  - Average facility benefit: ${avg_facility_benefit:.2f}")
            logger.info(f"  - Average non-facility benefit: ${avg_non_facility_benefit:.2f}")
            logger.info(f"  - Total unique providers: {unique_npis:,}")

    def export_results(self, output_dir: str = "output"):
        """
        Export results to state-specific CSV files
        
        Args:
            output_dir: Directory to save output CSV files
        """
        logger.info("Exporting results to CSV files")
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for state, results in self.results_by_state.items():
            if not results:
                logger.info(f"No results to export for {state}")
                continue
            
            # Convert results to DataFrame
            result_dicts = [result.to_dict() for result in results]
            df = pd.DataFrame(result_dicts)
            
            # Sort by provider price (highest first)
            df = df.sort_values('provider_price', ascending=False)
            
            # Export to CSV
            filename = f"benefit_provider_comparison_{state}_{timestamp}.csv"
            filepath = os.path.join(output_dir, filename)
            df.to_csv(filepath, index=False)
            
            logger.info(f"Exported {len(results)} results for {state} to {filepath}")
            
            # Print summary statistics
            if len(results) > 0:
                avg_provider_price = df['provider_price'].mean()
                max_provider_price = df['provider_price'].max()
                logger.info(f"{state} Summary: Avg provider price: ${avg_provider_price:.2f}, Max provider price: ${max_provider_price:.2f}")

    def print_summary(self):
        """Print summary of comparison results"""
        logger.info("\n" + "="*60)
        logger.info("COMPREHENSIVE COMPARISON SUMMARY")
        logger.info("="*60)
        
        total_results = 0
        for state, results in self.results_by_state.items():
            count = len(results)
            total_results += count
            logger.info(f"{state}: {count} cases where provider price > benefit amount")
            
            if count > 0:
                avg_price = sum(r.provider_price for r in results) / count
                max_price = max(r.provider_price for r in results)
                logger.info(f"  Average provider price: ${avg_price:.2f}")
                logger.info(f"  Maximum provider price: ${max_price:.2f}")
        
        logger.info(f"\nTotal cases found: {total_results}")
        logger.info("="*60)

    def cleanup(self):
        """Clean up resources and connections to prevent connection leaks"""
        logger.info("🧹 Starting cleanup process...")
        
        # FIRST: Flush any remaining results before closing connections
        logger.info("🔄 EMERGENCY FLUSH: Attempting to save any remaining results before cleanup...")
        try:
            if hasattr(self, 'results_batch') and self.results_batch:
                logger.warning(f"⚠️ FOUND {len(self.results_batch)} UNSAVED RESULTS IN BATCH!")
                logger.info("📊 LOGGING UNSAVED RESULTS TO CONSOLE:")
                for i, result in enumerate(self.results_batch, 1):
                    logger.info(f"  {i}. {result.sidecar_code} | {result.npi} | {result.provider_name[:30]} | ${result.provider_price:.2f}")
                
                # Try to flush to database
                self._flush_batch(force=True)
                logger.info("✅ Successfully saved remaining results to database")
            else:
                logger.info("✅ No pending results found - all data already saved")
        except Exception as e:
            logger.error(f"❌ Failed to flush remaining results: {e}")
            if hasattr(self, 'results_batch') and self.results_batch:
                logger.error(f"🚨 LOST DATA WARNING: {len(self.results_batch)} results could not be saved!")
                logger.error("📊 UNSAVED RESULTS (logged for recovery):")
                for i, result in enumerate(self.results_batch, 1):
                    logger.error(f"  LOST {i}: {result.sidecar_code} | {result.npi} | {result.provider_name[:30]} | ${result.provider_price:.2f} | ZIP:{result.zipcode} | STATE:{result.state}")
        
        logger.info("Cleaning up database connections and resources...")
        
        # Close persistent cursors first
        if hasattr(self, '_main_cursor') and self._main_cursor:
            try:
                self._main_cursor.close()
                logger.info("Closed persistent main database cursor")
            except Exception as e:
                logger.warning(f"Error closing main cursor: {e}")
        
        if hasattr(self, '_doctor_cursor') and self._doctor_cursor:
            try:
                self._doctor_cursor.close()
                logger.info("Closed persistent doctor database cursor")
            except Exception as e:
                logger.warning(f"Error closing doctor cursor: {e}")
        
        if hasattr(self, '_results_cursor') and self._results_cursor:
            try:
                self._results_cursor.close()
                logger.info("Closed persistent results database cursor")
            except Exception as e:
                logger.warning(f"Error closing results cursor: {e}")
        
        # Close benefit calculator connection
        if hasattr(self, 'benefit_calculator'):
            self.benefit_calculator.close_connection()
            logger.info("Closed benefit calculator connection")
        
        # Close results database connection
        if hasattr(self, 'results_connection') and self.results_connection and not self.results_connection.is_closed():
            self.results_connection.close()
            logger.info("Closed results database connection")
        
        # Close doctor database connection
        if hasattr(self, 'doctor_connection') and self.doctor_connection and not self.doctor_connection.is_closed():
            self.doctor_connection.close()
            logger.info("Closed doctor database connection")
        
        # Close QA connection (legacy)
        if hasattr(self, 'qa_connection') and self.qa_connection and not self.qa_connection.is_closed():
            self.qa_connection.close()
            logger.info("Closed QA database connection")
        
        # Clear caches to free memory
        # Flush any remaining results before cleanup
        logger.info("🔄 Final flush of any remaining batched results...")
        try:
            self._flush_batch(force=True)
        except Exception as e:
            logger.warning(f"Warning during final batch flush: {e}")
        
        cache_stats = {
            'rating_area': len(getattr(self, '_rating_area_cache', {})),
            'radius': len(getattr(self, '_radius_cache', {})),
            'coordinates': len(getattr(self, '_zipcode_coordinates_cache', {})),
            'batch_remaining': len(getattr(self, 'results_batch', []))
        }
        
        if hasattr(self, '_rating_area_cache'):
            self._rating_area_cache.clear()
        if hasattr(self, '_radius_cache'):
            self._radius_cache.clear()
        if hasattr(self, '_zipcode_coordinates_cache'):
            self._zipcode_coordinates_cache.clear()
        if hasattr(self, 'results_batch'):
            self.results_batch.clear()
        
        logger.info(f"Final statistics:")
        logger.info(f"  - Total results written: {getattr(self, 'total_results_written', 0):,}")
        logger.info(f"  - Results remaining in batch: {cache_stats['batch_remaining']}")
        logger.info(f"Cache statistics before cleanup:")
        logger.info(f"  - Rating area cache: {cache_stats['rating_area']} entries")
        logger.info(f"  - Radius cache: {cache_stats['radius']} entries")  
        logger.info(f"  - Coordinates cache: {cache_stats['coordinates']} entries")
        
        logger.info("✅ Resource cleanup completed - All cursors closed, connections closed, caches cleared, final batch flushed")

def main():
    """Main execution function"""
    logger.info("Starting Comprehensive Benefit vs Provider Price Comparison")
    
    comparison = None
    try:
        # Initialize the comparison system with batch processing
        comparison = ComprehensiveBenefitProviderComparison(data_dir="input_data", batch_size=100)
        
        # Run the comprehensive comparison (exports results automatically for each state)
        comparison.run_comparison()
        
        logger.info("\n🎊 COMPREHENSIVE COMPARISON COMPLETED SUCCESSFULLY!")
        logger.info(f"All results have been written to WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST")
        logger.info(f"📊 Total records written: {comparison.total_results_written:,}")
        logger.info(f"🆔 Query your results using execution_id: '{comparison.execution_id}'")
        logger.info(f"📊 Example query: SELECT * FROM WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST WHERE EXECUTION_ID = '{comparison.execution_id}';")
        
    except Exception as e:
        logger.error(f"🚨 COMPREHENSIVE COMPARISON FAILED: {e}")
        logger.error(f"📊 Traceback: {traceback.format_exc()}")
        
        # Try to save any remaining results before exiting
        if comparison:
            try:
                logger.error("🔄 ATTEMPTING EMERGENCY DATA SAVE before exit...")
                if hasattr(comparison, 'results_batch') and comparison.results_batch:
                    logger.error(f"⚠️ FOUND {len(comparison.results_batch)} UNSAVED RESULTS - logging to console:")
                    for i, result in enumerate(comparison.results_batch, 1):
                        logger.error(f"  UNSAVED {i}: {result.sidecar_code} | {result.npi} | {result.provider_name[:30]} | ${result.provider_price:.2f}")
                        
                logger.error(f"📊 FINAL STATS: Total results written before failure: {getattr(comparison, 'total_results_written', 0):,}")
                logger.error(f"🆔 Query saved results: SELECT * FROM WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST WHERE EXECUTION_ID = '{getattr(comparison, 'execution_id', 'UNKNOWN')}';")
            except Exception as save_error:
                logger.error(f"❌ Failed to perform emergency save: {save_error}")
        
        sys.exit(1)
    
    finally:
        if comparison:
            comparison.cleanup()

if __name__ == "__main__":
    main()