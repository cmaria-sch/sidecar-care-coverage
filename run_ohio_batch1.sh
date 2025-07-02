#!/bin/bash

echo "🏛️  Starting Sidecar Data Collection - OHIO BATCH 1/2"
echo "===================================================="
echo ""
echo "📊 Collection Details:"
echo "   • State: Ohio (OH)"
echo "   • Batch: 1 of 2"
echo "   • Zip codes: ~477 (first half)"
echo "   • Drugs: 100"
echo "   • Total combinations: ~47,700"
echo "   • Estimated time: ~5.3 hours"
echo "   • Rate: 2.5 requests/second (SAFE)"
echo ""
echo "🚀 Starting collection..."
echo ""

# Activate virtual environment if it exists
if [ -d "sidecar_env" ]; then
    echo "🔧 Activating virtual environment..."
    source sidecar_env/bin/activate
fi

# Run the collection for Ohio batch 1
python3 data_collection.py --states OH --batch 1 --total-batches 2

echo ""
echo "✅ Ohio Batch 1/2 completed!"
echo "📁 Check the results/ directory for output files"
echo "▶️  Next: Run ./run_ohio_batch2.sh to complete Ohio" 