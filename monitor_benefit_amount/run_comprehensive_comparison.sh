#!/bin/bash

# Comprehensive Benefit vs Provider Price Comparison Runner
# This script sets up environment, runs the comprehensive comparison, and manages outputs
# for a long-running job that processes all insurance filings, medical codes, and zip codes

set -e  # Exit on any error

echo "🚀 Comprehensive Benefit vs Provider Price Comparison"
echo "====================================================="

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="benefit_calc_env"
VENV_PATH="$SCRIPT_DIR/$VENV_NAME"
OUTPUT_DIR="$SCRIPT_DIR/comprehensive_comparison_results"
LOG_FILE="$OUTPUT_DIR/comparison_run_$(date +%Y%m%d_%H%M%S).log"
PYTHON_SCRIPT="comprehensive_benefit_provider_comparison.py"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to show usage
show_usage() {
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --dry-run     Show what would be done without actually running"
    echo "  --help, -h    Show this help message"
    echo ""
    echo "This script will:"
    echo "  1. Set up Python virtual environment"
    echo "  2. Install required dependencies"
    echo "  3. Run comprehensive comparison across all data files"
    echo "  4. Write results to Snowflake database"
    echo "  5. Create summary reports"
    echo ""
    echo "Expected data files (in input_data/ directory):"
    echo "  - insurance_fillings.csv (insurance filing UUIDs)"
    echo "  - medical_codes_non_rx.csv (sidecar codes)"
    echo "  - zip_code_fl.csv, zip_code_ga.csv, zip_code_oh.csv (zip codes)"
    echo ""
    echo "Results will be written to: WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST"
}

# Parse command line arguments
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Change to script directory
cd "$SCRIPT_DIR"

log "Starting comprehensive comparison setup"
log "Script directory: $SCRIPT_DIR"
log "Virtual environment: $VENV_PATH"
log "Output directory: $OUTPUT_DIR"
log "Log file: $LOG_FILE"

# Check if we're in dry-run mode
if [ "$DRY_RUN" = true ]; then
    log "🔍 DRY RUN MODE - showing what would be done"
fi

# Step 1: Verify required files exist
log "📋 Step 1: Verifying required files..."

required_files=(
    "input_data/insurance_fillings.csv"
    "input_data/medical_codes_non_rx.csv"
     "input_data/zip_code_fl.csv"
     "input_data/zip_code_ga.csv"
    "input_data/zip_code_oh.csv"
    "$PYTHON_SCRIPT"
    "enhanced_benefit_calculator.py"
    "ProviderPriceInformation.py"
    "config.py"
)

missing_files=()
for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
        missing_files+=("$file")
    else
        log "  ✅ Found: $file"
    fi
done

if [ ${#missing_files[@]} -ne 0 ]; then
    log "❌ Missing required files:"
    for file in "${missing_files[@]}"; do
        log "  - $file"
    done
    exit 1
fi

# Check data file contents
log "📊 Data file summary:"
insurance_count=$(tail -n +2 "input_data/insurance_fillings.csv" 2>/dev/null | wc -l || echo "unknown")
medical_codes_count=$(tail -n +2 "input_data/medical_codes_non_rx.csv" 2>/dev/null | wc -l || echo "unknown")
fl_zips=$(tail -n +2 "input_data/zip_code_fl.csv" 2>/dev/null | wc -l || echo "unknown")
ga_zips=$(tail -n +2 "input_data/zip_code_ga.csv" 2>/dev/null | wc -l || echo "unknown")
oh_zips=$(tail -n +2 "input_data/zip_code_oh.csv" 2>/dev/null | wc -l || echo "unknown")

log "  - Insurance filings: $insurance_count"
log "  - Medical codes: $medical_codes_count"
log "  - FL zip codes: $fl_zips"
log "  - GA zip codes: $ga_zips"
log "  - OH zip codes: $oh_zips"

# Calculate estimated combinations
if [[ "$insurance_count" =~ ^[0-9]+$ ]] && [[ "$medical_codes_count" =~ ^[0-9]+$ ]] && [[ "$fl_zips" =~ ^[0-9]+$ ]] && [[ "$ga_zips" =~ ^[0-9]+$ ]] && [[ "$oh_zips" =~ ^[0-9]+$ ]]; then
    total_zips=$((fl_zips + ga_zips + oh_zips))
    total_combinations=$((insurance_count * medical_codes_count * total_zips))
    log "  📈 Estimated combinations to process: $(printf "%'d" $total_combinations)"
    
    # Estimate runtime (very rough estimate: 1-2 seconds per combination)
    estimated_seconds=$((total_combinations * 2))
    estimated_hours=$((estimated_seconds / 3600))
    log "  ⏱️  Estimated runtime: ~$estimated_hours hours (very rough estimate)"
fi

# Step 2: Set up Python virtual environment
log "🐍 Step 2: Setting up Python virtual environment..."

if [ ! -d "$VENV_PATH" ]; then
    log "Creating new virtual environment: $VENV_PATH"
    if [ "$DRY_RUN" = false ]; then
        python3 -m venv "$VENV_PATH"
        if [ $? -ne 0 ]; then
            log "❌ Failed to create virtual environment"
            exit 1
        fi
    fi
else
    log "✅ Virtual environment already exists: $VENV_PATH"
fi

# Activate virtual environment
log "Activating virtual environment..."
if [ "$DRY_RUN" = false ]; then
    source "$VENV_PATH/bin/activate"
    log "✅ Virtual environment activated"
fi

# Step 3: Install/verify dependencies
log "📦 Step 3: Installing/verifying dependencies..."

if [ "$DRY_RUN" = false ]; then
    # Check if requirements.txt exists in parent directory
    if [ -f "../requirements.txt" ]; then
        log "Installing dependencies from ../requirements.txt..."
        pip install --upgrade pip
        pip install -r ../requirements.txt
        if [ $? -ne 0 ]; then
            log "❌ Failed to install dependencies from requirements.txt"
            exit 1
        fi
    else
        log "Installing essential dependencies individually..."
        pip install --upgrade pip
        pip install pandas boto3 snowflake-connector-python requests python-dateutil
        if [ $? -ne 0 ]; then
            log "❌ Failed to install essential dependencies"
            exit 1
        fi
    fi
    
    # Verify key imports work
    log "Verifying key imports..."
    python3 -c "
import pandas as pd
import boto3
import snowflake.connector
import requests
from enhanced_benefit_calculator import EnhancedBenefitCalculator
from ProviderPriceInformation import ProviderPriceInformation
print('✅ All key imports successful')
" 2>&1 | tee -a "$LOG_FILE"
    
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        log "❌ Import verification failed"
        exit 1
    fi
else
    log "🔍 DRY RUN: Would install dependencies and verify imports"
fi

# Step 4: Pre-flight checks
log "🔍 Step 4: Pre-flight checks..."

if [ "$DRY_RUN" = false ]; then
    # Check AWS credentials
    log "Checking AWS credentials..."
    if ! aws sts get-caller-identity >/dev/null 2>&1; then
        log "⚠️  Warning: AWS credentials not configured or invalid"
        log "   Make sure to configure AWS credentials before running"
        log "   Run: aws configure"
    else
        log "✅ AWS credentials configured"
    fi
    
    # Check if we can connect to Snowflake (quick test)
    log "Testing Snowflake connectivity..."
    python3 -c "
try:
    from enhanced_benefit_calculator import EnhancedBenefitCalculator
    calc = EnhancedBenefitCalculator()
    # Don't actually run a calculation, just test initialization
    calc.close_connection()
    print('✅ Snowflake connectivity test passed')
except Exception as e:
    print(f'⚠️  Snowflake connectivity test failed: {e}')
    print('   This may be due to credentials or network issues')
" 2>&1 | tee -a "$LOG_FILE"
else
    log "🔍 DRY RUN: Would check AWS credentials and Snowflake connectivity"
fi

# Step 5: Setup output file management for long-running job
log "📁 Step 5: Setting up output file management..."

if [ "$DRY_RUN" = false ]; then
    # Create a timestamped output subdirectory for this run
    RUN_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    RUN_OUTPUT_DIR="$OUTPUT_DIR/run_$RUN_TIMESTAMP"
    mkdir -p "$RUN_OUTPUT_DIR"
    
    log "✅ Created run-specific output directory: $RUN_OUTPUT_DIR"
    
    # Create a progress monitoring script
    cat > "$RUN_OUTPUT_DIR/monitor_progress.sh" << 'EOF'
#!/bin/bash
# Progress monitoring script for comprehensive comparison
echo "=== Comprehensive Comparison Progress Monitor ==="
echo "Run started: $(date)"
echo ""

# Monitor log file
LOG_FILE="$(dirname "$0")/../comparison_run_*.log"
if ls $LOG_FILE 1> /dev/null 2>&1; then
    echo "Recent log entries:"
    tail -20 $LOG_FILE
else
    echo "No log file found yet"
fi

echo ""
echo "Output files created so far:"
find "$(dirname "$0")" -name "*.csv" -type f -exec ls -lh {} \;

echo ""
echo "To continuously monitor progress, run:"
echo "  tail -f $LOG_FILE"
EOF
    chmod +x "$RUN_OUTPUT_DIR/monitor_progress.sh"
    
    log "✅ Created progress monitoring script: $RUN_OUTPUT_DIR/monitor_progress.sh"
else
    RUN_OUTPUT_DIR="$OUTPUT_DIR/run_TIMESTAMP"
    log "🔍 DRY RUN: Would create output directory: $RUN_OUTPUT_DIR"
fi

# Step 6: Run the comprehensive comparison
log "🚀 Step 6: Running comprehensive comparison..."
log "This may take several hours depending on data size..."

if [ "$DRY_RUN" = false ]; then
    # Store the start time
    START_TIME=$(date +%s)
    log "Comparison started at: $(date)"
    
    # Run the Python script with output redirection
    # The script will create its own output files in the "output" directory
    log "Executing: python3 $PYTHON_SCRIPT"
    
    # Run with both stdout and stderr captured
    if python3 "$PYTHON_SCRIPT" 2>&1 | tee -a "$LOG_FILE"; then
        END_TIME=$(date +%s)
        DURATION=$((END_TIME - START_TIME))
        HOURS=$((DURATION / 3600))
        MINUTES=$(((DURATION % 3600) / 60))
        SECONDS=$((DURATION % 60))
        
        log "✅ Comprehensive comparison completed successfully!"
        log "Total runtime: ${HOURS}h ${MINUTES}m ${SECONDS}s"
        
        # Extract execution ID from log file for easy reference
        EXECUTION_ID=$(grep "🆔 Execution ID:" "$LOG_FILE" | tail -1 | sed 's/.*🆔 Execution ID: \([^ ]*\).*/\1/')
        if [ ! -z "$EXECUTION_ID" ]; then
            log ""
            log "🆔 EXECUTION ID: $EXECUTION_ID"
            log "📊 Query your results with this execution ID:"
            log "   SELECT * FROM WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST WHERE EXECUTION_ID = '$EXECUTION_ID';"
        fi
    else
        log "❌ Comprehensive comparison failed!"
        exit 1
    fi
else
    log "🔍 DRY RUN: Would execute: python3 $PYTHON_SCRIPT"
fi

# Step 7: Organize and summarize results
log "📋 Step 7: Organizing and summarizing results..."

if [ "$DRY_RUN" = false ]; then
    # Move output files to our run-specific directory
    # No output files to move since results are written directly to database
    log "Results have been written directly to Snowflake database"
    
    # Create a summary report
    SUMMARY_FILE="$RUN_OUTPUT_DIR/comparison_summary.txt"
    cat > "$SUMMARY_FILE" << EOF
COMPREHENSIVE BENEFIT VS PROVIDER PRICE COMPARISON SUMMARY
==========================================================

Run Details:
- Start Time: $(date)
- Script Version: comprehensive_benefit_provider_comparison.py
- Output Directory: $RUN_OUTPUT_DIR

Data Processed:
- Insurance Filings: $insurance_count
- Medical Codes: $medical_codes_count
- ZIP Codes: FL($fl_zips), GA($ga_zips), OH($oh_zips)
- Total Combinations: $(printf "%'d" $total_combinations)

Database Results:
- Table: WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST
- Results written directly to Snowflake database
EOF
    
    cat >> "$SUMMARY_FILE" << EOF

Key Results:
- Providers where price > benefit amount have been identified
- Results are separated by state (FL, GA, OH) in database
- Each record includes detailed comparison data with execution_id

Files:
- comparison_summary.txt: This summary
- monitor_progress.sh: Progress monitoring script
- comparison_run_*.log: Detailed execution log

To analyze results:
1. Query WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST in Snowflake
2. Filter by execution_id to get results from this specific run
3. Sort by PRICE_VS_FACILITY_DIFF or PRICE_VS_NON_FACILITY_DIFF to find largest gaps
4. Filter by STATE, INSURANCE_FILING_UUID, or SIDECAR_CODE as needed
EOF
    
    log "✅ Created summary report: $SUMMARY_FILE"
    
    # Show final summary
    log ""
    log "🎉 COMPREHENSIVE COMPARISON COMPLETE!"
    log "======================================"
    log "📁 Results location: $RUN_OUTPUT_DIR"
    log "📄 Summary report: $SUMMARY_FILE"
    log "📊 Monitor script: $RUN_OUTPUT_DIR/monitor_progress.sh"
    log ""
    # Extract execution ID from log file for final summary
    FINAL_EXECUTION_ID=$(grep "🆔 Execution ID:" "$LOG_FILE" | tail -1 | sed 's/.*🆔 Execution ID: \([^ ]*\).*/\1/')
    
    log "Database results written to:"
    log "  💾 Table: WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST"
    if [ ! -z "$FINAL_EXECUTION_ID" ]; then
        log "  🆔 Execution ID: $FINAL_EXECUTION_ID"
        log "  📊 Query: SELECT * FROM WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST WHERE EXECUTION_ID = '$FINAL_EXECUTION_ID';"
    else
        log "  🆔 Use execution_id from the logs to query your specific results"
    fi
    
else
    log "🔍 DRY RUN: Would organize results and create summary report"
fi

# Final instructions
log ""
log "📋 Next Steps:"
log "1. Review the summary report: $SUMMARY_FILE"
log "2. Query WORKSPACE.SCRATCH.BENEFIT_PROVIDER_COMPARISON_TEST in Snowflake"
log "3. Filter by execution_id to get results from this specific run"
log "4. Use the data for business analysis and decision making"

if [ "$DRY_RUN" = false ]; then
    # Deactivate virtual environment
    deactivate 2>/dev/null || true
fi

log "✅ Script completed successfully!"