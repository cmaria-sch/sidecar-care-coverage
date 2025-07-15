# Sidecar Care Coverage Data Collection

This project collects drug pricing and benefit data from the Sidecar Health API across multiple zip codes in Florida, Georgia, and Ohio.

## 📋 Overview

The data collection system:

- Fetches drug pricing data from Sidecar Health's API
- Covers major metropolitan areas in FL, GA, and OH
- Processes pharmacy pricing information for the top 100 drugs by frequency
- Outputs comprehensive CSV data with pricing, benefits, and pharmacy details
- Includes automatic token management and rate limiting
- **Batch Processing**: Each state is split into 2 batches for manageable processing

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

### 3. Run Data Collection (Choose Your State)

**Ohio Collection (2 batches)**

```bash
# Run Ohio batch 1 (~5.3 hours)
./run_ohio_batch1.sh

# Run Ohio batch 2 (~5.3 hours)
./run_ohio_batch2.sh
```

**Florida Collection (2 batches)**

```bash
# Run Florida batch 1 (~5.3 hours)
./run_florida_batch1.sh

# Run Florida batch 2 (~5.2 hours)
./run_florida_batch2.sh
```

**Georgia Collection (2 batches)**

```bash
# Run Georgia batch 1 (~3.4 hours)
./run_georgia_batch1.sh

# Run Georgia batch 2 (~3.4 hours)
./run_georgia_batch2.sh
```

**Complete Collection (All States)**

```bash
# Run all batches sequentially (~32 hours total)
./run_ohio_batch1.sh && ./run_ohio_batch2.sh && \
./run_florida_batch1.sh && ./run_florida_batch2.sh && \
./run_georgia_batch1.sh && ./run_georgia_batch2.sh
```

## 📁 Project Files

| File/Folder               | Description                           |
| ------------------------- | ------------------------------------- |
| `data_collection.py`      | Main data collection script           |
| `preprocess_drugs_csv.py` | Script to add UUIDs to drugs CSV      |
| `grab_token.sh`           | Authentication token retrieval script |
| `setup_environment.sh`    | Environment setup script              |
| **Batch Scripts**         | **State-specific batch runners**      |
| `run_ohio_batch1.sh`      | Ohio batch 1 (~477 zip codes)         |
| `run_ohio_batch2.sh`      | Ohio batch 2 (~477 zip codes)         |
| `run_florida_batch1.sh`   | Florida batch 1 (~474 zip codes)      |
| `run_florida_batch2.sh`   | Florida batch 2 (~473 zip codes)      |
| `run_georgia_batch1.sh`   | Georgia batch 1 (~304 zip codes)      |
| `run_georgia_batch2.sh`   | Georgia batch 2 (~303 zip codes)      |
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
- **Total**: ~947 zip codes (split into 2 batches)

**Georgia** (`zipcodes/zipcode_ga.txt`)

- Atlanta, Augusta, Columbus, Savannah, Macon, Albany, Athens, Valdosta
- **Total**: ~607 zip codes (split into 2 batches)

**Ohio** (`zipcodes/zipcode_oh.txt`)

- Cleveland, Columbus, Cincinnati, Toledo, Akron, Dayton, Youngstown, Canton
- **Total**: ~954 zip codes (split into 2 batches)

### Batch Processing Strategy

Each state is divided into 2 batches for manageable processing:

| State   | Batch 1   | Batch 2   | Total Combinations | Est. Time per Batch |
| ------- | --------- | --------- | ------------------ | ------------------- |
| Ohio    | ~477 zips | ~477 zips | ~95,400            | ~5.3 hours          |
| Florida | ~474 zips | ~473 zips | ~94,700            | ~5.2-5.3 hours      |
| Georgia | ~304 zips | ~303 zips | ~60,700            | ~3.4 hours          |

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

**Batch Scripts Not Executable**

```bash
# Make batch scripts executable
chmod +x run_*_batch*.sh
```

**Test Mode Returns Empty Results**

If test mode completes immediately without making API calls and produces an empty CSV file (only headers), the issue is likely a leftover progress file:

```bash
# Check if test progress file exists
ls -la results/progress_test.json

# If it exists, remove it to run a fresh test
rm results/progress_test.json

# Then run test mode again
python3 data_collection.py --test --states OH --csv-file top_100_drugs_with_uuids.csv
```

**Batch Progress Files**

Each batch maintains its own progress file:

- Ohio Batch 1: `results/progress_OH_batch1of2.json`
- Ohio Batch 2: `results/progress_OH_batch2of2.json`
- Florida Batch 1: `results/progress_FL_batch1of2.json`
- Florida Batch 2: `results/progress_FL_batch2of2.json`
- Georgia Batch 1: `results/progress_GA_batch1of2.json`
- Georgia Batch 2: `results/progress_GA_batch2of2.json`

To restart a specific batch from scratch:

```bash
# Remove specific batch progress file (WARNING: This will restart that batch)
rm results/progress_OH_batch1of2.json
```

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

# 3. Run data collection by state
# Choose your state and run both batches:

# For Ohio:
./run_ohio_batch1.sh
./run_ohio_batch2.sh

# For Florida:
./run_florida_batch1.sh
./run_florida_batch2.sh

# For Georgia:
./run_georgia_batch1.sh
./run_georgia_batch2.sh
```

### Individual State Collection

```bash
# Ohio only (both batches)
./run_ohio_batch1.sh && ./run_ohio_batch2.sh

# Florida only (both batches)
./run_florida_batch1.sh && ./run_florida_batch2.sh

# Georgia only (both batches)
./run_georgia_batch1.sh && ./run_georgia_batch2.sh
```

### Resume Interrupted Collection

```bash
# Each batch script automatically resumes from where it left off
# Just re-run the same batch script that was interrupted
./run_ohio_batch1.sh  # Will resume from progress file
```

### Test Mode

```bash
# Test with a small sample before running full batches
source sidecar_env/bin/activate
python3 data_collection.py --test --states OH --csv-file top_100_drugs_with_uuids.csv
```

### Manual Environment Management

```bash
# Activate environment
source sidecar_env/bin/activate

# Run specific batch manually
python3 data_collection.py --states OH --batch 1 --total-batches 2 --csv-file top_100_drugs_with_uuids.csv

# Deactivate when done
deactivate
```

## 📊 Expected Runtime

### Per-Batch Estimates

- **Ohio Batches**: ~5.3 hours each (2 batches = ~10.6 hours total)
- **Florida Batches**: ~5.2-5.3 hours each (2 batches = ~10.5 hours total)
- **Georgia Batches**: ~3.4 hours each (2 batches = ~6.8 hours total)

### Total Collection Time

- **Single State**: 6.8 - 10.6 hours (depending on state)
- **All States**: ~32 hours total (if run sequentially)
- **Parallel Processing**: Can run different states on different machines

### Output Size per Batch

- **Ohio**: ~500K+ records per batch
- **Florida**: ~500K+ records per batch
- **Georgia**: ~300K+ records per batch

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
