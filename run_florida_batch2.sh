#!/bin/bash

echo "🌴 Starting Sidecar Data Collection - FLORIDA BATCH 2/2"
echo "======================================================="
echo ""
echo "📊 Collection Details:"
echo "   • State: Florida (FL)"
echo "   • Batch: 2 of 2"
echo "   • Zip codes: ~473 (second half)"
echo "   • Drugs: 100"
echo "   • Total combinations: ~47,300"
echo "   • Estimated time: ~5.2 hours"
echo "   • Rate: 2.5 requests/second (SAFE)"
echo ""
echo "🚀 Starting collection..."
echo ""

# Activate virtual environment if it exists
if [ -d "sidecar_env" ]; then
    echo "🔧 Activating virtual environment..."
    source sidecar_env/bin/activate
fi

# Run the collection for Florida batch 2
python3 data_collection.py --states FL --batch 2 --total-batches 2

echo ""
echo "✅ Florida Batch 2/2 completed!"
echo "📁 Check the results/ directory for output files"
echo "🎉 Florida state collection COMPLETE!" 