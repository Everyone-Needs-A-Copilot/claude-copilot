/**
 * Simple test to verify token measurement tooling works
 */

import { countTokens, createMeasurementTracker } from './index.js';

console.log('Testing Token Measurement Tooling...\n');

// Test 1: Token counting
console.log('Test 1: Token Counting');
console.log('='.repeat(40));

const testTexts = [
  { text: 'Hello world', expected: 3 }, // 2 words × 1.3 ≈ 3
  { text: 'This is a test', expected: 5 }, // 4 words × 1.3 ≈ 5
  { text: '', expected: 0 },
  { text: '   ', expected: 0 },
];

let passed = 0;
let failed = 0;

testTexts.forEach(({ text, expected }) => {
  const result = countTokens(text);
  const pass = Math.abs(result - expected) <= 1; // Allow ±1 for rounding
  if (pass) {
    passed++;
    console.log(`✓ "${text}" → ${result} tokens`);
  } else {
    failed++;
    console.log(`✗ "${text}" → ${result} tokens (expected ~${expected})`);
  }
});

console.log(`\nPassed: ${passed}/${testTexts.length}\n`);

// Test 2: Measurement Tracker
console.log('Test 2: Measurement Tracker');
console.log('='.repeat(40));

const tracker = createMeasurementTracker('TEST-1', 'Test Scenario');

tracker.measure('main_input', 'User request here');
tracker.measure('agent_output', 'This is a much longer agent output with many words and sentences. '.repeat(50));
tracker.measure('main_return', 'Brief summary');

const metrics = tracker.calculateMetrics();

console.log('Measurements recorded:');
tracker.getAllMeasurements().forEach(m => {
  console.log(`  ${m.point}: ${m.tokens} tokens`);
});

console.log('\nMetrics calculated:');
console.log(`  Context Reduction: ${metrics.percentages.contextReductionPct.toFixed(1)}%`);
console.log(`  Storage Overhead: ${metrics.percentages.storageOverheadPct.toFixed(1)}%`);

if (metrics.percentages.contextReductionPct > 90) {
  console.log('✓ Context reduction > 90%');
  passed++;
} else {
  console.log('✗ Context reduction too low');
  failed++;
}

// Test 3: JSON export
console.log('\nTest 3: JSON Export');
console.log('='.repeat(40));

const json = tracker.toJSON();
if (json.scenarioId === 'TEST-1' && json.measurements.length === 3) {
  console.log('✓ JSON export contains correct data');
  passed++;
} else {
  console.log('✗ JSON export invalid');
  failed++;
}

// Test 4: Summary generation
console.log('\nTest 4: Summary Generation');
console.log('='.repeat(40));

const summary = tracker.generateSummary();
if (summary.includes('TEST-1') && summary.includes('Token Counts')) {
  console.log('✓ Summary generated successfully');
  console.log('\nGenerated Summary:');
  console.log(summary);
  passed++;
} else {
  console.log('✗ Summary generation failed');
  failed++;
}

// Final results
console.log('\n' + '='.repeat(40));
console.log(`TOTAL: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));

if (failed > 0) {
  process.exit(1);
}
