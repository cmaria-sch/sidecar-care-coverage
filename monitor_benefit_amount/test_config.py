#!/usr/bin/env python3
"""
Test script for centralized configuration
"""

from config import config, Environment, Config
from ProviderPriceInformation import ProviderPriceInformation
import os

def test_config():
    """Test centralized configuration functionality"""
    print("=== Testing Centralized Configuration ===")
    print(f"Current Environment: {config.environment.value}")
    print()
    
    # Test Elasticsearch config
    print("1. Elasticsearch Configuration:")
    es_config = config.get_elasticsearch_config()
    print(f"   Endpoint: {es_config.endpoint}")
    print(f"   Region: {es_config.region}")
    print(f"   Use AWS Auth: {es_config.use_aws_auth}")
    print(f"   Index Name: {es_config.index_name}")
    print(f"   Max Results: {es_config.max_results}")
    print()
    
    # Test Snowflake config
    print("2. Snowflake Configuration:")
    sf_config = config.get_snowflake_config()
    print(f"   Database: {sf_config.database}")
    print(f"   Schema: {sf_config.schema}")
    print(f"   Warehouse: {sf_config.warehouse}")
    print(f"   Account: {sf_config.account}")
    print(f"   Role: {sf_config.role}")
    print()
    
    # Test API config
    print("3. API Configuration:")
    api_config = config.get_api_config()
    print(f"   Base URL: {api_config.base_url}")
    print(f"   Auth Endpoint: {api_config.auth_endpoint}")
    print(f"   Doctors Endpoint: {api_config.doctors_endpoint}")
    print(f"   Full Doctors URL: {config.get_full_api_url(api_config.doctors_endpoint)}")
    print()
    
    # Test default search params
    print("4. Default Search Parameters:")
    search_params = config.get_default_search_params()
    print(f"   Default Radius: {search_params.radius} miles")
    print(f"   Page Size: {search_params.page_size}")
    print(f"   Max Providers: {search_params.max_providers}")
    print(f"   Default Specialties Count: {len(search_params.default_specialties)}")
    print()
    
    # Test ProviderPriceInformation with config
    print("5. Testing ProviderPriceInformation with Config:")
    try:
        provider_service = ProviderPriceInformation()
        print(f"   ✅ Provider service initialized successfully")
        print(f"   ES Endpoint: {provider_service.es_endpoint}")
        print(f"   Index Name: {provider_service.index_name}")
        print(f"   Max Results: {provider_service.max_results}")
        print(f"   Use AWS Auth: {provider_service.use_aws_auth}")
    except Exception as e:
        print(f"   ❌ Failed to initialize provider service: {e}")
    print()
    
    # Test environment variable override
    print("6. Testing Environment Variable Override:")
    original_env = os.getenv('ENVIRONMENT')
    
    # Test staging environment
    os.environ['ENVIRONMENT'] = 'staging'
    staging_config = Config.from_environment_var()
    print(f"   Staging Database: {staging_config.get_snowflake_config().database}")
    
    # Test prod environment
    os.environ['ENVIRONMENT'] = 'prod'
    prod_config = Config.from_environment_var()
    print(f"   Prod Database: {prod_config.get_snowflake_config().database}")
    
    # Restore original environment
    if original_env:
        os.environ['ENVIRONMENT'] = original_env
    elif 'ENVIRONMENT' in os.environ:
        del os.environ['ENVIRONMENT']
    
    print()
    print("=== Configuration Test Complete ===")

if __name__ == "__main__":
    test_config()