# Sidecar Care Coverage Data Collection

This project collects drug pricing and benefit data from the Sidecar Health API across multiple zip codes in Florida, Georgia, and Ohio.

## 📋 Overview

The data collection system:

- Fetches drug pricing data from Sidecar Health's API
- Covers major metropolitan areas in FL, GA, and OH
- Processes pharmacy pricing information for the top 100 drugs by frequency
- Outputs comprehensive CSV data with pricing, benefits, and pharmacy details
- Includes automatic token management and rate limiting

## 🚀 Quick Start

### 1. Initial Setup

```bash
# Clone or download the project files
# Ensure you have the CSV file: "top_100_drugs.csv"

# Run the setup script (only needed once)
./setup_environment.sh
```

### 2. Preprocess Drugs CSV (Required)

Before running data collection, you must preprocess the drugs CSV to add UUIDs:

```bash
# Activate environment
source sidecar_env/bin/activate

# Run preprocessing to add care_uuid column
python3 preprocess_drugs_csv.py --input top_100_drugs.csv

# This creates top_100_drugs_with_uuids.csv and uuid_cache.json
```

### 3. Run Data Collection

```bash
# Easy way - using the convenience script
./run_collection.sh

# Manual way - activate environment and run
source sidecar_env/bin/activate
python3 data_collection.py --csv-file top_100_drugs_with_uuids.csv
```

## 📁 Project Files

| File/Folder               | Description                           |
| ------------------------- | ------------------------------------- |
| `data_collection.py`      | Main data collection script           |
| `preprocess_drugs_csv.py` | Script to add UUIDs to drugs CSV      |
| `grab_token.sh`           | Authentication token retrieval script |
| `setup_environment.sh`    | Environment setup script              |
| `run_collection.sh`       | Convenience script to run collection  |
| `requirements.txt`        | Python dependencies                   |
| `zipcodes/`               | Directory containing zipcode files    |
| `README.md`               | This documentation file               |

## 🔧 Requirements

### System Requirements

- Python 3.7+
- macOS/Linux/WSL (bash shell)
- Internet connection for API calls
- CSV file: `top_100_drugs.csv`
- Zipcode files in `/zipcodes` directory

### Python Dependencies

- `requests>=2.28.0` - HTTP requests for API calls
- `pandas>=1.5.0` - Data manipulation and CSV reading

## 📊 Data Collection Details

### Geographic Coverage

Zipcode files are stored in the `/zipcodes` directory:

**Florida** (`zipcodes/zipcode_fl.txt`)

- Miami, Fort Lauderdale, Tampa, Orlando, Jacksonville, St. Petersburg, Hialeah, West Palm Beach

**Georgia** (`zipcodes/zipcode_ga.txt`)

- Atlanta, Augusta, Columbus, Savannah, Macon, Albany, Athens, Valdosta

**Ohio** (`zipcodes/zipcode_oh.txt`)

- Cleveland, Columbus, Cincinnati, Toledo, Akron, Dayton, Youngstown, Canton

### Data Points Collected

For each drug/location combination:

- **Location Info**: State, zip code, city, coordinates
- **Drug Info**: Procedure code, drug name, dosage form, original benefit amounts
- **Pharmacy Info**: Name, phone, address, distance, rating
- **Pricing Info**: Provider price, member responsibility, earned benefit, savings
- **Additional**: NDC codes, quantities, deductible applications

## 📈 Output Format

The script generates files in organized directories:

- **CSV File**: `results/sidecar_data_YYYYMMDD_HHMMSS.csv` with all collected data
- **Log Files**: `logs/sidecar_api_collection.log` with detailed execution logs
- **Progress File**: `results/progress.json` for resuming interrupted collections
- **UUID Cache**: `uuid_cache.json` for procedure code to UUID mappings

### CSV Columns

```
timestamp, state, zip_code, city, lat, lng, procedure_code, drug_name,
dosage_form, total_benefit_amount_orig, claim_count_orig, pharmacy_name,
pharmacy_phone, pharmacy_address, pharmacy_distance, pharmacy_rate,
price_fairness, provider_price, estimated_member_responsibility,
earned_benefit, applied_to_deductible, savings, bill_over_benefit_amount,
facility_benefit_amount, gsn, ndc, qty
```

## 🔐 Authentication

The system uses automatic token management:

1. Checks for existing `TOKEN` environment variable
2. If not found, runs `grab_token.sh` to obtain a fresh token
3. Uses development API credentials for authentication

## ⚙️ Configuration

### Rate Limiting

- 1 second delay between API requests
- 3 retry attempts for failed requests
- 5 second delay between retries
- Extended delay for rate limit responses

### API Settings

- **Endpoint**: `https://prod-api.sidecarhealth.com/care/v1/cares/detail`
- **Category**: prescriptions
- **Search Radius**: 8 miles
- **Member UUID**: Pre-configured test member

## 🔄 Progress Tracking

The system includes robust progress tracking:

- **Resume Capability**: Automatically resumes from where it left off
- **Progress File**: `progress.json` tracks completed combinations
- **Error Handling**: Logs failures and continues processing
- **Completion Stats**: Reports total processed combinations

## 🐛 Troubleshooting

### Common Issues

**Token Authentication Fails**

```bash
# Check if grab_token.sh is executable
chmod +x grab_token.sh

# Manually test token retrieval
./grab_token.sh
```

**Missing CSV File**

```
Error: CSV file not found: top_100_drugs.csv
```

Ensure the CSV file is in the project directory.

**Missing UUIDs**

```
Error: No UUID in cache for procedure code
```

Run the preprocessing script first:

```bash
python3 preprocess_drugs_csv.py --input top_100_drugs.csv
```

**Missing Zipcode Files**

Ensure zipcode files are present in the `/zipcodes` directory:

- `zipcodes/zipcode_fl.txt`
- `zipcodes/zipcode_ga.txt`
- `zipcodes/zipcode_oh.txt`

**Python Dependencies**

```bash
# Reinstall dependencies
source sidecar_env/bin/activate
pip install -r requirements.txt
```

**API Rate Limiting**
The script automatically handles rate limiting with exponential backoff.

### Logs and Debugging

- Check `logs/sidecar_api_collection.log` for detailed execution logs
- Monitor `results/progress.json` for completion status
- Use `logs/errors.log` for error-specific debugging
- Check `logs/preprocess_drugs.log` for UUID lookup issues

## 📝 Usage Examples

### Complete Workflow

```bash
# 1. Setup environment (one time)
./setup_environment.sh

# 2. Preprocess drugs CSV to add UUIDs (required)
source sidecar_env/bin/activate
python3 preprocess_drugs_csv.py --input top_100_drugs.csv

# 3. Run data collection
./run_collection.sh
```

### Basic Collection

```bash
./run_collection.sh
```

### Resume Interrupted Collection

```bash
# The script automatically resumes from results/progress.json
./run_collection.sh
```

### Manual Environment Management

```bash
# Activate environment
source sidecar_env/bin/activate

# Run with custom settings
python3 data_collection.py

# Deactivate when done
deactivate
```

## 📊 Expected Runtime

- **Total Combinations**: ~4,000 (100 drugs × 40 zip codes)
- **Estimated Time**: 1-2 hours (with 1-second delays)
- **Output Size**: Varies based on pharmacy density per location

## 🔒 Security Notes

- Authentication tokens are temporary and automatically refreshed
- No sensitive data is stored in configuration files
- API credentials use development environment settings
- All network requests use HTTPS

## 🤝 Support

For issues or questions:

1. Check the log files for error details
2. Verify all requirements are installed
3. Ensure the CSV file is present and accessible
4. Confirm internet connectivity for API access

---

**Note**: This tool is designed for data analysis and research purposes. Please ensure compliance with Sidecar Health's API terms of service.
