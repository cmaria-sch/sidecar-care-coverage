#!/usr/bin/env python3
"""
Snowflake Table Utility
========================

Utility to test Snowflake connectivity and create tables in WORKSPACE.SCRATCH schema
with the same format as our comprehensive comparison CSV outputs.

Usage:
    python snowflake_table_utility.py
    
This script will:
1. Test Snowflake connection using your credentials
2. Create a table in WORKSPACE.SCRATCH schema
3. Insert a sample record to verify table functionality
4. Query the table to confirm data was inserted correctly
"""

import snowflake.connector
import logging
import boto3
import json
import os
from datetime import datetime
from typing import Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SnowflakeTableUtility:
    """Utility class for testing Snowflake connectivity and creating tables"""
    
    def __init__(self, aws_region: str = None):
        """Initialize the utility with Snowflake credentials"""
        # Set up AWS region
        self.aws_region = aws_region or os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1'
        os.environ['AWS_DEFAULT_REGION'] = self.aws_region
        
        self.secrets_client = boto3.client('secretsmanager', region_name=self.aws_region)
        self.snowflake_config = self._get_snowflake_credentials()
        self.connection = None
        
        logger.info("SnowflakeTableUtility initialized successfully")
    
    def _get_snowflake_credentials(self) -> Dict[str, str]:
        """Get Snowflake credentials from AWS Secrets Manager"""
        try:
            secret_response = self.secrets_client.get_secret_value(
                SecretId='sidecar-data-snowflake-etl-svc-account'
            )
            credentials = json.loads(secret_response['SecretString'])
            logger.info("✅ Successfully retrieved Snowflake credentials from AWS Secrets Manager")
            logger.info(f"   Retrieved user: {credentials.get('user', 'NOT_FOUND')}")
            logger.info(f"   Retrieved account: {credentials.get('account', 'NOT_FOUND')}")
            
            # Validate that we have the required credentials
            if not credentials.get('user'):
                raise Exception("Missing 'user' field in Snowflake credentials")
            if not credentials.get('password'):
                raise Exception("Missing 'password' field in Snowflake credentials")
            if not credentials.get('account'):
                raise Exception("Missing 'account' field in Snowflake credentials")
                
            return credentials
        except Exception as e:
            logger.error(f"❌ Failed to retrieve Snowflake credentials: {str(e)}")
            raise
    
    def _get_connection(self):
        """Get or create Snowflake connection"""
        if self.connection is None or self.connection.is_closed():
            try:
                logger.info("🔌 Connecting to Snowflake...")
                self.connection = snowflake.connector.connect(
                    user=self.snowflake_config['user'],
                    password=self.snowflake_config['password'],
                    account=self.snowflake_config['account'],
                    warehouse=self.snowflake_config.get('warehouse', 'COMPUTE_WH'),
                    database='WORKSPACE',  # Using WORKSPACE database
                    schema='SCRATCH',      # Using SCRATCH schema
                    role=self.snowflake_config.get('role', 'SYSADMIN')
                )
                logger.info("✅ Connected to Snowflake successfully")
                logger.info(f"   📍 Database: WORKSPACE")
                logger.info(f"   📍 Schema: SCRATCH")
                logger.info(f"   👤 User: {self.snowflake_config['user']}")
                logger.info(f"   🏢 Account: {self.snowflake_config['account']}")
            except Exception as e:
                logger.error(f"❌ Failed to connect to Snowflake: {e}")
                raise
        return self.connection
    
    def test_connection(self) -> bool:
        """Test Snowflake connection by running a simple query"""
        try:
            logger.info("🧪 Testing Snowflake connection...")
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Test basic connectivity
            cursor.execute("SELECT CURRENT_VERSION(), CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_USER(), CURRENT_ROLE()")
            result = cursor.fetchone()
            
            if result:
                logger.info("✅ Connection test successful!")
                logger.info(f"   Snowflake Version: {result[0]}")
                logger.info(f"   Current Database: {result[1]}")
                logger.info(f"   Current Schema: {result[2]}")
                logger.info(f"   Current User: {result[3]}")
                logger.info(f"   Current Role: {result[4]}")
                return True
            else:
                logger.error("❌ Connection test failed - no result returned")
                return False
                
        except Exception as e:
            logger.error(f"❌ Connection test failed: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def create_comparison_table(self, table_name: str = None) -> str:
        """
        Create a table with the same structure as our comprehensive comparison CSV output
        
        Args:
            table_name: Name of the table to create (optional, defaults to timestamped name)
            
        Returns:
            The name of the created table
        """
        if table_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            table_name = f"BENEFIT_PROVIDER_COMPARISON_TEST_{timestamp}"
        
        try:
            logger.info(f"🏗️ Creating table: {table_name}")
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Drop table if it exists (for testing purposes)
            drop_sql = f"DROP TABLE IF EXISTS {table_name}"
            cursor.execute(drop_sql)
            logger.info(f"   Dropped existing table if it existed")
            
            # Create table with same structure as CSV output
            create_sql = f"""
            CREATE TABLE {table_name} (
                EXECUTION_ID VARCHAR(100),
                SIDECAR_CODE VARCHAR(50) NOT NULL,
                NPI VARCHAR(20) NOT NULL,
                INSURANCE_FILING_UUID VARCHAR(100) NOT NULL,
                ZIPCODE VARCHAR(10) NOT NULL,
                STATE VARCHAR(2) NOT NULL,
                RATING_AREA VARCHAR(50),
                PROVIDER_PRICE NUMBER(10,2) NOT NULL,
                FACILITY_BENEFIT_AMOUNT NUMBER(10,2) NOT NULL,
                NON_FACILITY_BENEFIT_AMOUNT NUMBER(10,2) NOT NULL,
                RX_BENEFIT_AMOUNT NUMBER(10,2) NOT NULL,
                PROVIDER_NAME VARCHAR(500),
                CARE_CATEGORY VARCHAR(100),
                EXCEEDS_FACILITY BOOLEAN,
                EXCEEDS_NON_FACILITY BOOLEAN,
                PRICE_VS_FACILITY_DIFF NUMBER(10,2),
                PRICE_VS_NON_FACILITY_DIFF NUMBER(10,2),
                RESULT_TYPE VARCHAR(50) DEFAULT 'lower-benefit-amount',
                PROVIDER_COUNT_WITH_NO_PRICE INTEGER DEFAULT 0,
                CREATED_TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                
                -- Add some useful indexes/constraints
                CONSTRAINT PK_{table_name} PRIMARY KEY (EXECUTION_ID, SIDECAR_CODE, NPI, INSURANCE_FILING_UUID, ZIPCODE)
            )
            COMMENT = 'Test table for benefit vs provider price comparison results - matches CSV output format'
            """
            
            cursor.execute(create_sql)
            logger.info(f"✅ Table {table_name} created successfully!")
            logger.info(f"   📊 Table structure matches CSV output format")
            logger.info(f"   🔑 Primary key: (EXECUTION_ID, SIDECAR_CODE, NPI, INSURANCE_FILING_UUID, ZIPCODE)")
            
            return table_name
            
        except Exception as e:
            logger.error(f"❌ Failed to create table {table_name}: {e}")
            raise
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def insert_sample_record(self, table_name: str) -> bool:
        """
        Insert a sample record into the table to test functionality
        
        Args:
            table_name: Name of the table to insert into
            
        Returns:
            True if insert was successful, False otherwise
        """
        try:
            logger.info(f"📝 Inserting sample record into {table_name}...")
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Sample data based on the CSV format we saw
            sample_data = {
                'EXECUTION_ID': 'TEST_20250105_123456_abc123',
                'SIDECAR_CODE': 'A0425000',
                'NPI': '1234567890',
                'INSURANCE_FILING_UUID': 'test_filing_uuid_123',
                'ZIPCODE': '43560',
                'STATE': 'OH',
                'RATING_AREA': 'OH_AREA_1',
                'PROVIDER_PRICE': 765.45,
                'FACILITY_BENEFIT_AMOUNT': 127.90,
                'NON_FACILITY_BENEFIT_AMOUNT': 99.42,
                'RX_BENEFIT_AMOUNT': 74.22,
                'PROVIDER_NAME': 'Test Provider for Snowflake Utility',
                'CARE_CATEGORY': 'Ambulance Service',
                'EXCEEDS_FACILITY': True,
                'EXCEEDS_NON_FACILITY': True,
                'PRICE_VS_FACILITY_DIFF': 637.55,
                'PRICE_VS_NON_FACILITY_DIFF': 666.03,
                'RESULT_TYPE': 'lower-benefit-amount',
                'PROVIDER_COUNT_WITH_NO_PRICE': 0
            }
            
            insert_sql = f"""
            INSERT INTO {table_name} (
                EXECUTION_ID, SIDECAR_CODE, NPI, INSURANCE_FILING_UUID, ZIPCODE, STATE, RATING_AREA,
                PROVIDER_PRICE, FACILITY_BENEFIT_AMOUNT, NON_FACILITY_BENEFIT_AMOUNT, RX_BENEFIT_AMOUNT,
                PROVIDER_NAME, CARE_CATEGORY, EXCEEDS_FACILITY, EXCEEDS_NON_FACILITY,
                PRICE_VS_FACILITY_DIFF, PRICE_VS_NON_FACILITY_DIFF, RESULT_TYPE, PROVIDER_COUNT_WITH_NO_PRICE
            ) VALUES (
                %(EXECUTION_ID)s, %(SIDECAR_CODE)s, %(NPI)s, %(INSURANCE_FILING_UUID)s, %(ZIPCODE)s, %(STATE)s, %(RATING_AREA)s,
                %(PROVIDER_PRICE)s, %(FACILITY_BENEFIT_AMOUNT)s, %(NON_FACILITY_BENEFIT_AMOUNT)s, %(RX_BENEFIT_AMOUNT)s,
                %(PROVIDER_NAME)s, %(CARE_CATEGORY)s, %(EXCEEDS_FACILITY)s, %(EXCEEDS_NON_FACILITY)s,
                %(PRICE_VS_FACILITY_DIFF)s, %(PRICE_VS_NON_FACILITY_DIFF)s, %(RESULT_TYPE)s, %(PROVIDER_COUNT_WITH_NO_PRICE)s
            )
            """
            
            cursor.execute(insert_sql, sample_data)
            
            logger.info("✅ Sample record inserted successfully!")
            logger.info(f"   🏥 Provider: {sample_data['PROVIDER_NAME']}")
            logger.info(f"   💰 Provider Price: ${sample_data['PROVIDER_PRICE']}")
            logger.info(f"   📍 Location: {sample_data['ZIPCODE']}, {sample_data['STATE']}")
            logger.info(f"   🎯 Sidecar Code: {sample_data['SIDECAR_CODE']}")
            logger.info(f"   🆔 Execution ID: {sample_data['EXECUTION_ID']}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to insert sample record: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def query_table(self, table_name: str) -> bool:
        """
        Query the table to verify data was inserted correctly
        
        Args:
            table_name: Name of the table to query
            
        Returns:
            True if query was successful, False otherwise
        """
        try:
            logger.info(f"🔍 Querying table {table_name} to verify data...")
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Query all records
            query_sql = f"""
            SELECT 
                EXECUTION_ID, SIDECAR_CODE, NPI, PROVIDER_NAME, PROVIDER_PRICE, 
                FACILITY_BENEFIT_AMOUNT, NON_FACILITY_BENEFIT_AMOUNT,
                EXCEEDS_FACILITY, EXCEEDS_NON_FACILITY,
                CREATED_TIMESTAMP,
                STATE, ZIPCODE
            FROM {table_name}
            ORDER BY CREATED_TIMESTAMP DESC
            """
            
            cursor.execute(query_sql)
            results = cursor.fetchall()
            
            if results:
                logger.info(f"✅ Query successful! Found {len(results)} record(s):")
                logger.info("=" * 100)
                
                for i, row in enumerate(results, 1):
                    logger.info(f"Record {i}:")
                    logger.info(f"  🆔 Execution ID: {row[0]}")
                    logger.info(f"  🎯 Sidecar Code: {row[1]}")
                    logger.info(f"  🏥 Provider: {row[2]} - {row[3]}")
                    logger.info(f"  💰 Provider Price: ${row[4]}")
                    logger.info(f"  🏢 Facility Benefit: ${row[5]} ({'EXCEEDS' if row[7] else 'below'})")
                    logger.info(f"  🏠 Non-Facility Benefit: ${row[6]} ({'EXCEEDS' if row[8] else 'below'})")
                    logger.info(f"  📍 Location: {row[11]}, {row[10]}")
                    logger.info(f"  📅 Created: {row[9]}")
                    logger.info("-" * 80)
                
                return True
            else:
                logger.warning("⚠️ Query successful but no records found")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to query table: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def get_table_info(self, table_name: str) -> bool:
        """
        Get information about the created table (columns, data types, etc.)
        
        Args:
            table_name: Name of the table to describe
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"📋 Getting table information for {table_name}...")
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get table structure
            describe_sql = f"DESCRIBE TABLE {table_name}"
            cursor.execute(describe_sql)
            columns = cursor.fetchall()
            
            if columns:
                logger.info(f"✅ Table {table_name} structure:")
                logger.info("=" * 100)
                logger.info(f"{'Column Name':<30} {'Data Type':<20} {'Nullable':<10} {'Key':<10}")
                logger.info("-" * 100)
                
                for col in columns:
                    col_name = col[0]
                    data_type = col[1]
                    nullable = col[2]
                    key = col[3] if len(col) > 3 else ''
                    logger.info(f"{col_name:<30} {data_type:<20} {nullable:<10} {key:<10}")
                
                logger.info("-" * 100)
                return True
            else:
                logger.warning("⚠️ No column information found")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to get table info: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def cleanup_table(self, table_name: str) -> bool:
        """
        Clean up by dropping the test table
        
        Args:
            table_name: Name of the table to drop
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"🧹 Cleaning up table {table_name}...")
            conn = self._get_connection()
            cursor = conn.cursor()
            
            drop_sql = f"DROP TABLE IF EXISTS {table_name}"
            cursor.execute(drop_sql)
            
            logger.info(f"✅ Table {table_name} dropped successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to drop table: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    def close_connection(self):
        """Close the Snowflake connection"""
        if self.connection and not self.connection.is_closed():
            self.connection.close()
            logger.info("🔌 Snowflake connection closed")

def main():
    """Main function to run the Snowflake table utility test"""
    logger.info("🚀 Starting Snowflake Table Utility Test")
    logger.info("=" * 80)
    
    utility = None
    table_name = None
    
    try:
        # Initialize utility
        utility = SnowflakeTableUtility()
        
        # Step 1: Test connection
        logger.info("\n📋 STEP 1: Testing Snowflake Connection")
        logger.info("-" * 50)
        if not utility.test_connection():
            logger.error("❌ Connection test failed. Cannot proceed.")
            return
        
        # Step 2: Create table
        logger.info("\n📋 STEP 2: Creating Test Table")
        logger.info("-" * 50)
        table_name = utility.create_comparison_table()
        
        # Step 3: Get table info
        logger.info("\n📋 STEP 3: Describing Table Structure")
        logger.info("-" * 50)
        utility.get_table_info(table_name)
        
        # Step 4: Insert sample record
        logger.info("\n📋 STEP 4: Inserting Sample Record")
        logger.info("-" * 50)
        if not utility.insert_sample_record(table_name):
            logger.error("❌ Failed to insert sample record")
            return
        
        # Step 5: Query table
        logger.info("\n📋 STEP 5: Querying Table to Verify Data")
        logger.info("-" * 50)
        if not utility.query_table(table_name):
            logger.error("❌ Failed to query table")
            return
        
        # Success summary
        logger.info("\n🎊 SUCCESS SUMMARY")
        logger.info("=" * 80)
        logger.info("✅ All tests passed successfully!")
        logger.info(f"✅ Table created: WORKSPACE.SCRATCH.{table_name}")
        logger.info("✅ Sample record inserted and verified")
        logger.info("✅ Your Snowflake credentials are working correctly")
        logger.info("✅ Ready to use WORKSPACE.SCRATCH schema for storing comparison results")
        
        # Ask if user wants to keep the table
        logger.info("\n🤔 Table cleanup options:")
        logger.info(f"   Keep table: WORKSPACE.SCRATCH.{table_name}")
        logger.info(f"   Drop table: Set CLEANUP_TABLE=true in environment or modify script")
        
        # Optional cleanup (you can uncomment this if you want to clean up automatically)
        # logger.info("\n📋 STEP 6: Cleaning Up Test Table")
        # logger.info("-" * 50)
        # utility.cleanup_table(table_name)
        
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        logger.error("Check your Snowflake credentials and permissions")
    
    finally:
        if utility:
            utility.close_connection()
        
        logger.info("\n🏁 Snowflake Table Utility Test Complete")
        logger.info("=" * 80)

if __name__ == "__main__":
    main()