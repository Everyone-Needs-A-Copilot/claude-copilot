#!/bin/bash

# MCP Server Build Verification
# This script builds all MCP servers and reports results

set -e  # Exit on first error

echo "========================================="
echo "MCP SERVER BUILD VERIFICATION"
echo "Started: $(date)"
echo "========================================="
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track results
declare -a RESULTS
BUILD_COUNT=0
SUCCESS_COUNT=0

# Function to build a server
build_server() {
    local server_name=$1
    local server_path="/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/$server_name"

    echo "----------------------------------------"
    echo "Building: $server_name"
    echo "----------------------------------------"

    cd "$server_path" || {
        echo -e "${RED}❌ ERROR: Cannot cd to $server_path${NC}"
        RESULTS+=("$server_name: FAIL (directory error)")
        return 1
    }

    # Clean any existing dist
    rm -rf dist

    # Run build
    if npm run build 2>&1 | tee "/tmp/build-$server_name.log"; then
        if [ -d "dist" ] && [ "$(ls -A dist)" ]; then
            local js_count=$(find dist -name "*.js" | wc -l | tr -d ' ')
            echo -e "${GREEN}✅ SUCCESS: $server_name${NC}"
            echo "   - Generated $js_count JavaScript files"
            RESULTS+=("$server_name: PASS ($js_count files)")
            ((SUCCESS_COUNT++))
        else
            echo -e "${RED}❌ FAIL: $server_name (no output files)${NC}"
            RESULTS+=("$server_name: FAIL (no dist files)")
        fi
    else
        echo -e "${RED}❌ FAIL: $server_name (build error)${NC}"
        echo "   - See /tmp/build-$server_name.log for details"
        RESULTS+=("$server_name: FAIL (build error)")
    fi

    ((BUILD_COUNT++))
    echo ""
}

# Build each server
build_server "copilot-memory"
build_server "skills-copilot"
build_server "websocket-bridge"

echo ""

# Generate summary
echo "========================================="
echo "BUILD VERIFICATION SUMMARY"
echo "========================================="
echo ""

for result in "${RESULTS[@]}"; do
    if [[ $result == *"PASS"* ]]; then
        echo -e "${GREEN}$result${NC}"
    else
        echo -e "${RED}$result${NC}"
    fi
done

echo ""
echo "Builds: $SUCCESS_COUNT/$BUILD_COUNT successful"
echo "Completed: $(date)"
echo ""

if [ $SUCCESS_COUNT -eq $BUILD_COUNT ]; then
    echo -e "${GREEN}✅ All builds passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Some builds failed${NC}"
    echo "Check log files in /tmp/build-*.log"
    exit 1
fi
