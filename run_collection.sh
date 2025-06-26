#!/bin/bash

# Sidecar Care Coverage Data Collection Runner
echo "Starting Sidecar Care Coverage data collection..."

# Check if virtual environment exists
if [ ! -d "sidecar_env" ]; then
    echo "Virtual environment not found. Please run ./setup_environment.sh first."
    exit 1
fi

# Activate virtual environment
echo "Activating virtual environment..."
source sidecar_env/bin/activate

# Function to grab fresh token
grab_fresh_token() {
    echo "🔄 Session token expired or invalid. Grabbing fresh token..."
    if ./grab_token.sh > /tmp/token_output.txt 2>&1; then
        echo "✅ Successfully obtained fresh token"
        # Extract token and memberUUID from the output, cleaning any extra whitespace/quotes
        TOKEN=$(grep "TOKEN=" /tmp/token_output.txt | cut -d'=' -f2 | tr -d '\n\r"'"'" | xargs)
        MEMBERUUID=$(grep "MEMBERUUID=" /tmp/token_output.txt | cut -d'=' -f2 | tr -d '\n\r"'"'" | xargs)
        
        # Export cleaned values
        export TOKEN="$TOKEN"
        export MEMBERUUID="$MEMBERUUID"
        
        # Verify we got valid values
        if [ -z "$TOKEN" ] || [ -z "$MEMBERUUID" ]; then
            echo "❌ Failed to extract TOKEN or MEMBERUUID from output"
            cat /tmp/token_output.txt
            rm -f /tmp/token_output.txt
            return 1
        fi
        
        rm -f /tmp/token_output.txt
        return 0
    else
        echo "❌ Failed to grab fresh token"
        cat /tmp/token_output.txt
        rm -f /tmp/token_output.txt
        return 1
    fi
}

# Check if we need a fresh token (if TOKEN env var doesn't exist)
if [ -z "$TOKEN" ]; then
    echo "🔑 No token found in environment. Getting fresh token..."
    grab_fresh_token
    if [ $? -ne 0 ]; then
        echo "Failed to obtain token. Exiting."
        exit 1
    fi
fi

# Check if CSV file exists
CSV_FILE="top_100_drugs.csv"
if [ ! -f "$CSV_FILE" ]; then
    echo "Warning: CSV file '$CSV_FILE' not found."
    echo "Please ensure the CSV file is in the current directory."
    read -p "Continue anyway? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Display usage information if --help is passed
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo ""
    echo "Usage: ./run_collection.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --test          Run in test mode (only 10 drugs × 6 zip codes = 60 combinations)"
    echo "  --csv-file FILE Use custom CSV file instead of top_100_drugs.csv"
    echo "  --help, -h      Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./run_collection.sh                    # Full collection (100 drugs × 2511 zip codes)"
    echo "  ./run_collection.sh --test             # Test with 60 combinations"
    echo "  ./run_collection.sh --test --csv-file my_drugs.csv"
    echo ""
    exit 0
fi

# Check for test mode
if [[ "$*" == *"--test"* ]]; then
    echo "🧪 Running in TEST MODE (60 combinations total)"
    echo "   This will process only 10 drugs × 6 zip codes (2 from each state)"
    echo "   Estimated runtime: 1-2 minutes"
    echo ""
fi

# Run the data collection script with retry logic for token expiration
echo "Running data collection script..."

# Function to run data collection with token refresh on failure
run_data_collection() {
    local max_retries=2
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        echo "Attempt $((retry_count + 1)) of $max_retries..."
        
        # Run the data collection script
        python3 data_collection.py "$@"
        exit_code=$?
        
        # If successful, break out of retry loop
        if [ $exit_code -eq 0 ]; then
            echo "✅ Data collection completed successfully!"
            return 0
        fi
        
        # Check if the error might be due to token expiration
        # Look for authentication errors in the recent log
        if grep -q -i "401\|unauthorized\|token.*expired\|authentication.*failed" logs/sidecar_api_collection.log 2>/dev/null; then
            echo "🔍 Detected possible token expiration error"
            
            if [ $retry_count -lt $((max_retries - 1)) ]; then
                grab_fresh_token
                if [ $? -eq 0 ]; then
                    echo "🔄 Retrying data collection with fresh token..."
                    retry_count=$((retry_count + 1))
                    continue
                else
                    echo "❌ Failed to refresh token. Cannot retry."
                    return 1
                fi
            fi
        else
            echo "❌ Data collection failed with non-authentication error"
            return $exit_code
        fi
        
        retry_count=$((retry_count + 1))
    done
    
    echo "❌ Data collection failed after $max_retries attempts"
    return 1
}

# Run data collection with retry logic
run_data_collection "$@"
collection_exit_code=$?

echo ""
if [ $collection_exit_code -eq 0 ]; then
    echo "Data collection completed!"
    echo "Check the log file: logs/sidecar_api_collection.log"
else
    echo "Data collection failed. Check the log file: logs/sidecar_api_collection.log"
fi

# Show appropriate output file message based on test mode
if [ $collection_exit_code -eq 0 ]; then
    if [[ "$*" == *"--test"* ]]; then
        echo "Output CSV file: results/sidecar_data_test_[timestamp].csv"
        echo ""
        echo "🧪 Test completed! To run full collection, use:"
        echo "   ./run_collection.sh"
    else
        echo "Output CSV file: results/sidecar_data_[timestamp].csv"
    fi
fi 