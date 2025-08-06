#!/usr/bin/env python3
"""
ProviderPriceInformation - Elasticsearch client for fetching provider/doctor information
with business logic filtering and sorting based on specialty matches and pricing
"""

import requests
import json
import logging
from typing import List, Optional, Dict, Any
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from config import config
from snowflake_care_lookup import CareReimbursementLookup

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProviderPriceInformation:
    """
    Provider price information service that fetches doctors from Elasticsearch
    and applies business logic filtering and sorting
    """

    def __init__(self, es_endpoint: str = None, region: str = None, use_aws_auth: bool = None,
                 index_name: str = None, max_results: int = None, enable_snowflake_filtering: bool = True):
        # Use centralized config as defaults
        es_config = config.get_elasticsearch_config()

        self.es_endpoint = (es_endpoint or es_config.endpoint).rstrip('/')
        self.region = region or es_config.region
        self.use_aws_auth = use_aws_auth if use_aws_auth is not None else es_config.use_aws_auth
        self.index_name = index_name or es_config.index_name
        self.max_results = max_results or es_config.max_results
        self.session = requests.Session()

        # Initialize Snowflake lookup for Java-matching specialty filtering
        self.care_lookup = None
        self.enable_snowflake_filtering = enable_snowflake_filtering
        if enable_snowflake_filtering:
            try:
                self.care_lookup = CareReimbursementLookup()
                # Clear any cached data to ensure we get fresh data with our fix
                if hasattr(self.care_lookup, 'clear_cache'):
                    self.care_lookup.clear_cache()
                logger.info("Snowflake CareReimbursementLookup initialized successfully with cleared cache")
            except Exception as e:
                logger.warning(f"Failed to initialize Snowflake lookup: {e}. Will use ES-only filtering.")
                self.care_lookup = None

        # Set up AWS authentication if needed
        if self.use_aws_auth:
            self.credentials = boto3.Session().get_credentials()

        # Common headers
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _sign_request(self, method: str, url: str, body: str = None) -> Dict[str, str]:
        """
        Sign request with AWS SigV4 for AWS Elasticsearch Service
        """
        if not self.use_aws_auth or not self.credentials:
            return self.headers

        request = AWSRequest(method=method, url=url, data=body, headers=self.headers)
        SigV4Auth(self.credentials, 'es', self.region).add_auth(request)
        return dict(request.headers)

    def _make_es_request(self, method: str, endpoint: str, body: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make HTTP request to Elasticsearch with comprehensive logging
        """
        url = f"{self.es_endpoint}{endpoint}"
        json_body = json.dumps(body) if body else None

        # Sign request if using AWS auth
        headers = self._sign_request(method, url, json_body)

        # Console print ES queries for debugging
        print(f"\n🔍 ELASTICSEARCH QUERY:")
        print(f"📍 URL: {method} {url}")
        if body:
            print(f"📋 Query Body:")
            print(json.dumps(body, indent=2))
        print("="*60)

        # Basic request logging
        logger.debug(f"ES {method} request to {endpoint}")

        try:
            response = self.session.request(
                method=method,
                url=url,
                data=json_body,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()

            response_data = response.json()

            # Console print ES response summary
            total_hits = 0
            if 'hits' in response_data and 'total' in response_data['hits']:
                if isinstance(response_data['hits']['total'], dict):
                    total_hits = response_data['hits']['total'].get('value', 0)
                else:
                    total_hits = response_data['hits']['total']
            
            print(f"✅ ES Response: {response.status_code} | Total hits: {total_hits}")
            print("="*60)

            # Basic response logging
            logger.debug(f"ES response: {response.status_code}")

            return response_data

        except requests.exceptions.RequestException as e:
            logger.error(f"Elasticsearch request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response content: {e.response.text}")
            raise

    def _build_sidecar_query(self, sidecar_code: str, lat: Optional[float],
                             lon: Optional[float], radius: Optional[float]) -> Dict[str, Any]:
        """
        Build Elasticsearch query for sidecar code search only
        """
        query = {
            "from": 0,
            "size": self.max_results,
            "timeout": "60s",
            "min_score": 1.0,
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "careRates.sidecarCode": sidecar_code.strip().upper()
                            }
                        }
                    ]
                }
            }
        }

        # Add geo and practice location filters
        filter_queries = []
        if lat is not None and lon is not None:
            # Radius must be provided when using geo coordinates
            if radius is None:
                raise ValueError("Radius must be provided when using geo coordinates")
            filter_queries.append({
                "geo_distance": {
                    "distance": f"{radius}mi",
                    "geoCoordinates": {
                        "lat": lat,
                        "lon": lon
                    }
                }
            })

        # filter_queries.append({
        #     "exists": {
        #         "field": "practiceLocations"
        #     }
        # })

        if filter_queries:
            query["query"]["bool"]["filter"] = filter_queries

        return query

    def _build_specialties_query(self, specialties: List[str], lat: Optional[float],
                                 lon: Optional[float], radius: Optional[float]) -> Dict[str, Any]:
        """
        Build Elasticsearch query for specialties search only
        """
        query = {
            "from": 0,
            "size": self.max_results,
            "timeout": "60s",
            "min_score": 1.0,
            "query": {
                "bool": {
                    "should": []
                }
            }
        }

        # Add specialty queries
        for specialty in specialties:
            if specialty.strip():
                query["query"]["bool"]["should"].append({
                    "match": {
                        "taxonomies.specialty": specialty.strip().lower()
                    }
                })

        # Set minimum should match to at least 1
        query["query"]["bool"]["minimum_should_match"] = 1

        # Add geo and practice location filters
        filter_queries = []
        if lat is not None and lon is not None:
            # Radius must be provided when using geo coordinates
            if radius is None:
                raise ValueError("Radius must be provided when using geo coordinates")
            filter_queries.append({
                "geo_distance": {
                    "distance": f"{radius}mi",
                    "geoCoordinates": {
                        "lat": lat,
                        "lon": lon
                    }
                }
            })

        # filter_queries.append({
        #     "exists": {
        #         "field": "practiceLocations"
        #     }
        # })

        if filter_queries:
            query["query"]["bool"]["filter"] = filter_queries

        return query

    def _build_elasticsearch_query(self, sidecar_code: Optional[str], specialties: Optional[List[str]],
                                   lat: Optional[float], lon: Optional[float], radius: Optional[float]) -> Dict[str, Any]:
        """
        Build Elasticsearch query combining sidecar code and specialties search (DEPRECATED - kept for compatibility)
        """
        query = {
            "from": 0,
            "size": self.max_results,
            "timeout": "60s",
            "min_score": 1.0,
            "query": {
                "bool": {}
            }
        }

        should_queries = []
        must_queries = []
        filter_queries = []

        # Add sidecar code query as must (required) if provided
        if sidecar_code and sidecar_code.strip():
            must_queries.append({
                "match": {
                    "careRates.sidecarCode": sidecar_code.strip().upper()
                }
            })

        # Add specialty queries as should (optional boost) if provided
        if specialties:
            for specialty in specialties:
                if specialty.strip():
                    should_queries.append({
                        "match": {
                            "taxonomies.specialty": specialty.strip().lower()
                        }
                    })

        # Add geo distance filter if coordinates provided
        if lat is not None and lon is not None:
            # Radius must be provided when using geo coordinates
            if radius is None:
                raise ValueError("Radius must be provided when using geo coordinates")
            filter_queries.append({
                "geo_distance": {
                    "distance": f"{radius}mi",
                    "geoCoordinates": {
                        "lat": lat,
                        "lon": lon
                    }
                }
            })

        # Always filter for existing practice locations
        # filter_queries.append({
        #     "exists": {
        #         "field": "practiceLocations"
        #     }
        # })

        # Build the bool query
        bool_query = {}
        if must_queries:
            bool_query["must"] = must_queries
        if should_queries:
            bool_query["should"] = should_queries
        if filter_queries:
            bool_query["filter"] = filter_queries

        if bool_query:
            query["query"]["bool"] = bool_query
        else:
            query["query"] = {"match_all": {}}

        logger.debug(f"Generated combined ES query")
        return query

    def _combine_and_deduplicate_results(self, sidecar_results: List[Dict[str, Any]],
                                         specialty_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Combine results from sidecar and specialty searches, removing duplicates
        """
        # Use provider ID to track duplicates
        seen_ids = set()
        combined_results = []

        # Add sidecar results first (higher priority)
        for provider in sidecar_results:
            provider_id = self._safe_get_provider_id(provider)
            if provider_id and provider_id not in seen_ids:
                # Mark as sidecar match for business logic
                provider['_source_type'] = 'sidecar'
                combined_results.append(provider)
                seen_ids.add(provider_id)

        # Add specialty results that aren't already included
        for provider in specialty_results:
            provider_id = self._safe_get_provider_id(provider)
            if provider_id and provider_id not in seen_ids:
                # Mark as specialty match for business logic
                provider['_source_type'] = 'specialty'
                combined_results.append(provider)
                seen_ids.add(provider_id)

        logger.info(f"Combined results: {len(sidecar_results)} sidecar + {len(specialty_results)} specialty = {len(combined_results)} unique providers")
        return combined_results

    def _build_combined_query(self, sidecar_code: Optional[str], specialties: Optional[List[str]],
                              lat: Optional[float], lon: Optional[float], radius: Optional[float]) -> Dict[str, Any]:
        """
        Build combined Elasticsearch query matching Java's specialties + sidecar query structure exactly
        """
        # Radius must be provided when using geo coordinates
        if radius is None:
            raise ValueError("Radius must be provided for geo search")
        radius_miles = radius
        radius_meters = radius_miles * 1609.344  # Match Java conversion precision

        query = {
            "from": 0,
            "size": 100,  # Keep at 100 as requested - will deduplicate after
            "timeout": "60s",  # Match Java timeout
            "query": {
                "bool": {
                    "filter": [],
                    "should": [],
                    "adjust_pure_negative": True,
                    "boost": 1.0
                }
            },
            "min_score": 1.0  # Match Java min_score requirement
        }

        # Add geo distance filter if coordinates provided
        if lat is not None and lon is not None:
            query["query"]["bool"]["filter"].append({
                "geo_distance": {
                    "geoCoordinates": [lon, lat],  # [longitude, latitude] format
                    "distance": radius_meters,
                    "distance_type": "arc",
                    "validation_method": "STRICT",
                    "ignore_unmapped": False,
                    "boost": 1.0
                }
            })

        # # Always add practice locations filter
        # query["query"]["bool"]["filter"].append({
        #     "exists": {
        #         "field": "practiceLocations",
        #         "boost": 1.0
        #     }
        # })

        # Add specialty should clauses first (matching Java order)
        if specialties:
            for specialty in specialties:
                if specialty.strip():
                    query["query"]["bool"]["should"].append({
                        "match": {
                            "taxonomies.specialty": {
                                "query": specialty.strip().lower(),
                                "operator": "OR",
                                "prefix_length": 0,
                                "max_expansions": 50,
                                "fuzzy_transpositions": True,
                                "lenient": False,
                                "zero_terms_query": "NONE",
                                "auto_generate_synonyms_phrase_query": True,
                                "boost": 1.0
                            }
                        }
                    })

        # Add sidecar code should clause last (matching Java order)
        if sidecar_code and sidecar_code.strip():
            query["query"]["bool"]["should"].append({
                "match": {
                    "careRates.sidecarCode": {
                        "query": sidecar_code.strip().upper(),
                        "operator": "OR",
                        "prefix_length": 0,
                        "max_expansions": 50,
                        "fuzzy_transpositions": True,
                        "lenient": False,
                        "zero_terms_query": "NONE",
                        "auto_generate_synonyms_phrase_query": True,
                        "boost": 1.0
                    }
                }
            })

        # Return empty results if no search criteria
        if not query["query"]["bool"]["should"]:
            logger.warning("No search criteria provided")
            return {"from": 0, "size": 0, "query": {"match_none": {}}}

        logger.debug(f"Generated combined ES query")
        return query

    def _build_specialties_only_query(self, specialties: List[str], sidecar_code: Optional[str],
                                      lat: Optional[float], lon: Optional[float], radius: Optional[float]) -> Dict[str, Any]:
        """
        Build specialties+sidecar Elasticsearch query (matching Java specialties query exactly - includes sidecar code)
        """
        # Radius must be provided when using geo coordinates
        if radius is None:
            raise ValueError("Radius must be provided for geo search")
        radius_miles = radius
        radius_meters = radius_miles * 1609.344  # Match Java conversion precision

        query = {
            "from": 0,
            "size": 100,  # Match Java query size
            "timeout": "60s",  # Match Java timeout
            "query": {
                "bool": {
                    "filter": [],
                    "should": [],
                    "adjust_pure_negative": True,
                    "boost": 1.0
                }
            },
            "min_score": 1.0  # Match Java min_score requirement
        }

        # Add geo distance filter if coordinates provided
        if lat is not None and lon is not None:
            query["query"]["bool"]["filter"].append({
                "geo_distance": {
                    "geoCoordinates": [lon, lat],  # [longitude, latitude] format
                    "distance": radius_meters,
                    "distance_type": "arc",
                    "validation_method": "STRICT",
                    "ignore_unmapped": False,
                    "boost": 1.0
                }
            })

        # # Always add practice locations filter
        # query["query"]["bool"]["filter"].append({
        #     "exists": {
        #         "field": "practiceLocations",
        #         "boost": 1.0
        #     }
        # })

        # Add specialty should clauses first (matching Java order)
        if specialties:
            for specialty in specialties:
                if specialty.strip():
                    query["query"]["bool"]["should"].append({
                        "match": {
                            "taxonomies.specialty": {
                                "query": specialty.strip().lower(),
                                "operator": "OR",
                                "prefix_length": 0,
                                "max_expansions": 50,
                                "fuzzy_transpositions": True,
                                "lenient": False,
                                "zero_terms_query": "NONE",
                                "auto_generate_synonyms_phrase_query": True,
                                "boost": 1.0
                            }
                        }
                    })

        # Add sidecar code should clause (matching Java specialties query exactly)
        if sidecar_code and sidecar_code.strip():
            query["query"]["bool"]["should"].append({
                "match": {
                    "careRates.sidecarCode": {
                        "query": sidecar_code.strip().upper(),
                        "operator": "OR",
                        "prefix_length": 0,
                        "max_expansions": 50,
                        "fuzzy_transpositions": True,
                        "lenient": False,
                        "zero_terms_query": "NONE",
                        "auto_generate_synonyms_phrase_query": True,
                        "boost": 1.0
                    }
                }
            })

        # Return empty results if no search criteria
        if not query["query"]["bool"]["should"]:
            logger.warning("No specialty search criteria provided")
            return {"from": 0, "size": 0, "query": {"match_none": {}}}

        logger.debug(f"Generated specialties+sidecar ES query")
        return query

    def _build_sidecar_only_query(self, sidecar_code: str, lat: Optional[float],
                                  lon: Optional[float], radius: Optional[float]) -> Dict[str, Any]:
        """
        Build sidecar-only Elasticsearch query (matching Java generateSidecarCodeOnlySearchRequest exactly)
        """
        # Radius must be provided when using geo coordinates
        if radius is None:
            raise ValueError("Radius must be provided for geo search")
        radius_miles = radius
        # Use exact Java conversion to meters
        radius_meters = radius_miles * 1609.344  # Match Java precision

        query = {
            "from": 0,
            "size": 100,  # Match Java query size
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "careRates.sidecarCode": {
                                    "query": sidecar_code.strip().upper(),
                                    "operator": "OR",
                                    "prefix_length": 0,
                                    "max_expansions": 50,
                                    "fuzzy_transpositions": True,
                                    "lenient": False,
                                    "zero_terms_query": "NONE",
                                    "auto_generate_synonyms_phrase_query": True,
                                    "boost": 1.0
                                }
                            }
                        }
                    ],
                    "filter": [],
                    "adjust_pure_negative": True,
                    "boost": 1.0
                }
            }
        }

        # Add geo distance filter if coordinates provided
        if lat is not None and lon is not None:
            query["query"]["bool"]["filter"].append({
                "geo_distance": {
                    "geoCoordinates": [lon, lat],  # [longitude, latitude] format
                    "distance": radius_meters,
                    "distance_type": "arc",
                    "validation_method": "STRICT",
                    "ignore_unmapped": False,
                    "boost": 1.0
                }
            })

        # Always add practice locations filter
        # query["query"]["bool"]["filter"].append({
        #     "exists": {
        #         "field": "practiceLocations",
        #         "boost": 1.0
        #     }
        # })

        logger.debug(f"Generated sidecar-only ES query")
        return query

    def has_price(self, provider: Dict[str, Any], target_sidecar_code: str) -> bool:
        """
        Check if provider has price information for a specific sidecar code
        Returns True only if there's a matching sidecarCode with averageProviderRate > 0
        """
        # Get careRates directly from flattened provider structure
        care_rates = provider.get('careRates', [])

        if isinstance(care_rates, list):
            for rate in care_rates:
                if isinstance(rate, dict):
                    rate_sidecar = rate.get('sidecarCode')
                    avg_rate = rate.get('averageProviderRate')

                    # Check if this rate matches the target sidecar code
                    if rate_sidecar == target_sidecar_code and avg_rate is not None:
                        try:
                            rate_value = float(avg_rate)
                            if rate_value > 0:
                                return True
                        except (ValueError, TypeError):
                            continue

        elif isinstance(care_rates, dict):
            # Handle single rate case
            rate_sidecar = care_rates.get('sidecarCode')
            avg_rate = care_rates.get('averageProviderRate')

            if rate_sidecar == target_sidecar_code and avg_rate is not None:
                try:
                    rate_value = float(avg_rate)
                    if rate_value > 0:
                        return True
                except (ValueError, TypeError):
                    pass

        return False


    def _get_provider_specialties(self, provider: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Extract primary and secondary specialties from provider document using careSearchSpecialties
        to match Java logic (CareReimbursement.CareSearchSpecialties)

        Note: ES queries use taxonomies.specialty for search, but filtering uses careSearchSpecialties
        for consistency with Java business logic
        """
        source = provider.get('_source', {})

        # Use careSearchSpecialties field for Java filtering logic (NOT taxonomies.specialty)
        # ES queries use taxonomies.specialty, but Java filtering uses careSearchSpecialties
        care_search_specialties = source.get('careSearchSpecialties', [])

        # Handle both list and single value cases
        if not isinstance(care_search_specialties, list):
            care_search_specialties = [care_search_specialties] if care_search_specialties else []

        # For careSearchSpecialties, we typically treat all as primary specialties
        # since this field is specifically used for care search filtering
        primary_specialties = []
        secondary_specialties = []

        for specialty in care_search_specialties:
            if isinstance(specialty, str) and specialty.strip():
                primary_specialties.append(specialty.lower().strip())
            elif isinstance(specialty, dict):
                # Handle case where specialty is an object with name/value
                specialty_name = specialty.get('name') or specialty.get('specialty') or specialty.get('value', '')
                if specialty_name and specialty_name.strip():
                    # Check if it's marked as primary/secondary
                    is_primary = specialty.get('isPrimary', True)  # Default to primary for careSearchSpecialties
                    if is_primary:
                        primary_specialties.append(specialty_name.lower().strip())
                    else:
                        secondary_specialties.append(specialty_name.lower().strip())

        # Fallback to taxonomies.specialty if careSearchSpecialties is empty (backward compatibility)
        if not primary_specialties and not secondary_specialties:
            taxonomies = source.get('taxonomies', [])
            if not isinstance(taxonomies, list):
                taxonomies = [taxonomies] if taxonomies else []

            for taxonomy in taxonomies:
                if isinstance(taxonomy, dict):
                    specialty = taxonomy.get('specialty')
                    if specialty and specialty.strip():
                        # Treat all taxonomy specialties as primary for now
                        # (matches ES query behavior - providers matched on taxonomies.specialty)
                        primary_specialties.append(specialty.lower().strip())

        return {
            'primary': primary_specialties,
            'secondary': secondary_specialties
        }

    def _matches_target_specialties(self, provider_specialties: Dict[str, List[str]],
                                    target_specialties: Optional[List[str]]) -> Dict[str, bool]:
        """
        Check if provider specialties match target specialties
        """
        if not target_specialties:
            return {'primary': True, 'secondary': True}  # No filter means all match

        target_lower = [spec.lower().strip() for spec in target_specialties]

        primary_match = any(spec in target_lower for spec in provider_specialties['primary'])
        secondary_match = any(spec in target_lower for spec in provider_specialties['secondary'])

        return {
            'primary': primary_match,
            'secondary': secondary_match
        }

    def _has_primary_specialty_match(self, provider: Dict[str, Any], sidecar_code: str) -> bool:
        """
        Check if provider has primary specialty match (matching Java hasPrimarySpecialtyMatch)
        Java checks if provider taxonomies match careInfo.getCareSearchSpecialties()
        """
        # Get CARE_SEARCH_SPECIALTIES from Snowflake for this sidecar code
        if not self.care_lookup:
            return False

        sidecar_specialties = self.care_lookup.get_care_search_specialties(sidecar_code)
        if not sidecar_specialties:
            return False

        # Get taxonomies directly from flattened provider structure
        taxonomies = provider.get('taxonomies', [])

        if not taxonomies:
            return False

        # Convert sidecar specialties to lowercase set for case-insensitive comparison
        # Handle potential non-string values safely
        specialties_lower_case = set()
        for spec in sidecar_specialties:
            if isinstance(spec, str) and spec.strip():
                specialties_lower_case.add(spec.strip().lower())

        # Check if any taxonomy marked as primary has a specialty matching target specialties
        has_match = False
        primary_specialties = []

        for taxonomy in taxonomies:
            if isinstance(taxonomy, dict):
                is_primary = taxonomy.get('primary')
                specialty = taxonomy.get('specialty')

                if is_primary is True:  # Only primary taxonomies
                    if specialty:
                        primary_specialties.append(specialty)
                        if specialty.lower() in specialties_lower_case:
                            has_match = True

        return has_match

    def _has_secondary_specialty_match(self, provider: Dict[str, Any], sidecar_code: str) -> bool:
        """
        Check if provider has secondary specialty match (matching Java hasSecondarySpecialtyMatch)
        Java checks if provider taxonomies match careInfo.getCareSearchSpecialties() but not primary
        """
        # Get CARE_SEARCH_SPECIALTIES from Snowflake for this sidecar code
        if not self.care_lookup:
            return False

        sidecar_specialties = self.care_lookup.get_care_search_specialties(sidecar_code)
        if not sidecar_specialties:
            return False

        # Get taxonomies directly from provider (not from _source)
        taxonomies = provider.get('taxonomies', [])

        if not taxonomies:
            return False

        # Convert sidecar specialties to lowercase set for case-insensitive comparison
        # Handle potential non-string values safely
        specialties_lower_case = set()
        for spec in sidecar_specialties:
            if isinstance(spec, str) and spec.strip():
                specialties_lower_case.add(spec.strip().lower())

        # Check if any taxonomy NOT marked as primary has a specialty matching target specialties
        for taxonomy in taxonomies:
            if isinstance(taxonomy, dict):
                # Filter for non-primary taxonomies (primary != True)
                is_primary = taxonomy.get('primary')
                if is_primary is not True:  # Matches Java logic: NOT "true"
                    specialty = taxonomy.get('specialty')
                    if specialty is not None and specialty.lower() in specialties_lower_case:
                        return True

        return False

    def _enrich_provider_with_price_info(self, provider: Dict[str, Any], target_sidecar_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Enrich provider with top-level pricing information (matching Java enrichProviderWithPriceInfo)
        """
        # Find the provider rate from careRates, prioritizing the target sidecar code
        provider_rate = None
        care_rates = provider.get('careRates', [])

        if isinstance(care_rates, list):
            # First, try to find a rate matching the target sidecar code
            if target_sidecar_code:
                for rate in care_rates:
                    if isinstance(rate, dict):
                        rate_sidecar = rate.get('sidecarCode')
                        avg_rate = rate.get('averageProviderRate')
                        if (rate_sidecar == target_sidecar_code and
                                avg_rate is not None and avg_rate > 0):
                            provider_rate = float(avg_rate)
                            break

            # Fallback: take first available rate if no target match found
            if provider_rate is None:
                for rate in care_rates:
                    if isinstance(rate, dict):
                        avg_rate = rate.get('averageProviderRate')
                        if avg_rate is not None and avg_rate > 0:
                            provider_rate = float(avg_rate)
                            break

        elif isinstance(care_rates, dict):
            avg_rate = care_rates.get('averageProviderRate')
            if avg_rate is not None and avg_rate > 0:
                provider_rate = float(avg_rate)

        # Add top-level providerRate field (matching Java behavior) - FIX: Use provider, not source
        if provider_rate is not None:
            provider['providerRate'] = provider_rate  # FIXED: was source['providerRate']

        return provider


    def _get_gam_appropriateness_score(self, provider: Dict[str, Any]) -> float:
        """
        Get GAM appropriateness score for sorting (matching Java getGamAppropriatenessScore)
        Default to 0.0 if not present
        """
        # Get GAM score directly from flattened provider structure
        score = provider.get('gamAppropriatenessScore')
        if score is not None:
            return float(score)

        # Fallback to fetched GAM score from Snowflake
        npi = self._safe_get_provider_id(provider)
        if npi and hasattr(provider, '_gam_score'):
            return provider._gam_score

        return 0.0

    def _provider_has_target_sidecar_code(self, provider: Dict[str, Any], target_sidecar_code: str) -> bool:
        """
        Check if provider has the target sidecar code in their careRates
        """
        # Get careRates directly from flattened provider structure
        care_rates = provider.get('careRates', [])

        if isinstance(care_rates, list):
            for rate in care_rates:
                if isinstance(rate, dict):
                    sidecar_code = rate.get('sidecarCode')
                    if sidecar_code == target_sidecar_code:
                        return True
        elif isinstance(care_rates, dict):
            sidecar_code = care_rates.get('sidecarCode')
            if sidecar_code == target_sidecar_code:
                return True

        return False

    def _provider_matches_care_search_specialties(self, provider: Dict[str, Any], sidecar_code: str) -> bool:
        """
        Check if provider's careSearchSpecialties field matches any of the target specialties
        This is the Java filtering logic that happens AFTER ES queries
        """
        if not sidecar_code:
            return True  # No filter means all match

        # Get careSearchSpecialties directly from flattened provider structure
        care_search_specialties = provider.get('careSearchSpecialties', [])

        provider_id = self._safe_get_provider_id(provider)

        # Handle both list and single value cases
        if not isinstance(care_search_specialties, list):
            care_search_specialties = [care_search_specialties] if care_search_specialties else []

        # If no careSearchSpecialties field, fall back to taxonomies matching
        # This ensures consistency with _has_primary_specialty_match and _has_secondary_specialty_match
        if not care_search_specialties:
            # Use the same logic as primary/secondary specialty matching
            has_primary = self._has_primary_specialty_match(provider, target_sidecar_code)
            has_secondary = self._has_secondary_specialty_match(provider, target_sidecar_code)
            return has_primary or has_secondary

        # Get CARE_SEARCH_SPECIALTIES from Snowflake for this sidecar code
        if not self.care_lookup:
            return False

        sidecar_specialties = self.care_lookup.get_care_search_specialties(sidecar_code)
        if not sidecar_specialties:
            return False

        # Normalize sidecar specialties for comparison
        target_lower = [spec.lower().strip() for spec in sidecar_specialties]

        # Check if any provider careSearchSpecialties matches target specialties
        for specialty in care_search_specialties:
            if isinstance(specialty, str) and specialty.strip():
                specialty_lower = specialty.lower().strip()
                if specialty_lower in target_lower:
                    return True
            elif isinstance(specialty, dict):
                specialty_name = specialty.get('name') or specialty.get('specialty') or specialty.get('value', '')
                if specialty_name and specialty_name.strip():
                    specialty_lower = specialty_name.lower().strip()
                    if specialty_lower in target_lower:
                        return True

        return False

    def _enrich_providers_with_gam_scores(self, providers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enrich providers with GAM scores from Snowflake DOCTOR table
        """
        if not providers or not self.care_lookup:
            return providers

        # Extract NPIs from providers using safe method
        npis = []
        for p in providers:
            npi = self._safe_get_provider_id(p)
            if npi:
                npis.append(npi)

        if not npis:
            return providers

        try:
            # Get GAM scores from Snowflake
            gam_scores = self.care_lookup.get_gam_scores(npis)
            logger.info(f"Retrieved GAM scores for {len(gam_scores)} providers")

            # Enrich providers with GAM scores
            for provider in providers:
                npi = self._safe_get_provider_id(provider)
                if npi and npi in gam_scores:
                    provider['_gam_score'] = gam_scores[npi]
                    # Also add to flattened provider structure for completeness
                    provider['gamAppropriatenessScore'] = gam_scores[npi]
                else:
                    provider['_gam_score'] = 0.0

        except Exception as e:
            logger.error(f"Failed to enrich providers with GAM scores: {e}")
            # Add default GAM scores
            for provider in providers:
                provider['_gam_score'] = 0.0

        return providers

    def _apply_business_logic_filtering(self, processed_providers: List[Dict[str, Any]],
                                        target_specialties: Optional[List[str]],
                                        target_sidecar_code: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Apply business logic filtering and sorting to match Java implementation exactly

        Java Logic Explanation:

        STEP 1: ENRICH PROVIDERS WITH PRICING INFO
        - Call enrichProviderWithPriceInfo for each provider to add top-level providerRate

        STEP 2: FILTERING
        - Remove providers that have PRICE but NO specialty match (business rule)

        STEP 3: CATEGORIZATION
        - primaryWithPrice: Providers with PRIMARY specialty match AND price
        - secondaryWithPrice: Providers with SECONDARY specialty match AND price (but no primary)

        STEP 4: SORTING WITHIN CATEGORIES
        - primaryWithPrice: Sort by price ASC (cheapest first), then GAM score DESC (higher is better)
        - secondaryWithPrice: Sort by price ASC, then GAM score DESC
        - Others: No special sorting (keep ES order)

        STEP 5: FINAL ORDER
        - Combine: primary+price, secondary+price, primary+no-price, secondary+no-price
        """

        if not processed_providers:
            return []

        # Step 1: Enrich all providers with pricing info (matching Java)
        enriched_providers = []
        for provider in processed_providers:
            enriched_provider = self._enrich_provider_with_price_info(provider, target_sidecar_code)
            enriched_providers.append(enriched_provider)

        logger.info(f"STEP 1 ENRICHMENT: Enriched {len(enriched_providers)} providers with pricing info")


        # Step 2: Filter out providers with price but no specialty match
        filtered_providers = []
        filtered_out_count = 0

        for provider in enriched_providers:
            has_price = self.has_price(provider, target_sidecar_code)
            has_primary_specialty = self._has_primary_specialty_match(provider, target_sidecar_code)
            has_secondary_specialty = self._has_secondary_specialty_match(provider, target_sidecar_code)

            has_specialty_match = has_primary_specialty or has_secondary_specialty

            # If no specialty match and has price, filter it out (matching Java logic)
            if not has_specialty_match and has_price:
                filtered_out_count += 1
                continue

            # Otherwise keep it
            filtered_providers.append(provider)

        logger.info(f"STEP 2 FILTERING: {len(enriched_providers)} → {len(filtered_providers)} providers (removed {filtered_out_count})")


        # Step 3: Categorize providers into 4 groups (matching Java exactly)
        categorized_providers = {
            'primaryWithPrice': [],
            'secondaryWithPrice': []
        }

        # Single iteration to categorize all providers (matching Java)
        for i, provider in enumerate(filtered_providers):
            has_primary = self._has_primary_specialty_match(provider, target_sidecar_code)
            has_secondary = self._has_secondary_specialty_match(provider, target_sidecar_code)
            has_price = self.has_price(provider, target_sidecar_code)

            npi = self._safe_get_provider_id(provider)

            # Debug the first few providers to understand the categorization
            if i < 3:
                provider_taxonomies = provider.get('taxonomies', [])
                provider_specialties = [t.get('specialty') for t in provider_taxonomies if isinstance(t, dict) and t.get('specialty')]

            price = self._get_provider_rate(provider, target_sidecar_code)
            gam_score = self._get_gam_appropriateness_score(provider)

            # Java logic: if (hasPrimary && hasPrice)
            if has_primary and has_price:
                categorized_providers['primaryWithPrice'].append(provider)
            # Java logic: else if (!hasPrimary && hasSecondary && hasPrice)
            elif not has_primary and has_secondary and has_price:
                categorized_providers['secondaryWithPrice'].append(provider)
            else:
                logger.warning(f"STEP 3 CATEGORIZE: {npi} → UNCATEGORIZED (primary: {has_primary}, secondary: {has_secondary}, price: {has_price}) - This should not happen!")





        # Step 4: Sort each category according to Java logic
        logger.info(f"STEP 4 SORTING: Sorting categories by price ASC, then GAM score DESC")

        # PRIMARY WITH PRICE - Match Java sorting exactly
        categorized_providers['primaryWithPrice'].sort(
            key=lambda p: (
                # nullsFirst(naturalOrder) = NULL values FIRST, then ascending
                self._get_provider_rate(p, target_sidecar_code) if self._get_provider_rate(p, target_sidecar_code) is not None else float('-inf'),
                # reverseOrder for GAM = Higher GAM scores FIRST
                -self._get_gam_appropriateness_score(p)
            )
        )


        # SECONDARY WITH PRICE - Same sorting logic as Java
        categorized_providers['secondaryWithPrice'].sort(
            key=lambda p: (
                # nullsFirst(naturalOrder) = NULL values FIRST, then ascending
                self._get_provider_rate(p, target_sidecar_code) if self._get_provider_rate(p, target_sidecar_code) is not None else float('-inf'),
                # reverseOrder for GAM = Higher GAM scores FIRST
                -self._get_gam_appropriateness_score(p)
            )
        )



        # Step 5: Combine all categories in the required order (matching Java)
        logger.info(f"STEP 5 COMBINING: Combining categories in Java order")
        result = []
        result.extend(categorized_providers['primaryWithPrice'])
        result.extend(categorized_providers['secondaryWithPrice'])

        logger.info(f"Applied Java-matching business logic: {len(processed_providers)} → {len(result)} providers")



        # Log ALL NPIs in final order for easy comparison with Java
        all_final_npis = [self._safe_get_provider_id(p) for p in result if self._safe_get_provider_id(p)]

        return result

    def _get_provider_rate(self, provider: Dict[str, Any], target_sidecar_code: Optional[str] = None) -> Optional[float]:
        """
        Get provider rate for sorting - Only return rate for the specific target sidecar code

        Args:
            provider: Provider document from Elasticsearch
            target_sidecar_code: The sidecar code to look for in careRates

        Returns:
            Rate for the target sidecar code if found and > 0, otherwise None
        """
        if not target_sidecar_code:
            return None  # No sidecar code specified, no rate to return

        npi = self._safe_get_provider_id(provider)

        # Check careRates for the specific sidecar code (from flattened provider structure)
        care_rates = provider.get('careRates', [])

        if isinstance(care_rates, list):
            for rate in care_rates:
                if isinstance(rate, dict):
                    rate_sidecar_code = rate.get('sidecarCode')
                    avg_rate = rate.get('averageProviderRate')

                    # Only return rate if sidecar code matches and rate > 0
                    if (rate_sidecar_code == target_sidecar_code and
                            avg_rate is not None):
                        try:
                            rate_value = float(avg_rate)
                            if rate_value > 0:
                                return rate_value
                        except (ValueError, TypeError):
                            continue

        elif isinstance(care_rates, dict):
            # Handle single careRates object
            rate_sidecar_code = care_rates.get('sidecarCode')
            avg_rate = care_rates.get('averageProviderRate')

            if (rate_sidecar_code == target_sidecar_code and
                    avg_rate is not None):
                try:
                    rate_value = float(avg_rate)
                    if rate_value > 0:
                        return rate_value
                except (ValueError, TypeError):
                    pass
        return None

    def get_radius_for_zipcode(self, zipcode: str, insurance_filing_uuid: str = None, default_radius: float = 8.0) -> float:
        """
        Get proper radius for a zipcode using Snowflake lookup: zipcode -> rating_area -> radius

        Args:
            zipcode: The zipcode to lookup
            insurance_filing_uuid: Optional insurance filing UUID for more specific lookup
            default_radius: Default radius if lookup fails

        Returns:
            Radius in miles
        """
        if self.care_lookup:
            try:
                return self.care_lookup.get_radius_by_zipcode(zipcode, insurance_filing_uuid, default_radius)
            except Exception as e:
                logger.warning(f"Failed to get radius from Snowflake for zipcode {zipcode}: {e}, using default {default_radius}")
                return default_radius
        else:
            logger.info(f"Snowflake lookup disabled, using default radius {default_radius} for zipcode {zipcode}")
            return default_radius

    def _safe_get_provider_id(self, provider: Dict[str, Any]) -> Optional[str]:
        """
        Safely extract provider ID, ensuring it's a hashable string.
        Returns None if the ID is not a valid string.
        """
        provider_id = provider.get('_id')
        if provider_id is None:
            return None

        # Handle case where _id might be a list or other non-string type
        if isinstance(provider_id, str):
            return provider_id.strip() if provider_id.strip() else None
        elif isinstance(provider_id, (int, float)):
            return str(provider_id)
        elif isinstance(provider_id, list):
            if len(provider_id) == 0:
                logger.warning("Provider _id is an empty list")
                return None
            # Try to find the first valid item in the list
            for item in provider_id:
                if isinstance(item, str) and item.strip():
                    logger.warning(f"Provider _id is a list, using first valid string item: {item}")
                    return item.strip()
                elif isinstance(item, (int, float)):
                    logger.warning(f"Provider _id is a list, using first valid numeric item: {item}")
                    return str(item)
            # If no valid items found
            logger.warning(f"Provider _id list contains no valid items: {provider_id}")
            return None
        elif isinstance(provider_id, dict):
            # Handle case where _id might be a dict (shouldn't happen but let's be safe)
            logger.warning(f"Provider _id is a dict: {provider_id}")
            return None
        else:
            logger.warning(f"Provider has unsupported _id type: {provider_id} (type: {type(provider_id)})")
            return None


    def getProviders(self, sidecar_code: Optional[str] = None, specialties: Optional[List[str]] = None,
                     lat: Optional[float] = None, lon: Optional[float] = None,
                     radius: Optional[float] = None, zipcode: Optional[str] = None,
                     insurance_filing_uuid: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get providers/doctors from Elasticsearch with business logic filtering and sorting

        Executes TWO separate ES queries (matching Java implementation):
        1. Sidecar-only query (like Java generateSidecarCodeOnlySearchRequest)
        2. Combined query with sidecar + specialties in 'should' clauses
        Then combines and deduplicates both results

        Args:
            sidecar_code: Sidecar code to match (optional)
            specialties: List of medical specialties to search for (optional)
            lat: Latitude for geo search (optional)
            lon: Longitude for geo search (optional)
            radius: Search radius in miles (optional, will be calculated from zipcode if not provided)
            zipcode: Zipcode for radius calculation (optional)
            insurance_filing_uuid: Insurance filing UUID for radius calculation (optional)

        Returns:
            List of provider/doctor documents sorted by business logic priority
        """

        # Calculate proper radius using Snowflake lookup if zipcode provided but radius not specified
        final_radius = radius
        if radius is None and zipcode:
            final_radius = self.get_radius_for_zipcode(zipcode, insurance_filing_uuid, 8.0)
            logger.info(f"Calculated radius from Snowflake: zipcode {zipcode} -> {final_radius} miles")
        elif radius is None:
            final_radius = 8.0  # Standard default radius when no zipcode provided
            logger.info(f"No zipcode provided, using default radius: {final_radius} miles")

        logger.info(f"Getting providers - sidecar: {sidecar_code}, specialties: {specialties}, "
                    f"location: ({lat}, {lon}), radius: {final_radius} (zipcode: {zipcode})")

        # Step 1: Execute both ES queries first (matching Java approach)
        sidecar_providers = []
        specialties_providers = []

        # Query 1: Sidecar-only search
        if sidecar_code and sidecar_code.strip():
            sidecar_query = self._build_sidecar_only_query(sidecar_code, lat, lon, final_radius)
            sidecar_results = self._make_es_request('POST', f'/{self.index_name}/_search', sidecar_query)
            sidecar_providers = sidecar_results.get('hits', {}).get('hits', [])
            logger.info(f"Found {len(sidecar_providers)} providers from sidecar-only search")

            # Debug NPI types disabled

        # Query 2: Specialties+sidecar search
        if specialties and any(s.strip() for s in specialties):
            specialties_query = self._build_specialties_only_query(specialties, sidecar_code, lat, lon, final_radius)
            specialties_results = self._make_es_request('POST', f'/{self.index_name}/_search', specialties_query)
            specialties_providers = specialties_results.get('hits', {}).get('hits', [])
            logger.info(f"Found {len(specialties_providers)} providers from specialties+sidecar search")

            # Debug NPI types disabled

        # Step 2: Merge ES query results and deduplicate by NPI (matching Java approach)
        # Priority: Query 1 (sidecar-only) providers first, then Query 2 (specialties+sidecar) providers

        merged_providers = []
        seen_npis = set()

        # Add all Query 1 providers first (sidecar-only query results)
        for provider in sidecar_providers:
            npi = self._safe_get_provider_id(provider)
            if npi and npi not in seen_npis:
                # Flatten the ES structure: move _source fields to top level for specialty matching
                flattened_provider = provider.get('_source', {}).copy()
                flattened_provider['_id'] = npi
                flattened_provider['_score'] = provider.get('_score')
                flattened_provider['_query_source'] = 'sidecar_only'
                merged_providers.append(flattened_provider)
                seen_npis.add(npi)
            elif not npi:
                logger.warning(f"Skipping sidecar provider with invalid NPI: {provider.get('_id')}")

        # Add Query 2 providers that are not already in the list (specialties+sidecar query results)
        for provider in specialties_providers:
            npi = self._safe_get_provider_id(provider)
            if npi and npi not in seen_npis:
                # Flatten the ES structure: move _source fields to top level for specialty matching
                flattened_provider = provider.get('_source', {}).copy()
                flattened_provider['_id'] = npi
                flattened_provider['_score'] = provider.get('_score')
                flattened_provider['_query_source'] = 'specialties_and_sidecar'
                merged_providers.append(flattened_provider)
                seen_npis.add(npi)
            elif npi and npi in seen_npis:
                # Update existing provider to show it came from both queries
                for existing in merged_providers:
                    if self._safe_get_provider_id(existing) == npi:
                        existing['_query_source'] = 'both_queries'
                        break
            elif not npi:
                logger.warning(f"Skipping specialties provider with invalid NPI: {provider.get('_id')}")

        logger.info(f"Merged results: {len(sidecar_providers)} from Query 1, {len(specialties_providers)} from Query 2")
        logger.info(f"Total unique providers after deduplication: {len(merged_providers)}")

        # Step 3: Process max 200 deduplicated providers through Java filtering one by one
        providers_to_process = merged_providers[:200]  # Limit to 200 as requested
        logger.info(f"Processing {len(providers_to_process)} providers through Java filtering logic")

        processed_providers = []
        for i, provider in enumerate(providers_to_process, 1):
            npi = self._safe_get_provider_id(provider)
            if not npi:
                logger.warning(f"Skipping provider {i} due to invalid NPI: {provider.get('_id')}")
                continue


            # Call has_primary_specialty and has_secondary_specialty for each provider
            has_primary_match = self._has_primary_specialty_match(provider, sidecar_code if sidecar_code else "")
            has_secondary_match = self._has_secondary_specialty_match(provider, sidecar_code if sidecar_code else "")


            # Apply filtering logic: if has specialties, must have primary or secondary match
            if specialties and any(s.strip() for s in specialties):
                if has_primary_match or has_secondary_match:
                    processed_providers.append(provider)
            else:
                # If no specialties specified, include all providers
                processed_providers.append(provider)

        logger.info(f"After Java filtering: {len(processed_providers)} providers remain")

        logger.info(f"Query 1 (sidecar-only) raw results: {len(sidecar_providers)} providers")
        if sidecar_providers:
            query1_npis = [self._safe_get_provider_id(p) for p in sidecar_providers[:10]]
            query1_npis = [npi for npi in query1_npis if npi]  # Remove None values

        logger.info(f"Query 2 (specialties+sidecar) raw results: {len(specialties_providers)} providers")
        if specialties_providers:
            query2_npis = [self._safe_get_provider_id(p) for p in specialties_providers[:10]]
            query2_npis = [npi for npi in query2_npis if npi]  # Remove None values

        logger.info(f"After merge and deduplication: {len(merged_providers)} providers")
        if merged_providers:
            merged_npis = [self._safe_get_provider_id(p) for p in merged_providers[:10]]
            merged_npis = [npi for npi in merged_npis if npi]  # Remove None values

        logger.info(f"After Java individual filtering (max 200): {len(processed_providers)} providers")
        if processed_providers:
            processed_npis = [self._safe_get_provider_id(p) for p in processed_providers[:10]]
            processed_npis = [npi for npi in processed_npis if npi]  # Remove None values

            # Show query source distribution
            query_source_counts = {}
            for p in processed_providers:
                source = p.get('_query_source', 'unknown')
                query_source_counts[source] = query_source_counts.get(source, 0) + 1



        logger.info(f"About to start business logic with {len(processed_providers)} providers")
        if processed_providers:
            first_5_npis = [self._safe_get_provider_id(p) for p in processed_providers[:5]]
            first_5_npis = [npi for npi in first_5_npis if npi]  # Remove None values

        # Step 5: Snowflake filtering removed - filtering now happens in specialty matching methods
        snowflake_filtered_providers = processed_providers

        logger.info(f"After Snowflake filtering: {len(snowflake_filtered_providers)} providers")
        if snowflake_filtered_providers:
            snowflake_npis = [self._safe_get_provider_id(p) for p in snowflake_filtered_providers[:5]]
            snowflake_npis = [npi for npi in snowflake_npis if npi]  # Remove None values

        # Step 6: Enrich providers with GAM scores from Snowflake
        gam_enriched_providers = self._enrich_providers_with_gam_scores(snowflake_filtered_providers)

        # Step 7: Apply Java-matching business logic filtering and sorting
        filtered_providers = self._apply_business_logic_filtering(gam_enriched_providers, specialties, sidecar_code)

        logger.info(f"Final provider count after all filtering and sorting: {len(filtered_providers)}")
        if filtered_providers:
            final_npis = [self._safe_get_provider_id(p) for p in filtered_providers[:10]]
            final_npis = [npi for npi in final_npis if npi]  # Remove None values

            # Show breakdown by categories (if available)
            if hasattr(filtered_providers[0], '_final_category'):
                category_counts = {}
                for p in filtered_providers:
                    cat = getattr(p, '_final_category', 'unknown')
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                logger.info(f"Final provider distribution by category: {category_counts}")

        logger.info(f"Returning {len(filtered_providers)} providers after filtering and sorting")
        return filtered_providers

    def cluster_health(self) -> Dict[str, Any]:
        """
        Get Elasticsearch cluster health information
        """
        return self._make_es_request('GET', '/_cluster/health')

    def close(self):
        """
        Close connections and clean up resources
        """
        if self.care_lookup:
            try:
                self.care_lookup.close_connection()
            except Exception as e:
                logger.warning(f"Error closing Snowflake connection: {e}")


def main():
    """
    Example usage of ProviderPriceInformation
    """

    # Initialize the service using centralized config
    provider_service = ProviderPriceInformation()

    try:
        # Test cluster health
        print("\n=== Cluster Health ===")
        health = provider_service.cluster_health()
        print(f"Cluster status: {health.get('status', 'unknown')}")

        # Example 1: Get providers by sidecar code and specialties
        print("\n=== Example 1: Get providers with sidecar + specialties ===")
        providers1 = provider_service.getProviders(
            sidecar_code="SC123",
            specialties=["cardiology", "neurology"],
            lat=40.7128,
            lon=-74.0060,
            zipcode="10001"  # Use zipcode for dynamic radius calculation
        )
        print(f"Found {len(providers1)} providers")

        # Example 2: Get providers by specialties only (no sidecar code)
        print("\n=== Example 2: Get providers by specialties only ===")
        providers2 = provider_service.getProviders(
            specialties=["dermatology", "orthopedics"],
            lat=34.0522,
            lon=-118.2437,
            zipcode="90210"  # Use zipcode for dynamic radius calculation
        )
        print(f"Found {len(providers2)} providers")

        # Example 3: Get providers by sidecar code only
        print("\n=== Example 3: Get providers by sidecar code only ===")
        providers3 = provider_service.getProviders(
            sidecar_code="SC456",
            lat=40.7128,
            lon=-74.0060,
            zipcode="10001"  # Use zipcode for dynamic radius calculation
        )
        print(f"Found {len(providers3)} providers")

        # Example 4: Get all providers in area (no filters)
        print("\n=== Example 4: Get all providers in area ===")
        providers4 = provider_service.getProviders(
            lat=40.7128,
            lon=-74.0060,
            zipcode="10001"  # Use zipcode for dynamic radius calculation
        )
        print(f"Found {len(providers4)} providers")

        # Display sample provider information
        if providers1:
            print(f"\n=== Sample Provider Information ===")
            sample = providers1[0]
            # Handle both original ES structure and flattened structure
            source = sample.get('_source', sample)

            print(f"Provider ID: {sample.get('_id')}")
            print(f"ES Score: {sample.get('_score')}")

            # Show specialties
            taxonomies = source.get('taxonomies', [])
            if taxonomies:
                print("Specialties:")
                for taxonomy in taxonomies[:3]:  # Show first 3
                    if isinstance(taxonomy, dict):
                        specialty = taxonomy.get('specialty', 'N/A')
                        is_primary = taxonomy.get('isPrimary', False)
                        print(f"  - {specialty} ({'Primary' if is_primary else 'Secondary'})")

            # Show pricing info
            care_rates = source.get('careRates', [])
            if care_rates:
                if isinstance(care_rates, list) and care_rates:
                    rate = care_rates[0].get('averageProviderRate')
                    sidecar = care_rates[0].get('sidecarCode')
                elif isinstance(care_rates, dict):
                    rate = care_rates.get('averageProviderRate')
                    sidecar = care_rates.get('sidecarCode')

                if 'rate' in locals() and rate:
                    print(f"Average Rate: ${rate}")
                if 'sidecar' in locals() and sidecar:
                    print(f"Sidecar Code: {sidecar}")

    except Exception as e:
        logger.error(f"Error in example execution: {e}")
        raise


if __name__ == "__main__":
    main()