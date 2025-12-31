#!/usr/bin/env node

/**
 * Simple CLI for token measurement and benchmarking
 * Usage: node dist/benchmark/cli.js <command> [options]
 */

import { readFileSync, writeFileSync } from 'fs';
import { createMeasurementTracker, MeasurementPoint } from './measurement-tracker.js';
import { countTokens } from './token-counter.js';

function printUsage() {
  console.log(`
Token Measurement CLI

Usage:
  node dist/benchmark/cli.js count <file>
    Count tokens in a file

  node dist/benchmark/cli.js measure <scenario-id> <scenario-name>
    Start an interactive measurement session

  node dist/benchmark/cli.js analyze <measurements.json>
    Analyze measurements from JSON file

Examples:
  node dist/benchmark/cli.js count myfile.txt
  node dist/benchmark/cli.js measure BENCH-1 "Feature Implementation"
  node dist/benchmark/cli.js analyze results.json
`);
}

function countCommand(filePath: string) {
  try {
    const content = readFileSync(filePath, 'utf-8');
    const tokens = countTokens(content);
    const lines = content.split('\n').length;
    const chars = content.length;

    console.log(`File: ${filePath}`);
    console.log(`Tokens: ${tokens.toLocaleString()}`);
    console.log(`Characters: ${chars.toLocaleString()}`);
    console.log(`Lines: ${lines.toLocaleString()}`);
  } catch (error) {
    console.error(`Error reading file: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}

function measureCommand(scenarioId: string, scenarioName: string) {
  console.log(`Starting measurement session for: ${scenarioName} (${scenarioId})`);
  console.log('');
  console.log('Measurement Points:');
  console.log('  1. main_input     - User request to main session');
  console.log('  2. main_context   - Total context in main session');
  console.log('  3. agent_output   - Full agent output');
  console.log('  4. main_return    - Summary returned to main');
  console.log('  5. storage        - Content stored in Task Copilot');
  console.log('  6. retrieval      - Content retrieved later');
  console.log('');
  console.log('Usage: Provide file paths for each measurement point');
  console.log('');

  const tracker = createMeasurementTracker(scenarioId, scenarioName);

  const points: MeasurementPoint[] = [
    'main_input',
    'main_context',
    'agent_output',
    'main_return',
    'storage',
    'retrieval',
  ];

  // Read from stdin (for interactive mode)
  console.log('Enter file paths (or press Enter to skip):');
  console.log('');

  let index = 0;

  process.stdin.setEncoding('utf-8');
  process.stdin.on('data', (data) => {
    const line = data.toString().trim();

    if (index >= points.length) {
      // Done collecting measurements
      const result = tracker.toJSON();
      const outputFile = `measurement-${scenarioId}-${Date.now()}.json`;
      writeFileSync(outputFile, JSON.stringify(result, null, 2));

      console.log('');
      console.log('='.repeat(60));
      console.log(tracker.generateSummary());
      console.log('='.repeat(60));
      console.log('');
      console.log(`Results saved to: ${outputFile}`);

      process.exit(0);
    }

    const point = points[index];

    if (line.length > 0) {
      try {
        const content = readFileSync(line, 'utf-8');
        const measurement = tracker.measure(point, content);
        console.log(`✓ ${point}: ${measurement.tokens.toLocaleString()} tokens`);
      } catch (error) {
        console.log(`✗ ${point}: Error reading file - ${error instanceof Error ? error.message : String(error)}`);
      }
    } else {
      console.log(`- ${point}: Skipped`);
    }

    index++;

    if (index < points.length) {
      process.stdout.write(`${points[index]}: `);
    }
  });

  // Start prompting
  process.stdout.write(`${points[0]}: `);
}

function analyzeCommand(filePath: string) {
  try {
    const content = readFileSync(filePath, 'utf-8');
    const data = JSON.parse(content);

    console.log('='.repeat(60));
    console.log(`Scenario: ${data.scenarioName} (${data.scenarioId})`);
    console.log('='.repeat(60));
    console.log('');

    const metrics = data.metrics;

    console.log('Token Counts:');
    console.log(`  Main Input:    ${metrics.totalTokens.mainInput.toLocaleString()}`);
    console.log(`  Main Context:  ${metrics.totalTokens.mainContext.toLocaleString()}`);
    console.log(`  Agent Output:  ${metrics.totalTokens.agentOutput.toLocaleString()}`);
    console.log(`  Main Return:   ${metrics.totalTokens.mainReturn.toLocaleString()}`);
    console.log(`  Storage:       ${metrics.totalTokens.storage.toLocaleString()}`);
    console.log(`  Retrieval:     ${metrics.totalTokens.retrieval.toLocaleString()}`);
    console.log('');
    console.log('Efficiency Metrics:');
    console.log(`  Context Reduction:      ${metrics.percentages.contextReductionPct.toFixed(1)}%`);
    console.log(`  Storage Overhead:       ${metrics.percentages.storageOverheadPct.toFixed(1)}%`);
    console.log(`  Compression Ratio:      ${metrics.compressionRatio.toFixed(2)}x`);
    console.log(`  Main Session Load:      ${metrics.mainSessionLoad.toFixed(2)}x`);
    console.log(`  Return vs Output:       ${metrics.percentages.mainReturnVsAgentOutputPct.toFixed(1)}%`);
    console.log('');

    console.log('Measurements:');
    data.measurements.forEach((m: any) => {
      console.log(`  ${m.point}: ${m.tokens.toLocaleString()} tokens (${m.timestamp})`);
    });

    console.log('');
    console.log(`Duration: ${data.startTime} → ${data.endTime}`);

  } catch (error) {
    console.error(`Error analyzing file: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}

// Parse CLI arguments
const args = process.argv.slice(2);

if (args.length === 0) {
  printUsage();
  process.exit(0);
}

const command = args[0];

switch (command) {
  case 'count':
    if (args.length < 2) {
      console.error('Error: Missing file path');
      printUsage();
      process.exit(1);
    }
    countCommand(args[1]);
    break;

  case 'measure':
    if (args.length < 3) {
      console.error('Error: Missing scenario-id or scenario-name');
      printUsage();
      process.exit(1);
    }
    measureCommand(args[1], args[2]);
    break;

  case 'analyze':
    if (args.length < 2) {
      console.error('Error: Missing JSON file path');
      printUsage();
      process.exit(1);
    }
    analyzeCommand(args[1]);
    break;

  case 'help':
  case '--help':
  case '-h':
    printUsage();
    process.exit(0);
    break;

  default:
    console.error(`Unknown command: ${command}`);
    printUsage();
    process.exit(1);
}
