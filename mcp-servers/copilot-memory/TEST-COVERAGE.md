# Two-Tier Resume System Test Coverage

## Overview
This document describes the integration tests added for the two-tier resume system in copilot-memory.

## Feature Under Test
The `initiative_get()` function now supports two modes:
- **lean** (default): Returns ~150 tokens - essential fields only
- **full**: Returns ~370 tokens - includes all fields including decisions, lessons, keyFiles

## Test Suite Location
`mcp-servers/copilot-memory/src/tests/integration.test.ts`

## Test Cases Added

### 1. Default Behavior (Backward Compatibility)
**Test**: `should return lean mode by default (backward compatible)`
- Verifies that calling `initiativeGet(db)` without parameters returns lean mode
- Essential fields present: name, goal, status, currentFocus, nextAction, taskCopilotLinked, activePrdIds
- Heavy fields empty: decisions, lessons, keyFiles, completed, inProgress, blocked, resumeInstructions

### 2. Explicit Lean Mode
**Test**: `should return lean mode when explicitly requested`
- Verifies that `initiativeGet(db, { mode: 'lean' })` behaves identically to default
- Ensures explicit mode selection works correctly

### 3. Full Mode
**Test**: `should return full mode when explicitly requested`
- Verifies that `initiativeGet(db, { mode: 'full' })` returns all fields
- Heavy fields contain actual data: decisions, lessons, keyFiles
- All essential fields still present

### 4. Essential Fields Validation
**Test**: `should maintain all essential fields in lean mode`
- Validates all required fields are present in lean mode response:
  - id, projectId, name, goal, status
  - createdAt, updatedAt
  - taskCopilotLinked (boolean), activePrdIds (array)
  - currentFocus (string), nextAction (string)

### 5. Minimal Initiative Handling
**Test**: `should handle initiative with no currentFocus or nextAction in lean mode`
- Tests lean mode with an initiative that has no optional slim fields
- Verifies undefined values are handled correctly

### 6. Invalid Mode Handling
**Test**: `should handle invalid mode gracefully`
- Tests behavior when an invalid mode is provided
- Verifies it defaults to lean mode behavior (fail-safe)

## Test Data Setup
Each test uses a rich initiative with:
- Decisions: 2 entries
- Lessons: 3 entries
- Key files: 2 entries
- Current focus and next action
- Task Copilot linked status
- Active PRD IDs

## Running the Tests

### Quick Run
```bash
cd mcp-servers/copilot-memory
npm test
```

### Build and Test
```bash
./run-tests.sh
```

### Watch Mode
```bash
npm run test:watch
```

## Expected Results
All tests should pass, confirming:
- ✓ Backward compatibility (default = lean mode)
- ✓ Lean mode excludes heavy fields (decisions, lessons, keyFiles)
- ✓ Full mode includes all fields
- ✓ Essential fields always present in both modes
- ✓ Graceful handling of missing optional fields
- ✓ Fail-safe behavior for invalid mode

## Token Efficiency Verification
The two-tier system reduces token usage:
- **Lean mode**: ~150 tokens (60% reduction)
- **Full mode**: ~370 tokens (baseline)

This allows for faster resume operations while preserving the ability to access full context when needed.
