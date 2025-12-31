/**
 * Session Guard tool tests
 */

import { sessionGuard, estimateTokens } from './session-guard.js';
import type { SessionGuardInput, SessionGuardOutput } from '../types.js';

// Mock DatabaseClient
class MockDatabase {
  getCurrentInitiative() {
    return {
      id: 'test-initiative',
      title: 'Test Initiative',
      description: 'Test description',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
  }

  getStats() {
    return {
      prds: 2,
      tasks: 10,
      workProducts: 5,
      activityLogs: 15
    };
  }
}

const db = new MockDatabase() as any;

/**
 * Test: Basic check with no violations
 */
function testCheckNoViolations() {
  const input: SessionGuardInput = {
    action: 'check',
    context: {
      filesRead: 2,
      codeWritten: false,
      agentUsed: 'agent-me',
      responseTokens: 300
    }
  };

  const result: SessionGuardOutput = sessionGuard(db, input);

  console.log('Test: No violations');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.assert(result.allowed === true, 'Should be allowed');
  console.assert(result.violations.length === 0, 'Should have no violations');
  console.log('✓ Passed\n');
}

/**
 * Test: Exceeded file read limit
 */
function testExceededFileLimit() {
  const input: SessionGuardInput = {
    action: 'check',
    context: {
      filesRead: 5,
      codeWritten: false,
      agentUsed: 'agent-me',
      responseTokens: 300
    }
  };

  const result: SessionGuardOutput = sessionGuard(db, input);

  console.log('Test: Exceeded file limit');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.assert(result.allowed === false, 'Should not be allowed');
  console.assert(result.violations.length > 0, 'Should have violations');
  console.assert(
    result.violations[0].includes('Exceeded 3-file limit'),
    'Should mention file limit'
  );
  console.log('✓ Passed\n');
}

/**
 * Test: Code written in main session
 */
function testCodeWritten() {
  const input: SessionGuardInput = {
    action: 'check',
    context: {
      filesRead: 2,
      codeWritten: true,
      responseTokens: 300
    }
  };

  const result: SessionGuardOutput = sessionGuard(db, input);

  console.log('Test: Code written in main session');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.assert(result.allowed === false, 'Should not be allowed');
  console.assert(
    result.violations.some(v => v.includes('@agent-me')),
    'Should mention @agent-me'
  );
  console.log('✓ Passed\n');
}

/**
 * Test: Response token warning
 */
function testResponseTokenWarning() {
  const input: SessionGuardInput = {
    action: 'check',
    context: {
      filesRead: 2,
      codeWritten: false,
      responseTokens: 600
    }
  };

  const result: SessionGuardOutput = sessionGuard(db, input);

  console.log('Test: Response token warning');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.assert(result.allowed === true, 'Should still be allowed (warning only)');
  console.assert(result.warnings.length > 0, 'Should have warnings');
  console.assert(
    result.warnings[0].includes('500 tokens'),
    'Should mention token limit'
  );
  console.log('✓ Passed\n');
}

/**
 * Test: Response token violation
 */
function testResponseTokenViolation() {
  const input: SessionGuardInput = {
    action: 'check',
    context: {
      filesRead: 2,
      codeWritten: false,
      responseTokens: 1200
    }
  };

  const result: SessionGuardOutput = sessionGuard(db, input);

  console.log('Test: Response token violation');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.assert(result.allowed === false, 'Should not be allowed');
  console.assert(
    result.violations.some(v => v.includes('1000 tokens')),
    'Should mention error threshold'
  );
  console.log('✓ Passed\n');
}

/**
 * Test: Generic agent violation
 */
function testGenericAgent() {
  const input: SessionGuardInput = {
    action: 'check',
    context: {
      filesRead: 2,
      agentUsed: 'Explore'
    }
  };

  const result: SessionGuardOutput = sessionGuard(db, input);

  console.log('Test: Generic agent violation');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.assert(result.allowed === false, 'Should not be allowed');
  console.assert(
    result.violations.some(v => v.includes('bypasses Task Copilot')),
    'Should mention Task Copilot bypass'
  );
  console.log('✓ Passed\n');
}

/**
 * Test: Framework agent (good)
 */
function testFrameworkAgent() {
  const input: SessionGuardInput = {
    action: 'check',
    context: {
      filesRead: 2,
      agentUsed: 'agent-ta'
    }
  };

  const result: SessionGuardOutput = sessionGuard(db, input);

  console.log('Test: Framework agent (good)');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.assert(result.allowed === true, 'Should be allowed');
  console.assert(
    result.suggestions.some(s => s.includes('Good')),
    'Should provide positive feedback'
  );
  console.log('✓ Passed\n');
}

/**
 * Test: Report action
 */
function testReport() {
  const input: SessionGuardInput = {
    action: 'report'
  };

  const result: SessionGuardOutput = sessionGuard(db, input);

  console.log('Test: Report action');
  console.log('Result:', JSON.stringify(result, null, 2));
  console.assert(result.suggestions.length > 0, 'Should have suggestions');
  console.assert(
    result.suggestions.some(s => s.includes('Test Initiative')),
    'Should include initiative info'
  );
  console.log('✓ Passed\n');
}

/**
 * Test: Token estimation
 */
function testTokenEstimation() {
  const text = 'This is a test string with approximately 40 characters.';
  const tokens = estimateTokens(text);

  console.log('Test: Token estimation');
  console.log(`Text length: ${text.length}, Estimated tokens: ${tokens}`);
  console.assert(tokens > 0, 'Should estimate tokens');
  console.assert(tokens < text.length, 'Tokens should be less than characters');
  console.log('✓ Passed\n');
}

/**
 * Run all tests
 */
function runTests() {
  console.log('=== Session Guard Tests ===\n');

  testCheckNoViolations();
  testExceededFileLimit();
  testCodeWritten();
  testResponseTokenWarning();
  testResponseTokenViolation();
  testGenericAgent();
  testFrameworkAgent();
  testReport();
  testTokenEstimation();

  console.log('=== All tests passed! ===');
}

// Run tests if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runTests();
}

export { runTests };
