#!/usr/bin/env python3
"""
Care Database Utilities
Utilities for fetching specialties and other data from care database using Snowflake
"""

import logging
import csv
import json
import os
import boto3
import snowflake.connector
from typing import List, Dict, Any, Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CareDBUtils:
    """
    Utility class for fetching data from care database and CSV files
    """
    
    def __init__(self, data_dir: str = "data", aws_region: str = None, use_database: bool = True):
        """
        Initialize with data directory path and optional database connection
        """
        self.data_dir = data_dir
        self.use_database = use_database
        self.connection = None
        
        if use_database:
            # Set up AWS region
            self.aws_region = aws_region or os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1'
            os.environ['AWS_DEFAULT_REGION'] = self.aws_region
            
            try:
                self.secrets_client = boto3.client('secretsmanager', region_name=self.aws_region)
                self.snowflake_config = self._get_snowflake_credentials()
                logger.info("Snowflake credentials retrieved successfully")
            except Exception as e:
                logger.warning(f"Failed to get Snowflake credentials, falling back to placeholder data: {e}")
                self.use_database = False
    
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
        """Create or return existing Snowflake connection"""
        if not self.use_database:
            return None
            
        if self.connection is None or self.connection.is_closed():
            try:
                self.connection = snowflake.connector.connect(
                    user=self.snowflake_config['user'],
                    password=self.snowflake_config['password'],
                    account=self.snowflake_config['account'],
                    warehouse=self.snowflake_config.get('warehouse', 'COMPUTE_WH'),
                    database='FIVETRAN',
                    schema='MYSQL_CARE_SIDECARHEALTH_CARE_DB',
                    role=self.snowflake_config.get('role', 'SYSADMIN')
                )
                logger.info("Snowflake connection established")
            except Exception as e:
                logger.error(f"Failed to connect to Snowflake: {e}")
                self.use_database = False
                return None
        return self.connection
    
    def get_specialties_by_sidecar_code(self, sidecar_code: str) -> List[str]:
        """
        Get specialties for a sidecar code from care_reimbursement_info table
        """
        if self.use_database:
            return self._get_specialties_from_database(sidecar_code)
        else:
            return self._get_specialties_from_placeholder(sidecar_code)
    
    def _get_specialties_from_database(self, sidecar_code: str) -> List[str]:
        """
        Get specialties from actual Snowflake database
        """
        query = """
        SELECT CARE_SPECIALTIES
        FROM CARE_REIMBURSEMENT_INFO
        WHERE SIDECAR_CODE = %s
        AND IS_ACTIVE = 'T'
        LIMIT 1
        """
        
        conn = self._get_connection()
        if not conn:
            logger.warning("No database connection, falling back to placeholder data")
            return self._get_specialties_from_placeholder(sidecar_code)
        
        cursor = conn.cursor()
        
        try:
            logger.info(f"Querying database for specialties of sidecar code: {sidecar_code}")
            cursor.execute(query, (sidecar_code,))
            result = cursor.fetchone()
            
            if result and result[0]:
                specialties_str = result[0]
                specialties = [s.strip().lower() for s in specialties_str.split(',') if s.strip()]
                logger.info(f"Found specialties for {sidecar_code} from database: {specialties}")
                return specialties
            else:
                logger.warning(f"No specialties found in database for sidecar code: {sidecar_code}")
                return []
                
        except Exception as e:
            logger.error(f"Database query failed for sidecar {sidecar_code}: {e}")
            return self._get_specialties_from_placeholder(sidecar_code)
        finally:
            cursor.close()
    
    def _get_specialties_from_placeholder(self, sidecar_code: str) -> List[str]:
        """
        Get specialties from placeholder mapping (fallback when database is unavailable)
        """
        logger.info(f"Using placeholder data for sidecar code: {sidecar_code}")
        
        # Placeholder mapping for testing - based on common medical specialties
        sidecar_specialties_map = {
            'SC123': 'cardiology,internal medicine,family medicine',
            'SC124': 'dermatology,plastic surgery',
            'SC125': 'orthopedics,sports medicine,physical therapy',
            'SC126': 'neurology,neurosurgery',
            'SC127': 'oncology,hematology',
            'SC128': 'pediatrics,family medicine',
            'SC129': 'psychiatry,psychology',
            'SC130': 'radiology,diagnostic imaging',
            '90834': 'psychiatry,psychology,behavioral health',  # Psychotherapy code
            '99213': 'internal medicine,family medicine',  # Office visit
            '90791': 'psychiatry,psychology',  # Psychiatric diagnostic evaluation
            '36415': 'laboratory,pathology',  # Venipuncture
            '80053': 'laboratory,pathology',  # Comprehensive metabolic panel
            '93000': 'cardiology,internal medicine',  # ECG
            '99396': 'preventive medicine,family medicine'  # Preventive visit
        }
        
        specialties_str = sidecar_specialties_map.get(sidecar_code, '')
        if specialties_str:
            specialties = [s.strip().lower() for s in specialties_str.split(',') if s.strip()]
            logger.info(f"Found specialties for {sidecar_code} from placeholder: {specialties}")
            return specialties
        else:
            logger.warning(f"No specialties found for sidecar code: {sidecar_code}")
            return []
    
    def get_coordinates_by_zip(self, zip_code: str, state: str = None) -> Optional[Tuple[float, float]]:
        """
        Get latitude and longitude for a zip code from zip_code CSV files
        """
        # Try state-specific file first if state provided
        if state:
            state_file = os.path.join(self.data_dir, f"zip_code_{state.lower()}.csv")
            coords = self._search_zip_in_file(zip_code, state_file)
            if coords:
                return coords
        
        # Search all zip_code files
        zip_files = [
            f for f in os.listdir(self.data_dir) 
            if f.startswith('zip_code_') and f.endswith('.csv')
        ]
        
        for zip_file in zip_files:
            file_path = os.path.join(self.data_dir, zip_file)
            coords = self._search_zip_in_file(zip_code, file_path)
            if coords:
                return coords
        
        logger.warning(f"No coordinates found for zip code: {zip_code}")
        return None
    
    def _search_zip_in_file(self, zip_code: str, file_path: str) -> Optional[Tuple[float, float]]:
        """
        Search for zip code in a specific CSV file
        """
        try:
            with open(file_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row.get('zip', '').strip() == zip_code.strip():
                        lat = float(row.get('lat', 0))
                        lon = float(row.get('lon', 0))
                        logger.info(f"Found coordinates for {zip_code}: ({lat}, {lon})")
                        return (lat, lon)
        except FileNotFoundError:
            logger.debug(f"File not found: {file_path}")
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
        
        return None
    
    def get_available_zip_codes(self, state: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get available zip codes for testing purposes
        """
        zip_codes = []
        
        if state:
            state_file = os.path.join(self.data_dir, f"zip_code_{state.lower()}.csv")
            zip_codes.extend(self._read_zip_codes_from_file(state_file, limit))
        else:
            # Read from all files
            zip_files = [
                f for f in os.listdir(self.data_dir) 
                if f.startswith('zip_code_') and f.endswith('.csv')
            ]
            
            per_file_limit = max(1, limit // len(zip_files)) if zip_files else limit
            
            for zip_file in zip_files:
                file_path = os.path.join(self.data_dir, zip_file)
                zip_codes.extend(self._read_zip_codes_from_file(file_path, per_file_limit))
                
                if len(zip_codes) >= limit:
                    break
        
        return zip_codes[:limit]
    
    def _read_zip_codes_from_file(self, file_path: str, limit: int) -> List[Dict[str, Any]]:
        """
        Read zip codes from a specific CSV file
        """
        zip_codes = []
        
        try:
            with open(file_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for i, row in enumerate(reader):
                    if i >= limit:
                        break
                    
                    zip_codes.append({
                        'zip': row.get('zip', ''),
                        'lat': float(row.get('lat', 0)),
                        'lon': float(row.get('lon', 0)),
                        'state': row.get('state', ''),
                        'policy_count': int(row.get('policy_count', 0))
                    })
        except FileNotFoundError:
            logger.debug(f"File not found: {file_path}")
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
        
        return zip_codes
    
    def create_provider_test_scenarios(self) -> List[Dict[str, Any]]:
        """
        Create comprehensive test scenarios using real zip codes and sidecar mappings
        """
        scenarios = []
        
        # Get some sample zip codes
        sample_zips = self.get_available_zip_codes(limit=5)
        
        # Test scenarios with different sidecar codes
        sidecar_codes = ['SC123', 'SC124', 'SC125', 'SC126']
        
        for i, sidecar_code in enumerate(sidecar_codes):
            if i < len(sample_zips):
                zip_info = sample_zips[i]
                specialties = self.get_specialties_by_sidecar_code(sidecar_code)
                
                scenarios.append({
                    'test_name': f'Test_{sidecar_code}_{zip_info["zip"]}',
                    'sidecar_code': sidecar_code,
                    'specialties': specialties,
                    'lat': zip_info['lat'],
                    'lon': zip_info['lon'],
                    'zip_code': zip_info['zip'],
                    'state': zip_info['state'],
                    'radius': 25.0
                })
        
        return scenarios
    
    def close_connection(self):
        """Close Snowflake connection"""
        if self.connection and not self.connection.is_closed():
            self.connection.close()
            logger.info("Snowflake connection closed")

def create_actual_db_query_template():
    """
    Template for actual database query implementation
    """
    db_query_template = '''
# Actual database implementation (replace placeholder above)

import pymysql  # or your preferred DB connector

class ActualCareDBUtils(CareDBUtils):
    def __init__(self, db_config: Dict[str, str], data_dir: str = "data"):
        super().__init__(data_dir)
        self.db_config = db_config
    
    def get_specialties_by_sidecar_code(self, sidecar_code: str) -> List[str]:
        """
        Get specialties from actual care_reimbursement_info table
        """
        try:
            connection = pymysql.connect(**self.db_config)
            with connection.cursor() as cursor:
                query = """
                SELECT care_specialties 
                FROM care_reimbursement_info 
                WHERE sidecar_code = %s
                """
                cursor.execute(query, (sidecar_code,))
                result = cursor.fetchone()
                
                if result and result[0]:
                    specialties = [s.strip().lower() for s in result[0].split(',') if s.strip()]
                    logger.info(f"Found specialties for {sidecar_code}: {specialties}")
                    return specialties
                else:
                    logger.warning(f"No specialties found for sidecar code: {sidecar_code}")
                    return []
                    
        except Exception as e:
            logger.error(f"Database error: {e}")
            return []
        finally:
            if 'connection' in locals():
                connection.close()
'''
    
    return db_query_template

def main():
    """
    Example usage of CareDBUtils
    """
    
    # Initialize utils with database enabled
    db_utils = CareDBUtils(use_database=True)
    
    try:
        # Test specialty lookup
        print("=== Testing Specialty Lookup ===")
        sidecar_code = "90834"  # Use a real CPT code
        specialties = db_utils.get_specialties_by_sidecar_code(sidecar_code)
        print(f"Sidecar {sidecar_code} specialties: {specialties}")
        
        # Test another real code
        sidecar_code2 = "99213"
        specialties2 = db_utils.get_specialties_by_sidecar_code(sidecar_code2)
        print(f"Sidecar {sidecar_code2} specialties: {specialties2}")
        
        # Test coordinate lookup
        print("\n=== Testing Coordinate Lookup ===")
        zip_code = "43560"
        coords = db_utils.get_coordinates_by_zip(zip_code, "OH")
        print(f"Zip {zip_code} coordinates: {coords}")
        
        # Test available zip codes
        print("\n=== Available Zip Codes (Sample) ===")
        zip_codes = db_utils.get_available_zip_codes(limit=5)
        for zip_info in zip_codes:
            print(f"Zip: {zip_info['zip']}, State: {zip_info['state']}, Coords: ({zip_info['lat']}, {zip_info['lon']})")
        
        # Test scenarios
        print("\n=== Test Scenarios ===")
        scenarios = db_utils.create_provider_test_scenarios()
        for scenario in scenarios:
            print(f"Scenario: {scenario['test_name']}")
            print(f"  Sidecar: {scenario['sidecar_code']}")
            print(f"  Specialties: {scenario['specialties']}")
            print(f"  Location: {scenario['zip_code']}, {scenario['state']} ({scenario['lat']}, {scenario['lon']})")
            print()
    
    finally:
        # Always close the connection
        db_utils.close_connection()

if __name__ == "__main__":
    main()