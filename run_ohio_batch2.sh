#!/bin/bash

echo "🏛️  Starting Sidecar Data Collection - OHIO BATCH 2/2"
echo "===================================================="
echo ""
echo "📊 Collection Details:"
echo "   • State: Ohio (OH)"
echo "   • Batch: 2 of 2"
echo "   • Zip codes: ~477 (second half)"
echo "   • Drugs: 100"
echo "   • Total combinations: ~47,700"
echo "   • Estimated time: ~5.3 hours"
echo "   • Rate: 2.5 requests/second (SAFE)"
echo ""
echo "📝 Data Collection Features:"
echo "   • Comprehensive endpoint data capture"
echo "   • All pharmacy pricing and location details"
echo "   • Complete drug descriptions and medical info"
echo "   • Member coverage and benefit information"
echo "   • All available dosage/quantity/form options"
echo "   • Hours of operation and pharmacy details"
echo ""
echo "🚀 Starting collection..."
echo ""

# Activate virtual environment if it exists
if [ -d "sidecar_env" ]; then
    echo "🔧 Activating virtual environment..."
    source sidecar_env/bin/activate
fi

# Run the collection for Ohio batch 2
python3 data_collection.py --states OH --batch 2 --total-batches 2

echo ""
echo "✅ Ohio Batch 2/2 completed!"
echo "📁 Check the results/ directory for output files"
echo "🎉 Ohio state collection COMPLETE!" 