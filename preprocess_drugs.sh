#!/bin/bash

# Preprocess Drugs CSV Script
# Adds care_uuid column to the drugs CSV file

echo "🔧 Preprocessing drugs CSV to add care_uuid column..."
echo "This will look up UUIDs for all procedure codes in the CSV file."
echo ""

# Default file
INPUT_FILE="top_100_drugs.csv"
OUTPUT_FILE=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -i|--input)
            INPUT_FILE="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -i, --input FILE   Input CSV file (default: top_100_drugs.csv)"
            echo "  -o, --output FILE  Output CSV file (default: input_with_uuids.csv)"
            echo "  -h, --help         Show this help message"
            echo ""
            echo "Example:"
            echo "  $0                              # Process top_100_drugs.csv"
            echo "  $0 -i my_drugs.csv             # Process custom file"
            echo "  $0 -i drugs.csv -o processed.csv  # Custom input and output"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Check if input file exists
if [ ! -f "$INPUT_FILE" ]; then
    echo "❌ Error: Input file '$INPUT_FILE' not found"
    exit 1
fi

# Activate the virtual environment
echo "🐍 Activating virtual environment..."
source sidecar_env/bin/activate

# Make sure we have the environment set up
if [ -z "$TOKEN" ] || [ -z "$MEMBERUUID" ]; then
    echo "🔑 Getting authentication tokens..."
    source ./grab_token.sh
fi

echo "📁 Input file: $INPUT_FILE"
if [ -n "$OUTPUT_FILE" ]; then
    echo "📁 Output file: $OUTPUT_FILE"
    python preprocess_drugs_csv.py --input "$INPUT_FILE" --output "$OUTPUT_FILE"
else
    echo "📁 Output file: ${INPUT_FILE%.*}_with_uuids.csv"
    python preprocess_drugs_csv.py --input "$INPUT_FILE"
fi

echo ""
echo "✅ Preprocessing complete!"
echo "You can now run the data collection with the processed CSV file." 