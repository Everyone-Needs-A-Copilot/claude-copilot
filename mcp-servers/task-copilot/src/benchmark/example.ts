/**
 * Example usage of the token measurement tooling
 */

import { createMeasurementTracker, countTokens } from './index.js';

// Example: Measuring a simple workflow
export function exampleMeasurement() {
  // Create a tracker for a benchmark scenario
  const tracker = createMeasurementTracker(
    'BENCH-1',
    'Feature Implementation',
    { framework: 'claude-copilot', version: '2.0' }
  );

  // Simulate measurements at different points
  const userRequest = 'Implement user authentication with JWT tokens';
  tracker.measure('main_input', userRequest, { source: 'user' });

  const mainContext = `
    ${userRequest}

    Current codebase context:
    - Express.js API
    - PostgreSQL database
    - Existing user model
    - Session management in place
  `.trim();
  tracker.measure('main_context', mainContext);

  const agentOutput = `
    # Authentication Implementation

    ## Analysis
    [3000 words of detailed analysis]

    ## Implementation
    [5000 words of code and explanations]

    ## Testing Strategy
    [2000 words of test plans]

    ## Security Considerations
    [1000 words of security review]
  `.trim();
  tracker.measure('agent_output', agentOutput, { agent: '@agent-me' });

  const mainReturn = `
    Implementation complete for TASK-123.
    Work Product: WP-456 (implementation, 11,000 words)
    Files Modified: auth.ts, user.model.ts, auth.test.ts
    Summary: JWT authentication added with refresh tokens, session management updated.
  `.trim();
  tracker.measure('main_return', mainReturn);

  const storage = JSON.stringify({
    id: 'WP-456',
    taskId: 'TASK-123',
    type: 'implementation',
    title: 'User Authentication Implementation',
    content: agentOutput,
    metadata: {
      filesModified: ['auth.ts', 'user.model.ts', 'auth.test.ts'],
      complexity: 'medium',
    },
  });
  tracker.measure('storage', storage);

  const retrieval = `
    Work Product WP-456:
    ${agentOutput.substring(0, 500)}...
    [truncated for retrieval]
  `.trim();
  tracker.measure('retrieval', retrieval);

  // Generate summary
  console.log(tracker.generateSummary());

  // Get raw metrics
  const metrics = tracker.calculateMetrics();
  console.log('\nDetailed Metrics:');
  console.log(JSON.stringify(metrics, null, 2));

  // Export to JSON
  const results = tracker.toJSON();
  console.log('\nFull Results:');
  console.log(JSON.stringify(results, null, 2));

  return tracker;
}

// Example: Simple token counting
export function exampleTokenCounting() {
  const texts = [
    'Hello world',
    'This is a longer piece of text with more words to count.',
    `
      Multi-line text
      with several lines
      and various content
    `,
  ];

  console.log('Token Counting Examples:');
  texts.forEach((text, i) => {
    const tokens = countTokens(text);
    console.log(`Text ${i + 1}: ${tokens} tokens`);
    console.log(`  "${text.substring(0, 50)}${text.length > 50 ? '...' : ''}"`);
  });
}

// Run examples if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  console.log('='.repeat(60));
  console.log('Token Measurement Example');
  console.log('='.repeat(60));
  console.log('');

  exampleTokenCounting();
  console.log('');
  console.log('='.repeat(60));
  console.log('');

  exampleMeasurement();
}
