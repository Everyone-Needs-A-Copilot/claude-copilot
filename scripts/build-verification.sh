#!/bin/bash

# Build Verification Script for MCP Servers
# Runs build for each MCP server and reports results

set +e  # Don't exit on error, we want to collect all results

echo "========================================="
echo "MCP Server Build Verification"
echo "========================================="
echo ""

# Track overall status
ALL_SUCCESS=true

# Function to build a server
build_server() {
    local server_name=$1
    local server_path="/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/$server_name"

    echo "----------------------------------------"
    echo "Building: $server_name"
    echo "----------------------------------------"

    if [ ! -d "$server_path" ]; then
        echo "❌ ERROR: Directory not found: $server_path"
        ALL_SUCCESS=false
        return 1
    fi

    cd "$server_path" || exit 1

    # Check if node_modules exists
    if [ ! -d "node_modules" ]; then
        echo "⚠️  WARNING: node_modules not found. Running npm install first..."
        npm install
    fi

    # Run build
    echo "Running: npm run build"
    npm run build 2>&1

    if [ $? -eq 0 ]; then
        echo "✅ SUCCESS: $server_name built successfully"

        # Check if dist directory was created
        if [ -d "dist" ]; then
            echo "   - dist/ directory created"
            echo "   - Files in dist/: $(ls dist | wc -l | tr -d ' ')"
        fi
    else
        echo "❌ FAILED: $server_name build failed"
        ALL_SUCCESS=false
    fi

    echo ""
}

# Build each server
build_server "copilot-memory"
build_server "skills-copilot"
build_server "websocket-bridge"

# Summary
echo "========================================="
echo "Build Verification Summary"
echo "========================================="

if [ "$ALL_SUCCESS" = true ]; then
    echo "✅ All MCP servers built successfully"
    exit 0
else
    echo "❌ Some builds failed - see details above"
    exit 1
fi
