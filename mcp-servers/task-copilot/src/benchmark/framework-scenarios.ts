/**
 * Framework Measurements for BENCH-4
 *
 * Simulates token usage WITH Claude Copilot framework
 * - Agent delegation (work happens in subagent context)
 * - Task Copilot storage (only summaries return to main)
 * - Memory Copilot provides slim initiative state
 * - Progress summaries instead of full details
 */

import { createMeasurementTracker } from './index.js';

/**
 * SCENARIO 1: Feature Implementation (WITH Framework)
 *
 * WITH framework:
 * - User delegates to @agent-me
 * - Agent reads code, plans, implements in its own context
 * - Agent stores work product in Task Copilot
 * - Only ~300 token summary returns to main session
 */
export function frameworkScenario1_FeatureImplementation() {
  const tracker = createMeasurementTracker(
    'FRAMEWORK-1',
    'Feature Implementation (With Framework)',
    { variant: 'framework', framework: 'claude-copilot' }
  );

  // User's initial request (same as baseline)
  const mainInput = 'Add user authentication with JWT tokens to the Express.js API';
  tracker.measure('main_input', mainInput);

  // WITH framework: Main session only contains delegation and routing
  const mainContext = `
    ${mainInput}

    # User invokes /protocol
    # Selects FEATURE initiative type
    # Protocol routes to @agent-me

    # Main session context includes:
    # - Initiative context from Memory Copilot (~150 tokens)
    # - Current task context (~100 tokens)
  `.trim();
  tracker.measure('main_context', mainContext);

  // Agent works in its own context (not counted in main session)
  // This would be ~11,908 tokens in baseline, but it's in agent context
  const agentOutput = `
    # Agent @agent-me performs all work in its context:
    # - Reads all relevant files
    # - Plans implementation
    # - Writes all code
    # - Writes tests
    # - Writes documentation
    #
    # This is approximately the same content as baseline scenario 1,
    # but it happens in the AGENT'S context, not the main session.
    #
    # The agent then stores this in Task Copilot instead of returning it.

    ## Implementation Plan
    [~60 lines of planning]

    ## Code Files Created
    - src/utils/jwt.ts [~50 lines]
    - src/services/auth.service.ts [~90 lines]
    - src/middleware/auth.ts [~60 lines]
    - src/routes/auth.routes.ts [~80 lines]

    ## Code Files Modified
    - src/routes/api.ts [~20 lines changes]

    ## Tests Created
    - tests/utils/jwt.test.ts [~60 lines]
    - tests/services/auth.service.test.ts [~90 lines]
    - tests/integration/auth.test.ts [~100 lines]

    ## Documentation
    - Updated README with auth endpoints
    - Added API documentation
    - Security considerations documented

    Total agent work: ~1,250 lines of content
    (Similar to baseline, but in agent context, not main session)
  `.trim();
  // Note: We measure this to show the work being done, but it doesn't bloat main context
  tracker.measure('agent_output', agentOutput);

  // Agent stores detailed work in Task Copilot
  const storage = `
    # Stored via work_product_store
    {
      "taskId": "TASK-xxx",
      "type": "implementation",
      "title": "JWT Authentication Implementation",
      "content": {
        "files_created": [
          "src/utils/jwt.ts",
          "src/services/auth.service.ts",
          "src/middleware/auth.ts",
          "src/routes/auth.routes.ts"
        ],
        "files_modified": [
          "src/routes/api.ts"
        ],
        "tests_created": [
          "tests/utils/jwt.test.ts",
          "tests/services/auth.service.test.ts",
          "tests/integration/auth.test.ts"
        ],
        "implementation_notes": "[Full implementation details]",
        "test_coverage": "Unit and integration tests for all auth flows",
        "security_notes": "Uses bcrypt for password hashing, JWT with RS256",
        "documentation": "[Full documentation]"
      }
    }

    # Storage includes some metadata overhead but compresses the narrative
    # Total stored: ~2,500 tokens (vs ~11,908 in baseline)
  `.trim();
  tracker.measure('storage', storage);

  // Agent returns compact summary to main session
  const mainReturn = `
    Task Complete: TASK-xxx
    Work Product: WP-yyy (implementation, 2,458 tokens stored)

    Summary: Implemented JWT-based authentication for Express.js API. Created auth
    service, JWT utilities, and auth middleware. All existing routes now protected.
    Added comprehensive tests (15 unit tests, 8 integration tests).

    Files Created:
    - src/utils/jwt.ts (JWT generation/verification)
    - src/services/auth.service.ts (Login/register logic)
    - src/middleware/auth.ts (Route protection)
    - src/routes/auth.routes.ts (Auth endpoints)

    Files Modified:
    - src/routes/api.ts (Protected routes)

    Tests: All passing (23 tests total)
    Coverage: 95% of new auth code

    Security:
    - Passwords hashed with bcrypt (cost 12)
    - JWTs signed with RS256
    - Tokens expire after 1h
    - Input validation on all endpoints

    Next Steps: Consider adding refresh token mechanism and rate limiting.
  `.trim();
  tracker.measure('main_return', mainReturn);

  // No retrieval needed for this scenario
  tracker.measure('retrieval', '');

  return tracker;
}

/**
 * SCENARIO 2: Bug Investigation (WITH Framework)
 *
 * WITH framework:
 * - User reports bug, protocol routes to @agent-qa
 * - Agent investigates in its own context
 * - Stores investigation report in Task Copilot
 * - Returns ~200 token summary with fix
 */
export function frameworkScenario2_BugInvestigation() {
  const tracker = createMeasurementTracker(
    'FRAMEWORK-2',
    'Bug Investigation (With Framework)',
    { variant: 'framework', framework: 'claude-copilot' }
  );

  const mainInput = 'Users reporting 500 errors on checkout - need to investigate';
  tracker.measure('main_input', mainInput);

  const mainContext = `
    ${mainInput}

    # User invokes /protocol with DEFECT type
    # Protocol routes to @agent-qa
    # Initiative context loaded from Memory Copilot (~100 tokens)
  `.trim();
  tracker.measure('main_context', mainContext);

  // Agent investigates in its own context
  const agentOutput = `
    # Agent @agent-qa performs investigation in its context:
    # - Reads error logs
    # - Reads related code files
    # - Analyzes root cause
    # - Proposes fix
    #
    # This is ~4,953 tokens of work (same as baseline)
    # but happens in agent context, not main session

    ## Error Analysis
    [~50 log entries analyzed]
    [~890 lines of code reviewed]

    ## Root Cause
    Cart.items is undefined when cart is deleted/expired before checkout.
    Missing null checks in CheckoutService.processPayment().

    ## Proposed Fix
    [~60 lines of fix code]

    ## Verification Plan
    [Test cases to verify fix]
  `.trim();
  tracker.measure('agent_output', agentOutput);

  // Agent stores investigation in Task Copilot
  const storage = `
    # Stored via work_product_store
    {
      "taskId": "TASK-xxx",
      "type": "other",
      "title": "Checkout 500 Error Investigation",
      "content": {
        "error_pattern": "Cannot read property 'amount' of undefined",
        "frequency": "45 occurrences in last 24h",
        "affected_code": "src/services/checkout.service.ts:45",
        "root_cause": "Missing null checks for cart.items",
        "fix_implemented": true,
        "fix_location": "src/services/checkout.service.ts",
        "verification": "Added null checks and validation",
        "impact": "Resolves ~5% of failed checkouts"
      }
    }

    # Stored: ~800 tokens
  `.trim();
  tracker.measure('storage', storage);

  // Agent returns summary to main
  const mainReturn = `
    Task Complete: TASK-xxx
    Work Product: WP-yyy (investigation report, 783 tokens stored)

    Summary: Identified and fixed root cause of checkout 500 errors. Missing null
    checks for cart.items causing "Cannot read property 'amount'" errors.

    Root Cause: Cart deleted/expired between add-to-cart and checkout, causing
    processPayment to fail on undefined cart.items.

    Fix Applied:
    - Added null/undefined checks for cart and cart.items
    - Added validation before payment processing
    - Improved error messages

    Impact: Resolves ~5% of checkout failures (45 errors in last 24h)

    Files Modified: src/services/checkout.service.ts

    Verification: Manual testing confirms fix, no regression.
  `.trim();
  tracker.measure('main_return', mainReturn);

  tracker.measure('retrieval', '');

  return tracker;
}

/**
 * SCENARIO 3: Code Refactoring (WITH Framework)
 *
 * WITH framework:
 * - User requests refactoring, routes to @agent-me
 * - Agent performs refactoring in its context
 * - Stores refactoring details in Task Copilot
 * - Returns ~250 token summary
 */
export function frameworkScenario3_CodeRefactoring() {
  const tracker = createMeasurementTracker(
    'FRAMEWORK-3',
    'Code Refactoring (With Framework)',
    { variant: 'framework', framework: 'claude-copilot' }
  );

  const mainInput = 'Refactor user service to use dependency injection pattern';
  tracker.measure('main_input', mainInput);

  const mainContext = `
    ${mainInput}

    # User invokes /protocol with FEATURE type (refactoring)
    # Protocol routes to @agent-me
    # Initiative context from Memory Copilot (~100 tokens)
  `.trim();
  tracker.measure('main_context', mainContext);

  const agentOutput = `
    # Agent @agent-me performs refactoring in its context:
    # - Reads existing code
    # - Plans refactoring approach
    # - Implements dependency injection
    # - Updates tests
    #
    # This is ~6,182 tokens of work (same as baseline)
    # but happens in agent context

    ## Refactoring Plan
    [~50 lines of planning]

    ## Interfaces Created
    [~60 lines of interface definitions]

    ## UserService Refactored
    [~180 lines of refactored service]

    ## DI Container
    [~120 lines of container setup]

    ## Tests Updated
    [~180 lines of updated tests]
  `.trim();
  tracker.measure('agent_output', agentOutput);

  const storage = `
    # Stored via work_product_store
    {
      "taskId": "TASK-xxx",
      "type": "implementation",
      "title": "UserService Dependency Injection Refactoring",
      "content": {
        "approach": "Introduced interfaces and constructor injection",
        "interfaces_created": [
          "IDatabase",
          "IEmailService",
          "ILogger"
        ],
        "files_refactored": [
          "src/services/user.service.ts",
          "src/controllers/user.controller.ts"
        ],
        "files_created": [
          "src/interfaces/database.interface.ts",
          "src/interfaces/email.interface.ts",
          "src/interfaces/logger.interface.ts",
          "src/container.ts"
        ],
        "tests_updated": true,
        "backwards_compatible": false,
        "migration_notes": "All consumers must use DI container"
      }
    }

    # Stored: ~1,200 tokens
  `.trim();
  tracker.measure('storage', storage);

  const mainReturn = `
    Task Complete: TASK-xxx
    Work Product: WP-yyy (implementation, 1,187 tokens stored)

    Summary: Refactored UserService to use dependency injection pattern. Created
    interfaces for all dependencies and DI container for service resolution.

    Changes:
    - Created IDatabase, IEmailService, ILogger interfaces
    - Updated UserService to use constructor injection
    - Created DI container (src/container.ts)
    - Updated UserController to use container
    - Updated all tests to use mocks

    Benefits:
    - Much easier to test (can inject mocks)
    - Reduced coupling to concrete implementations
    - Better separation of concerns

    Breaking: Consumers must now use DI container instead of direct instantiation.

    Tests: All passing (12 tests updated with mocks)
  `.trim();
  tracker.measure('main_return', mainReturn);

  tracker.measure('retrieval', '');

  return tracker;
}

/**
 * SCENARIO 4: Session Resume (WITH Framework)
 *
 * WITH framework:
 * - User runs /continue
 * - Memory Copilot provides initiative state
 * - Task Copilot provides progress summary
 * - Total: ~400 tokens to resume (vs 2,808 in baseline)
 */
export function frameworkScenario4_SessionResume() {
  const tracker = createMeasurementTracker(
    'FRAMEWORK-4',
    'Session Resume (With Framework)',
    { variant: 'framework', framework: 'claude-copilot' }
  );

  const mainInput = 'Continue working on the user dashboard feature from yesterday';
  tracker.measure('main_input', mainInput);

  // WITH framework: Memory Copilot provides compact initiative state
  const mainContext = `
    ${mainInput}

    # User runs /continue
    # Memory Copilot loads initiative via initiative_get

    Initiative: User Dashboard Feature
    Status: In Progress
    Phase: Implementation

    Summary: Building user dashboard with profile, activity feed, and stats.
    Completed dashboard layout and profile section. Next: QuickStats component.

    Key Files:
    - src/pages/Dashboard.tsx
    - src/components/UserProfile.tsx
    - src/components/ActivityFeed.tsx
    - src/hooks/useDashboardData.ts

    Decisions:
    - Using React Query for data fetching
    - Tailwind CSS for styling
    - Component structure: Dashboard → UserProfile, ActivityFeed, QuickStats

    Blockers:
    - Avatar CORS issue (STILL OPEN)

    Next Steps:
    1. Create QuickStats component
    2. Create SettingsShortcut component
    3. Fix avatar CORS issue

    # Total context from Memory Copilot: ~250 tokens
    # No need to re-read all files or recreate full history
  `.trim();
  tracker.measure('main_context', mainContext);

  // No agent invoked for resume - just loading context
  tracker.measure('agent_output', '');

  // No storage for resume operation
  tracker.measure('storage', '');

  // Retrieval from Memory Copilot
  const retrieval = `
    # Retrieved via initiative_get
    {
      "id": "INIT-xxx",
      "title": "User Dashboard Feature",
      "status": "in_progress",
      "inProgress": [
        "Implementing dashboard components",
        "Need QuickStats and SettingsShortcut components"
      ],
      "completed": [
        "Dashboard layout",
        "UserProfile component",
        "ActivityFeed component",
        "Data fetching with React Query"
      ],
      "decisions": [
        "Use React Query over SWR",
        "Use Tailwind CSS",
        "Component-based architecture"
      ],
      "keyFiles": [
        "src/pages/Dashboard.tsx",
        "src/components/UserProfile.tsx",
        "src/components/ActivityFeed.tsx",
        "src/hooks/useDashboardData.ts"
      ],
      "lessons": [
        "TypeScript types needed for stats object",
        "React Query cache keys must be consistent"
      ],
      "blockers": [
        "Avatar CORS issue with image CDN"
      ]
    }

    # Retrieved: ~350 tokens (vs 2,808 in baseline)
  `.trim();
  tracker.measure('retrieval', retrieval);

  // Nothing returned to main for resume - context is already in main
  const mainReturn = `
    # Context loaded from Memory Copilot
    # User can immediately continue work
    # No summary needed - this IS the summary

    Ready to continue. Current task: Create QuickStats component.
  `.trim();
  tracker.measure('main_return', mainReturn);

  return tracker;
}

/**
 * SCENARIO 5: Multi-Agent Collaboration (WITH Framework)
 *
 * WITH framework:
 * - User requests design + implementation
 * - @agent-ta handles architecture (stores in Task Copilot)
 * - @agent-me handles implementation (stores in Task Copilot)
 * - @agent-qa handles testing (stores in Task Copilot)
 * - Each returns ~300 token summary
 * - Total main context: ~1,200 tokens (vs 6,319 in baseline)
 */
export function frameworkScenario5_MultiAgentCollaboration() {
  const tracker = createMeasurementTracker(
    'FRAMEWORK-5',
    'Multi-Agent Collaboration (With Framework)',
    { variant: 'framework', framework: 'claude-copilot' }
  );

  const mainInput = 'Design and implement a real-time notification system';
  tracker.measure('main_input', mainInput);

  const mainContext = `
    ${mainInput}

    # User invokes /protocol with ARCHITECTURE type
    # Protocol routes to @agent-ta for design
    # Then routes to @agent-me for implementation
    # Then routes to @agent-qa for testing

    ## Phase 1: Architecture (@agent-ta)
    [~300 token summary returned]

    ## Phase 2: Implementation (@agent-me)
    [~300 token summary returned]

    ## Phase 3: Testing (@agent-qa)
    [~300 token summary returned]

    # Total main context: Summaries only, full work in Task Copilot
    # ~1,200 tokens total (vs 6,319 in baseline)
  `.trim();
  tracker.measure('main_context', mainContext);

  // Combined agent work across all three agents
  const agentOutput = `
    # AGENT 1: @agent-ta (Architecture)
    # Works in its own context: ~2,000 tokens
    ## Architecture Design
    - Requirements analysis
    - ADRs (WebSocket vs SSE, Redis vs RabbitMQ, etc.)
    - High-level architecture diagram
    - Component design
    - Data models
    - API design
    - Scalability considerations
    - Security design
    [Full architecture document: ~500 lines]

    # AGENT 2: @agent-me (Implementation)
    # Works in its own context: ~3,500 tokens
    ## Implementation
    - Socket server implementation (~280 lines)
    - Notification service (~320 lines)
    - Client library (~200 lines)
    - Database migrations
    - Redis setup
    [Full implementation: ~800 lines]

    # AGENT 3: @agent-qa (Testing)
    # Works in its own context: ~900 tokens
    ## Testing Strategy
    - Unit test plan
    - Integration test plan
    - Load test plan
    - Example tests
    [Full test plan and tests: ~100 lines]

    # Total agent work: ~6,400 tokens
    # But each happens in separate agent context
    # Not accumulated in main session
  `.trim();
  tracker.measure('agent_output', agentOutput);

  // All agents store their work in Task Copilot
  const storage = `
    # STORED BY @agent-ta
    {
      "taskId": "TASK-architecture-xxx",
      "type": "architecture",
      "title": "Real-Time Notification System Architecture",
      "content": { /* Full architecture design */ }
    }
    # Stored: ~2,200 tokens

    # STORED BY @agent-me
    {
      "taskId": "TASK-implementation-xxx",
      "type": "implementation",
      "title": "Real-Time Notification System Implementation",
      "content": { /* Full implementation code */ }
    }
    # Stored: ~3,800 tokens

    # STORED BY @agent-qa
    {
      "taskId": "TASK-testing-xxx",
      "type": "test_plan",
      "title": "Real-Time Notification System Test Plan",
      "content": { /* Full test plan and tests */ }
    }
    # Stored: ~1,000 tokens

    # Total stored: ~7,000 tokens
  `.trim();
  tracker.measure('storage', storage);

  // Each agent returns summary to main
  const mainReturn = `
    # SUMMARY FROM @agent-ta
    Task Complete: TASK-architecture-xxx
    Work Product: WP-arch-yyy (architecture, 2,187 tokens stored)

    Summary: Designed real-time notification system using WebSocket (Socket.io)
    with Redis Pub/Sub for message delivery and PostgreSQL for persistence.

    Key Decisions:
    - Socket.io for WebSocket (better fallbacks than raw WebSocket)
    - Redis Pub/Sub for real-time + Streams for offline
    - PostgreSQL for persistence
    - Horizontal scaling with sticky sessions

    Components: Socket server, Notification service, Client library
    Scalability: Supports 100k concurrent users via horizontal scaling

    ----

    # SUMMARY FROM @agent-me
    Task Complete: TASK-implementation-xxx
    Work Product: WP-impl-yyy (implementation, 3,782 tokens stored)

    Summary: Implemented all components for real-time notification system.

    Files Created:
    - src/socket/server.ts (Socket.io server with Redis adapter)
    - src/services/notification.service.ts (Business logic)
    - src/client/notification-client.ts (Client library)
    - migrations/notifications.sql (Database schema)

    Features:
    - JWT authentication for WebSocket connections
    - Redis Pub/Sub for real-time delivery
    - PostgreSQL persistence
    - Offline queue in client
    - Auto-reconnect logic

    ----

    # SUMMARY FROM @agent-qa
    Task Complete: TASK-testing-xxx
    Work Product: WP-test-yyy (test_plan, 987 tokens stored)

    Summary: Created comprehensive test plan covering unit, integration, and load
    testing for notification system.

    Test Coverage:
    - Unit tests: Notification service, Socket handling
    - Integration tests: End-to-end delivery flow, Offline handling
    - Load tests: 10k concurrent connections, 1000 msg/sec throughput

    Status: Test plan ready, example tests provided
    Next: Execute full test suite

    ----

    # Total returned to main: ~900 tokens (summaries only)
    # vs 6,319 tokens in baseline where everything was inline
  `.trim();
  tracker.measure('main_return', mainReturn);

  // No retrieval for this scenario
  tracker.measure('retrieval', '');

  return tracker;
}

/**
 * Run all framework-enabled scenarios and generate summary report
 */
export function runAllFrameworkScenarios() {
  console.log('='.repeat(70));
  console.log('FRAMEWORK MEASUREMENTS (With Claude Copilot)');
  console.log('='.repeat(70));
  console.log('');
  console.log('Measuring token usage when:');
  console.log('- Agents delegated to (work in subagent context)');
  console.log('- Task Copilot stores work products');
  console.log('- Memory Copilot provides initiative state');
  console.log('- Only summaries return to main session');
  console.log('');
  console.log('='.repeat(70));
  console.log('');

  const scenarios = [
    { name: 'SCENARIO 1: Feature Implementation', fn: frameworkScenario1_FeatureImplementation },
    { name: 'SCENARIO 2: Bug Investigation', fn: frameworkScenario2_BugInvestigation },
    { name: 'SCENARIO 3: Code Refactoring', fn: frameworkScenario3_CodeRefactoring },
    { name: 'SCENARIO 4: Session Resume', fn: frameworkScenario4_SessionResume },
    { name: 'SCENARIO 5: Multi-Agent Collaboration', fn: frameworkScenario5_MultiAgentCollaboration },
  ];

  const results = [];

  for (const scenario of scenarios) {
    console.log('-'.repeat(70));
    console.log(scenario.name);
    console.log('-'.repeat(70));
    console.log('');

    const tracker = scenario.fn();
    const summary = tracker.generateSummary();
    console.log(summary);
    console.log('');

    results.push({
      scenario: scenario.name,
      tracker: tracker,
      summary: summary,
      json: tracker.toJSON()
    });
  }

  console.log('='.repeat(70));
  console.log('SUMMARY: All Framework Scenarios');
  console.log('='.repeat(70));
  console.log('');

  console.log('| Scenario | Main Context Tokens | Context Reduction |');
  console.log('|----------|---------------------|-------------------|');

  for (const result of results) {
    const tokens = result.json.metrics.totalTokens.mainContext;
    const reduction = result.json.metrics.percentages.contextReductionPct;
    const scenarioName = result.scenario.replace('SCENARIO ', '').substring(0, 30);
    console.log(`| ${scenarioName.padEnd(30)} | ${tokens.toLocaleString().padStart(19)} | ${reduction.toFixed(1)}% |`);
  }

  console.log('');
  console.log('Key Observations:');
  console.log('1. WITH framework, work happens in agent context (not main)');
  console.log('2. Task Copilot stores detailed work products');
  console.log('3. Only compact summaries return to main session');
  console.log('4. Memory Copilot eliminates session resume overhead');
  console.log('5. Multi-agent collaboration keeps each phase separate');
  console.log('');

  return results;
}

// Run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runAllFrameworkScenarios();
}
