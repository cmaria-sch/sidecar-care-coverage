#!/bin/bash

# Sidecar Care Coverage Data Collection - Environment Setup
echo "Setting up virtual environment for Sidecar Care Coverage data collection..."

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not installed. Please install Python 3 first."
    exit 1
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv sidecar_env

# Activate virtual environment
echo "Activating virtual environment..."
source sidecar_env/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# Make scripts executable
echo "Making scripts executable..."
chmod +x grab_token.sh
chmod +x run_collection.sh

echo ""
echo "✅ Environment setup complete!"
echo ""
echo "To activate the environment in the future, run:"
echo "  source sidecar_env/bin/activate"
echo ""
echo "To run the data collection:"
echo "  source sidecar_env/bin/activate"
echo "  python3 data_collection.py"
echo ""
echo "Or use the convenience script:"
echo "  ./run_collection.sh" 