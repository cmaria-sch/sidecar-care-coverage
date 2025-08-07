#!/bin/bash

# Quick test script to verify the comprehensive comparison setup
# This runs a dry-run to check all dependencies and setup without actually running the comparison

echo "🧪 Testing Comprehensive Comparison Setup"
echo "========================================="

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Running dry-run to verify setup..."
./run_comprehensive_comparison.sh --dry-run

echo ""
echo "🔍 Quick file verification:"

# Check data files
echo "Data files:"
for file in data/insurance_fillings.csv data/medical_codes_non_rx.csv data/zip_code_*.csv; do
    if [ -f "$file" ]; then
        lines=$(wc -l < "$file" 2>/dev/null || echo "0")
        echo "  ✅ $file ($lines lines)"
    else
        echo "  ❌ $file (missing)"
    fi
done

echo ""
echo "Python scripts:"
for file in comprehensive_benefit_provider_comparison.py enhanced_benefit_calculator.py provider_price_information.py config.py; do
    if [ -f "$file" ]; then
        echo "  ✅ $file"
    else
        echo "  ❌ $file (missing)"
    fi
done

echo ""
echo "📋 To run the actual comparison:"
echo "  ./run_comprehensive_comparison.sh"
echo ""
echo "📋 To monitor progress during execution:"
echo "  tail -f comprehensive_comparison_results/run_*/comparison_run_*.log"