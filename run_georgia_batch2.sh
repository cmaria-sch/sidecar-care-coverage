#!/bin/bash

echo "🍑 Starting Sidecar Data Collection - GEORGIA BATCH 2/2"
echo "======================================================="
echo ""
echo "📊 Collection Details:"
echo "   • State: Georgia (GA)"
echo "   • Batch: 2 of 2"
echo "   • Zip codes: ~303 (second half)"
echo "   • Drugs: 100"
echo "   • Total combinations: ~30,300"
echo "   • Estimated time: ~3.4 hours"
echo "   • Rate: 2.5 requests/second (SAFE)"
echo ""
echo "🚀 Starting collection..."
echo ""

# Activate virtual environment if it exists
if [ -d "sidecar_env" ]; then
    echo "🔧 Activating virtual environment..."
    source sidecar_env/bin/activate
fi

# Run the collection for Georgia batch 2
python3 data_collection.py --states GA --batch 2 --total-batches 2

echo ""
echo "✅ Georgia Batch 2/2 completed!"
echo "📁 Check the results/ directory for output files"
echo "🎉 Georgia state collection COMPLETE!" 