#!/bin/bash

# Sidecar Test Runner Script
# This script sets up and runs benefit calculator and provider search tests

echo "🚀 Sidecar Test Suite"
echo "===================="

# Check if we're in the right directory
if [ ! -f "calculate_benefit_amount.py" ]; then
    echo "❌ Error: Please run this script from the check_benefit_amount directory"
    exit 1
fi

# Setup virtual environment if needed
VENV_DIR="benefit_calc_env"

if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv $VENV_DIR
    if [ $? -ne 0 ]; then
        echo "❌ Failed to create virtual environment"
        exit 1
    fi
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source $VENV_DIR/bin/activate

# Check and install dependencies
echo "📦 Checking Python dependencies..."
python -c "import pandas, boto3, snowflake.connector, requests" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Missing dependencies. Installing from requirements.txt..."
    pip install -r ../requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install dependencies. Please check your pip setup."
        deactivate
        exit 1
    fi
fi

echo "✅ Dependencies check passed"

# Function to show usage
show_usage() {
    echo ""
    echo "Usage: $0 <test_type> <input_csv>"
    echo ""
    echo "Test Types:"
    echo "  benefit   - Run benefit calculator comparison tests"
    echo "  provider  - Run provider search comparison tests"
    echo ""
    echo "Parameters:"
    echo "  test_type  - Required: 'benefit' or 'provider'"
    echo "  input_csv  - Required: Path to CSV file with test cases"
    echo ""
    echo "Examples:"
    echo "  $0 benefit benefit_amount_test_cases.csv"
    echo "  $0 provider provider_test_data1.csv"
    echo "  $0 provider test_data/provider_test_data1.csv"
}

# Parse command line arguments - NO DEFAULTS, require both arguments
if [ $# -lt 2 ]; then
    echo "❌ Error: Both test type and input CSV file are required"
    show_usage
    exit 1
fi

TEST_TYPE=$1
INPUT_CSV=$2

# Create output directory
mkdir -p test_results
echo "✅ Output directory created: test_results/"

# Validate test type
case $TEST_TYPE in
    "benefit"|"provider"|"help"|"--help"|"-h")
        ;;
    *)
        echo "❌ Invalid test type: $TEST_TYPE"
        echo "❌ Valid options: benefit, provider"
        show_usage
        exit 1
        ;;
esac

if [ "$TEST_TYPE" = "help" ] || [ "$TEST_TYPE" = "--help" ] || [ "$TEST_TYPE" = "-h" ]; then
    show_usage
    exit 0
fi

# Function to run benefit tests
run_benefit_tests() {
    echo ""
    echo "🧪 Starting Benefit Calculator vs API Comparison Tests..."
    echo "========================================================="
    
    # Check if benefit test data exists
    if [ ! -f "$INPUT_CSV" ]; then
        echo "❌ Benefit test data file not found: $INPUT_CSV"
        return 1
    fi
    
    echo "✅ Benefit test data file found: $INPUT_CSV"
    
    # Run benefit comparison tests
    python compare_api_test.py "$INPUT_CSV" "test_results/benefit_comparison_results_$(date +%Y%m%d_%H%M%S).csv"
    return $?
}

# Function to run provider tests
run_provider_tests() {
    echo ""
    echo "🧪 Starting Provider Search vs API Comparison Tests..."
    echo "======================================================"
    
    # Check if provider test data exists
    if [ ! -f "$INPUT_CSV" ]; then
        echo "❌ Provider test data file not found: $INPUT_CSV"
        return 1
    fi
    
    echo "✅ Provider test data file found: $INPUT_CSV"
    
    # Run provider comparison tests
    python compare_provider_test.py "$INPUT_CSV" "test_results/provider_comparison_results_$(date +%Y%m%d_%H%M%S).csv"
    return $?
}

# Run tests based on type
TEST_SUCCESS=0

case $TEST_TYPE in
    "benefit")
        run_benefit_tests
        TEST_SUCCESS=$?
        ;;
    "provider")
        run_provider_tests
        TEST_SUCCESS=$?
        ;;
esac

# Report results
echo ""
echo "📊 TEST RESULTS SUMMARY"
echo "======================="

case $TEST_TYPE in
    "benefit")
        if [ $TEST_SUCCESS -eq 0 ]; then
            echo "✅ Benefit calculator tests completed successfully!"
        else
            echo "❌ Benefit calculator tests failed!"
        fi
        ;;
    "provider")
        if [ $TEST_SUCCESS -eq 0 ]; then
            echo "✅ Provider search tests completed successfully!"
        else
            echo "❌ Provider search tests failed!"
        fi
        ;;
esac

# Show available scripts
echo ""
echo "📊 Results saved in test_results/ directory"
echo ""
echo "📋 Available test scripts (remember to activate venv first):"
echo "  source $VENV_DIR/bin/activate"
echo ""
echo "Benefit Calculator Tests:"
echo "  - Interactive testing: python test_benefit_calculator.py"
echo "  - Quick single test: python quick_test.py <sidecar_code> <zip_code>"
echo "  - API comparison: python compare_api_test.py <csv_file>"
echo ""
echo "Provider Search Tests:"
echo "  - Provider comparison: python compare_provider_test.py <csv_file> <output_csv>"
echo "  - Single provider test: python test_final_case.py"

# Exit with error if tests failed
if [ $TEST_SUCCESS -ne 0 ]; then
    echo ""
    echo "💡 Common issues:"
    echo "  - AWS credentials not configured"
    echo "  - Snowflake access issues" 
    echo "  - Invalid test data in CSV"
    echo "  - API connectivity problems"
    exit 1
fi

# Deactivate virtual environment
deactivate