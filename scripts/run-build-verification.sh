#!/bin/bash

echo "=== MCP Server Build Verification ==="
echo ""

# copilot-memory
echo "1. Building copilot-memory..."
cd /Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/copilot-memory
npm run build
RESULT_1=$?
echo ""

# skills-copilot
echo "2. Building skills-copilot..."
cd /Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/skills-copilot
npm run build
RESULT_2=$?
echo ""

# websocket-bridge
echo "3. Building websocket-bridge..."
cd /Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/websocket-bridge
npm run build
RESULT_3=$?
echo ""

# Summary
echo "=== Build Summary ==="
echo "copilot-memory: $([ $RESULT_1 -eq 0 ] && echo '✅ PASS' || echo '❌ FAIL')"
echo "skills-copilot: $([ $RESULT_2 -eq 0 ] && echo '✅ PASS' || echo '❌ FAIL')"
echo "websocket-bridge: $([ $RESULT_3 -eq 0 ] && echo '✅ PASS' || echo '❌ FAIL')"

exit $(( $RESULT_1 + $RESULT_2 + $RESULT_3 ))
