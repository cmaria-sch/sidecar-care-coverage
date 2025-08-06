#!/bin/bash
# 
# Run Comprehensive Comparison with Log Capture
# ==============================================
# 
# This script runs the comprehensive comparison and captures ALL output 
# (including stdout, stderr, and any errors) to a timestamped log file.
#
# Usage:
#   chmod +x run_with_log_capture.sh
#   ./run_with_log_capture.sh
#
# The script will:
# 1. Create a timestamped log file
# 2. Run the comprehensive comparison 
# 3. Show output on screen AND save to log file
# 4. Show log file location when done

# Create logs directory
mkdir -p logs

# Generate timestamp for log file
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/comprehensive_comparison_${TIMESTAMP}.log"

echo "🚀 Starting Comprehensive Comparison with Log Capture"
echo "📝 Log file: $LOG_FILE"
echo "📅 Started at: $(date)"
echo "================================================================================"

# Run the Python script and capture ALL output (stdout + stderr) to both screen and log file
python comprehensive_benefit_provider_comparison.py 2>&1 | tee "$LOG_FILE"

# Capture the exit code from the Python script (not from tee)
EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo "================================================================================"
echo "📁 Process completed with exit code: $EXIT_CODE"
echo "📝 Full log saved to: $LOG_FILE"
echo "🔍 Review the log with: cat $LOG_FILE"
echo "📊 Or search for errors: grep -i error $LOG_FILE"
echo "⚠️  Or search for warnings: grep -i warning $LOG_FILE"
echo "🎯 Or search for specific terms: grep -i 'snowflake\|connection\|failed' $LOG_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Process completed successfully!"
else
    echo "❌ Process failed with exit code $EXIT_CODE"
    echo "🔍 Check the log file for detailed error information"
fi

exit $EXIT_CODE