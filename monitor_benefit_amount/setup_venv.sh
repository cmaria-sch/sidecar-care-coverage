#!/bin/bash

# Setup Virtual Environment for Benefit Calculator
echo "🔧 Setting up virtual environment for Benefit Calculator"
echo "======================================================"

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv benefit_calc_env

if [ $? -ne 0 ]; then
    echo "❌ Failed to create virtual environment"
    exit 1
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source benefit_calc_env/bin/activate

# Upgrade pip
echo "⬆️ Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r ../requirements.txt

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Setup completed successfully!"
    echo ""
    echo "🚀 To use the benefit calculator:"
    echo "  source benefit_calc_env/bin/activate"
    echo "  python calculate_benefit_amount.py"
    echo ""
    echo "🧪 To run tests:"
    echo "  ./run_tests.sh"
else
    echo "❌ Failed to install dependencies"
    exit 1
fi