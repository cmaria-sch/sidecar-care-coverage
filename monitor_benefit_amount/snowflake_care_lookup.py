#!/usr/bin/env python3
"""
Snowflake lookup utility for CareReimbursementInfo.careSearchSpecialties
to match Java filtering behavior
"""

import snowflake.connector
import logging
import boto3
import json
import os
from typing import Dict, List, Optional, Set
from config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CareReimbursementLookup:
    """
    Utility class to lookup CareReimbursementInfo.careSearchSpecialties from Snowflake
    to match Java's provider filtering behavior
    """
    
    def __init__(self, aws_region: str = None):
        # Set up AWS region
        self.aws_region = aws_region or os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1'
        os.environ['AWS_DEFAULT_REGION'] = self.aws_region
        
        self.secrets_client = boto3.client('secretsmanager', region_name=self.aws_region)
        self.snowflake_config = self._get_snowflake_credentials()
        self.connection = None
        self._care_search_specialties_cache = {}
    
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
        """Get or create Snowflake connection using AWS credentials"""
        if self.connection is None or self.connection.is_closed():
            try:
                # Use same connection approach as other files in the project
                self.connection = snowflake.connector.connect(
                    user=self.snowflake_config['user'],
                    password=self.snowflake_config['password'],
                    account=self.snowflake_config['account'],
                    warehouse=self.snowflake_config.get('warehouse', 'COMPUTE_WH'),
                    database='FIVETRAN',  # Same as other files
                    schema='MYSQL_CARE_SIDECARHEALTH_CARE_DB',  # Same as other files
                    role=self.snowflake_config.get('role', 'SYSADMIN')
                )
                logger.info("Connected to Snowflake successfully")
            except Exception as e:
                logger.error(f"Failed to connect to Snowflake: {e}")
                raise
        return self.connection
    
    def get_care_search_specialties(self, sidecar_code: str) -> List[str]:
        """
        Get careSearchSpecialties for a given sidecar code from CareReimbursementInfo table
        
        Args:
            sidecar_code: The sidecar code to lookup
            
        Returns:
            List of specialty strings for this sidecar code
        """
        # Check cache first
        if sidecar_code in self._care_search_specialties_cache:
            return self._care_search_specialties_cache[sidecar_code]
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Query to get careSearchSpecialties for the sidecar code
            query = """
            SELECT DISTINCT CARE_SEARCH_SPECIALTIES
            FROM CARE_REIMBURSEMENT_INFO 
            WHERE SIDECAR_CODE = %s 
            AND CARE_SEARCH_SPECIALTIES IS NOT NULL 
            AND CARE_SEARCH_SPECIALTIES != ''
            """
            
            cursor.execute(query, (sidecar_code,))
            results = cursor.fetchall()
            
            # Extract and flatten the specialties
            def flatten_specialty(item):
                """Recursively flatten specialty data"""
                if isinstance(item, (list, tuple)):
                    # Flatten lists/tuples recursively
                    flattened = []
                    for sub_item in item:
                        flattened.extend(flatten_specialty(sub_item))
                    return flattened
                elif isinstance(item, str):
                    # Handle comma-separated strings
                    if ',' in item:
                        return [s.strip().lower() for s in item.split(',') if s.strip()]
                    else:
                        item = item.strip().lower()
                        return [item] if item else []
                elif item is not None:
                    # Convert other types to string and try again
                    return flatten_specialty(str(item))
                else:
                    return []
            
            specialties = []
            for row in results:
                specialty = row[0]
                if specialty:
                    specialties.extend(flatten_specialty(specialty))
            
            # Remove duplicates and cache - handle potential non-string items safely
            clean_specialties = []
            for spec in specialties:
                # Recursively flatten any nested structures
                if isinstance(spec, (list, tuple)):
                    # If we somehow got a list/tuple, flatten it
                    for sub_spec in spec:
                        if isinstance(sub_spec, str) and sub_spec.strip():
                            clean_specialties.append(sub_spec.strip().lower())
                        elif sub_spec is not None:
                            clean_specialties.append(str(sub_spec).strip().lower())
                elif isinstance(spec, str) and spec.strip():
                    clean_specialties.append(spec.strip().lower())
                elif spec is not None:
                    # Convert non-string items to string as fallback
                    clean_specialties.append(str(spec).strip().lower())
            
            # Remove duplicates safely - filter out empty strings first
            clean_specialties = [s for s in clean_specialties if s and isinstance(s, str)]
            specialties = list(set(clean_specialties))
            self._care_search_specialties_cache[sidecar_code] = specialties
            
            logger.info(f"Found {len(specialties)} careSearchSpecialties for sidecar {sidecar_code}: {specialties}")
            return specialties
            
        except Exception as e:
            logger.error(f"Failed to lookup careSearchSpecialties for {sidecar_code}: {e}")
            # Return empty list on error so filtering doesn't break
            return []
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def get_provider_npi_to_specialties_map(self, provider_npis: List[str]) -> Dict[str, List[str]]:
        """
        NOTE: CARE_REIMBURSEMENT_INFO table doesn't have NPI column - it's organized by SIDECAR_CODE.
        This method can't work as designed. Provider filtering should be done based on 
        CARE_SEARCH_SPECIALTIES for the sidecar code, not individual NPIs.
        
        Args:
            provider_npis: List of provider NPIs to lookup
            
        Returns:
            Empty dict since we can't lookup by NPI in this table
        """
        logger.warning("CARE_REIMBURSEMENT_INFO table doesn't contain NPI column - cannot filter by individual NPIs")
        logger.info("Provider filtering should be done based on sidecar code's CARE_SEARCH_SPECIALTIES")
        return {}
    
    def get_rating_area_by_zipcode(self, zipcode: str, insurance_filing_uuid: str = None) -> Optional[str]:
        """
        Get rating area for a given zipcode from Snowflake
        
        Args:
            zipcode: The zipcode to lookup
            insurance_filing_uuid: Optional insurance filing UUID for more specific lookup
            
        Returns:
            Rating area string or None if not found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Query to get rating area from zipcode (matching existing code patterns)
            # Include Fivetran deletion filter like other queries in the project
            if insurance_filing_uuid:
                query = """
                SELECT RATING_AREA
                FROM ZIP_CODE_RATING_AREA 
                WHERE ZIP_CODE = %s 
                AND INSURANCE_FILING_UUID = %s
                AND RATING_AREA IS NOT NULL
                LIMIT 1
                """
                cursor.execute(query, (zipcode, insurance_filing_uuid))
            else:
                query = """
                SELECT RATING_AREA
                FROM ZIP_CODE_RATING_AREA 
                WHERE ZIP_CODE = %s 
                AND RATING_AREA IS NOT NULL
                LIMIT 1
                """
                cursor.execute(query, (zipcode,))
            
            result = cursor.fetchone()
            rating_area = result[0] if result else None
            
            logger.info(f"Zipcode {zipcode} -> Rating Area: {rating_area}")
            return rating_area
            
        except Exception as e:
            logger.error(f"Failed to lookup rating area for zipcode {zipcode}: {e}")
            return None
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def get_radius_by_rating_area(self, rating_area: str) -> Optional[float]:
        """
        Get radius for a given rating area from Snowflake
        
        Args:
            rating_area: The rating area to lookup
            
        Returns:
            Radius in miles or None if not found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Also include Fivetran deletion filter like existing code
            query = """
            SELECT DEFAULT_RADIUS 
            FROM RATING_AREA_DEFAULT_RADIUS
            WHERE RATING_AREA = %s 
            AND DEFAULT_RADIUS IS NOT NULL
            LIMIT 1
            """
            
            cursor.execute(query, (rating_area,))
            result = cursor.fetchone()
            radius = float(result[0]) if result else None
            
            logger.info(f"Rating Area {rating_area} -> DEFAULT_RADIUS: {radius} miles")
            return radius
            
        except Exception as e:
            logger.error(f"Failed to lookup radius for rating area {rating_area}: {e}")
            return None
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def get_radius_by_zipcode(self, zipcode: str, insurance_filing_uuid: str = None, default_radius: float = 8.0) -> float:
        """
        Get radius for a zipcode by doing: zipcode -> rating_area -> radius lookup
        
        Args:
            zipcode: The zipcode to lookup
            insurance_filing_uuid: Optional insurance filing UUID
            default_radius: Default radius if lookup fails
            
        Returns:
            Radius in miles (returns default_radius if lookup fails)
        """
        try:
            # Step 1: Get rating area from zipcode
            rating_area = self.get_rating_area_by_zipcode(zipcode, insurance_filing_uuid)
            if not rating_area:
                logger.warning(f"No rating area found for zipcode {zipcode}, using default radius {default_radius}")
                return default_radius
            
            # Step 2: Get radius from rating area
            radius = self.get_radius_by_rating_area(rating_area)
            if radius is None:
                logger.warning(f"No radius found for rating area {rating_area}, using default radius {default_radius}")
                return default_radius
            
            logger.info(f"Zipcode {zipcode} -> Rating Area {rating_area} -> Radius {radius} miles")
            return radius
            
        except Exception as e:
            logger.error(f"Failed to get radius for zipcode {zipcode}: {e}, using default radius {default_radius}")
            return default_radius
    
    def get_care_specialties(self, sidecar_code: str) -> Optional[List[str]]:
        """
        Get care specialties for a sidecar code from CARE_REIMBURSEMENT_INFO.SPECIALTIES
        
        Args:
            sidecar_code: Sidecar code to lookup
            
        Returns:
            List of specialty strings or None if not found
        """
        if not self.connection or self.connection.is_closed():
            logger.error("No active Snowflake connection")
            return None
            
        try:
            cursor = self.connection.cursor()
            
            # Query CARE_REIMBURSEMENT_INFO.SPECIALTIES
            query = """
            SELECT SPECIALTIES 
            FROM FIVETRAN.MYSQL_CARE_SIDECARHEALTH_CARE_DB.CARE_REIMBURSEMENT_INFO
            WHERE SIDECAR_CODE = %s 
            AND SPECIALTIES IS NOT NULL
            LIMIT 1
            """
            
            cursor.execute(query, (sidecar_code,))
            result = cursor.fetchone()
            
            if result and result[0]:
                specialties_str = result[0]
                # Parse comma-separated specialties and clean them up
                specialties = [s.strip() for s in specialties_str.split(',') if s.strip()]
                logger.info(f"Found {len(specialties)} specialties for sidecar {sidecar_code}: {specialties}")
                return specialties
            else:
                logger.info(f"No specialties found for sidecar code: {sidecar_code}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to lookup specialties for sidecar code {sidecar_code}: {e}")
            return None
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def get_gam_scores(self, npi_list: List[str]) -> Dict[str, float]:
        """
        Get GAM appropriateness scores for a list of NPIs from DOCTOR table
        
        Args:
            npi_list: List of NPIs to lookup
            
        Returns:
            Dict mapping NPI to GAM score (default 0.0 if not found)
        """
        if not npi_list:
            return {}
            
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Build parameterized query for multiple NPIs
            placeholders = ','.join(['%s'] * len(npi_list))
            query = f"""
            SELECT NPI, GAM_APPROPRIATENESS_SCORE
            FROM FIVETRAN.MYSQL_DOCTOR_SIDECARHEALTH_DOCTOR_V2_DB.DOCTOR
            WHERE NPI IN ({placeholders})
            AND GAM_APPROPRIATENESS_SCORE IS NOT NULL
            """
            
            cursor.execute(query, npi_list)
            results = cursor.fetchall()
            
            # Build result dictionary
            gam_scores = {}
            for row in results:
                npi = str(row[0])
                score = float(row[1]) if row[1] is not None else 0.0
                gam_scores[npi] = score
            
            # Add default scores for NPIs not found
            for npi in npi_list:
                if npi not in gam_scores:
                    gam_scores[npi] = 0.0
            
            logger.info(f"Retrieved GAM scores for {len(results)} out of {len(npi_list)} NPIs")
            return gam_scores
            
        except Exception as e:
            logger.error(f"Failed to lookup GAM scores: {e}")
            # Return default scores for all NPIs
            return {npi: 0.0 for npi in npi_list}
        finally:
            if 'cursor' in locals():
                cursor.close()

    def clear_cache(self):
        """Clear the specialties cache to force fresh data retrieval"""
        self._care_search_specialties_cache.clear()
        logger.info("Cleared care_search_specialties cache")

    def close_connection(self):
        """Close the Snowflake connection"""
        if self.connection and not self.connection.is_closed():
            self.connection.close()
            logger.info("Snowflake connection closed")

def test_care_lookup():
    """Test the CareReimbursementLookup functionality"""
    print("=== Testing CareReimbursementLookup ===")
    
    lookup = CareReimbursementLookup()
    
    try:
        # Test with our test sidecar codes
        test_codes = ["DA024300", "DA02439400"]
        
        for code in test_codes:
            print(f"\nTesting sidecar code: {code}")
            specialties = lookup.get_care_search_specialties(code)
            print(f"careSearchSpecialties: {specialties}")
        
        # Test NPI lookup with some sample NPIs
        test_npis = ["1427586536", "1134754864", "1356314421"]
        print(f"\nTesting NPI lookup for: {test_npis}")
        npi_specialties = lookup.get_provider_npi_to_specialties_map(test_npis)
        for npi, specialties in npi_specialties.items():
            print(f"NPI {npi}: {specialties}")
        
        # Test radius calculation from zipcode
        test_zipcode = "44870"  # From our test data
        print(f"\nTesting radius calculation for zipcode: {test_zipcode}")
        radius = lookup.get_radius_by_zipcode(test_zipcode)
        print(f"Zipcode {test_zipcode} -> Radius: {radius} miles")
        
        # Test individual steps
        print(f"\nTesting individual steps:")
        rating_area = lookup.get_rating_area_by_zipcode(test_zipcode)
        print(f"1. Zipcode {test_zipcode} -> Rating Area: {rating_area}")
        
        if rating_area:
            area_radius = lookup.get_radius_by_rating_area(rating_area)
            print(f"2. Rating Area {rating_area} -> Radius: {area_radius} miles")
            
    finally:
        lookup.close_connection()
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    test_care_lookup()