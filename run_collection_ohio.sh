#!/bin/bash

echo "🏛️  Starting Sidecar Data Collection - OHIO ONLY"
echo "================================================"
echo ""
echo "📊 Collection Details:"
echo "   • State: Ohio (OH)"
echo "   • Zip codes: 954"
echo "   • Drugs: 100"
echo "   • Total combinations: 95,400"
echo "   • Estimated time: ~2.7 hours"
echo "   • Rate: 10 requests/second"
echo ""
echo "🚀 Starting collection..."
echo ""

# Activate virtual environment if it exists
if [ -d "sidecar_env" ]; then
    echo "🔧 Activating virtual environment..."
    source sidecar_env/bin/activate
fi

# Run the collection for Ohio only
python3 data_collection.py --states OH

echo ""
echo "✅ Ohio collection completed!"
echo "📁 Check the results/ directory for output files" 