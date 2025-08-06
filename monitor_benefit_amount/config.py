#!/usr/bin/env python3
"""
Centralized Configuration for Sidecar Care Coverage Analysis

This module provides centralized configuration settings for:
- Elasticsearch endpoints
- Snowflake database connections  
- API endpoints
- Authentication settings
- Default parameters

All components should use this config instead of hardcoded values.
"""

import os
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

class Environment(Enum):
    """Environment types"""
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

@dataclass
class ElasticsearchConfig:
    """Elasticsearch configuration"""
    endpoint: str
    region: str = "us-east-1"
    use_aws_auth: bool = True
    index_name: str = "doctors"
    max_results: int = 100
    timeout: int = 60

@dataclass
class SnowflakeConfig:
    """Snowflake database configuration"""
    account: str
    warehouse: str
    database: str
    schema: str
    role: str
    user: Optional[str] = None
    password: Optional[str] = None
    authenticator: str = "externalbrowser"

@dataclass
class APIConfig:
    """API endpoint configuration"""
    base_url: str
    auth_endpoint: str
    doctors_endpoint: str
    timeout: int = 30

@dataclass
class DefaultSearchParams:
    """Default search parameters"""
    radius: float = 8.0
    page_size: int = 25
    max_providers: int = 50
    default_specialties: list = None
    
    def __post_init__(self):
        if self.default_specialties is None:
            self.default_specialties = [
                "Other clinic/center",
                "General practice", 
                "Family medicine",
                "Rural health center",
                "Internal medicine"
            ]

class Config:
    """
    Centralized configuration class for all application settings
    
    Usage:
        from config import Config
        config = Config()
        es_config = config.get_elasticsearch_config()
        sf_config = config.get_snowflake_config()
    """
    
    def __init__(self, environment: Environment = Environment.DEV):
        self.environment = environment
        
        # Define configurations for each environment
        self._configs = {
            Environment.DEV: {
                'elasticsearch': ElasticsearchConfig(
                    endpoint="https://vpc-sidecar-api-doctor-gxax5tlshqikfefzncefjs4ubi.us-east-1.es.amazonaws.com",
                    # endpoint="https://vpc-sidecar-api-doctor-qs6ui43nmfbojouwtj4cpqzea4.us-east-1.es.amazonaws.com",
                    region="us-east-1",
                    use_aws_auth=False,  # Dev ES doesn't require AWS auth
                    index_name="doctors",
                    max_results=100,
                    timeout=60
                ),
                'snowflake': SnowflakeConfig(
                    account=os.getenv('SNOWFLAKE_ACCOUNT', 'gp27715.us-east-1'),
                    warehouse=os.getenv('SNOWFLAKE_WAREHOUSE', 'SIDECAR_CARE_WH'),
                    database=os.getenv('SNOWFLAKE_DATABASE', 'SIDECAR_CARE_DEV_DB'),
                    schema='MYSQL_CARE_SIDECARHEALTH_CARE_DB',
                    role=os.getenv('SNOWFLAKE_ROLE', 'SIDECAR_CARE_DATA_ENGINEER'),
                    authenticator="externalbrowser"
                ),
                'api': APIConfig(
                    base_url="https://dev-api.sidecarhealth.com",
                    auth_endpoint="/auth/v1/login?type=password",
                    doctors_endpoint="/doc/v2/rates/cares/doctors",
                    timeout=30
                )
            },
            Environment.STAGING: {
                'elasticsearch': ElasticsearchConfig(
                    endpoint="https://vpc-sidecar-staging-qs6ui43nmfbojouwtj4cpqzea4.us-east-1.es.amazonaws.com",  # Placeholder
                    region="us-east-1",
                    use_aws_auth=True,
                    index_name="doctors",
                    max_results=100,
                    timeout=60
                ),
                'snowflake': SnowflakeConfig(
                    account=os.getenv('SNOWFLAKE_ACCOUNT', 'gp27715.us-east-1'),
                    warehouse=os.getenv('SNOWFLAKE_WAREHOUSE', 'SIDECAR_CARE_WH'),
                    database=os.getenv('SNOWFLAKE_DATABASE', 'SIDECAR_CARE_STAGING_DB'),
                    schema='MYSQL_CARE_SIDECARHEALTH_CARE_DB',
                    role=os.getenv('SNOWFLAKE_ROLE', 'SIDECAR_CARE_DATA_ENGINEER'),
                    authenticator="externalbrowser"
                ),
                'api': APIConfig(
                    base_url="https://staging-api.sidecarhealth.com",  # Placeholder
                    auth_endpoint="/auth/v1/login?type=password",
                    doctors_endpoint="/doc/v2/rates/cares/doctors",
                    timeout=30
                )
            },
            Environment.PROD: {
                'elasticsearch': ElasticsearchConfig(
                    endpoint="https://vpc-sidecar-prod-qs6ui43nmfbojouwtj4cpqzea4.us-east-1.es.amazonaws.com",  # Placeholder
                    region="us-east-1",
                    use_aws_auth=True,
                    index_name="doctors",
                    max_results=100,
                    timeout=60
                ),
                'snowflake': SnowflakeConfig(
                    account=os.getenv('SNOWFLAKE_ACCOUNT', 'gp27715.us-east-1'),
                    warehouse=os.getenv('SNOWFLAKE_WAREHOUSE', 'SIDECAR_CARE_WH'),
                    database=os.getenv('SNOWFLAKE_DATABASE', 'SIDECAR_CARE_PROD_DB'),
                    schema='MYSQL_CARE_SIDECARHEALTH_CARE_DB',
                    role=os.getenv('SNOWFLAKE_ROLE', 'SIDECAR_CARE_DATA_ENGINEER'),
                    authenticator="externalbrowser"
                ),
                'api': APIConfig(
                    base_url="https://api.sidecarhealth.com",  # Placeholder
                    auth_endpoint="/auth/v1/login?type=password", 
                    doctors_endpoint="/doc/v2/rates/cares/doctors",
                    timeout=30
                )
            }
        }
        
        # Default search parameters (environment-independent)
        self.default_search_params = DefaultSearchParams()
    
    def get_elasticsearch_config(self) -> ElasticsearchConfig:
        """Get Elasticsearch configuration for current environment"""
        return self._configs[self.environment]['elasticsearch']
    
    def get_snowflake_config(self) -> SnowflakeConfig:
        """Get Snowflake configuration for current environment"""
        return self._configs[self.environment]['snowflake']
    
    def get_api_config(self) -> APIConfig:
        """Get API configuration for current environment"""
        return self._configs[self.environment]['api']
    
    def get_default_search_params(self) -> DefaultSearchParams:
        """Get default search parameters"""
        return self.default_search_params
    
    def get_full_api_url(self, endpoint: str = None) -> str:
        """Get full API URL for specific endpoint"""
        api_config = self.get_api_config()
        if endpoint:
            return f"{api_config.base_url}{endpoint}"
        return api_config.base_url
    
    def get_snowflake_connection_params(self) -> Dict[str, Any]:
        """Get Snowflake connection parameters as dict"""
        sf_config = self.get_snowflake_config()
        params = {
            'account': sf_config.account,
            'warehouse': sf_config.warehouse,
            'database': sf_config.database,
            'schema': sf_config.schema,
            'role': sf_config.role,
            'authenticator': sf_config.authenticator
        }
        
        # Add user/password if provided
        if sf_config.user:
            params['user'] = sf_config.user
        if sf_config.password:
            params['password'] = sf_config.password
            
        return params
    
    @classmethod
    def from_environment_var(cls) -> 'Config':
        """Create config from ENVIRONMENT environment variable"""
        env_name = os.getenv('ENVIRONMENT', 'dev').lower()
        try:
            environment = Environment(env_name)
        except ValueError:
            # Default to dev if invalid environment
            environment = Environment.DEV
        return cls(environment)

# Global config instance - use this in your modules
# You can override by setting ENVIRONMENT environment variable
config = Config.from_environment_var()

# Convenience functions for backward compatibility
def get_elasticsearch_endpoint() -> str:
    """Get Elasticsearch endpoint URL"""
    return config.get_elasticsearch_config().endpoint

def get_snowflake_database() -> str:
    """Get Snowflake database name"""
    return config.get_snowflake_config().database

def get_api_base_url() -> str:
    """Get API base URL"""
    return config.get_api_config().base_url

# Example usage:
if __name__ == "__main__":
    print("=== Sidecar Care Configuration ===")
    print(f"Environment: {config.environment.value}")
    print()
    
    print("Elasticsearch Config:")
    es_config = config.get_elasticsearch_config()
    print(f"  Endpoint: {es_config.endpoint}")
    print(f"  Region: {es_config.region}")
    print(f"  Use AWS Auth: {es_config.use_aws_auth}")
    print(f"  Index: {es_config.index_name}")
    print()
    
    print("Snowflake Config:")
    sf_config = config.get_snowflake_config()
    print(f"  Database: {sf_config.database}")
    print(f"  Schema: {sf_config.schema}")
    print(f"  Warehouse: {sf_config.warehouse}")
    print()
    
    print("API Config:")
    api_config = config.get_api_config()
    print(f"  Base URL: {api_config.base_url}")
    print(f"  Doctors Endpoint: {api_config.base_url}{api_config.doctors_endpoint}")
    print()
    
    print("Default Search Params:")
    search_params = config.get_default_search_params()
    print(f"  Default Radius: {search_params.radius} miles")
    print(f"  Page Size: {search_params.page_size}")
    print(f"  Max Providers: {search_params.max_providers}")
    print(f"  Default Specialties: {len(search_params.default_specialties)} configured")