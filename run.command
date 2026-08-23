#!/bin/bash
# Double-click this file to run the paper-trader once.
cd "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Extra Projects/Polymarket Consesus Trading"
echo "Running the Polymarket paper-trader..."
python3 paper_trader.py
echo ""
echo "------------------------------------------------------------"
echo "Done. You can close this window."
read -n 1 -s -r -p "Press any key to close."
