/**
 * Progress Visibility Enhancements Integration Tests
 *
 * Tests for:
 * 1. Milestones in PRD metadata
 * 2. progress_summary with milestone tracking
 * 3. ASCII progress bar utility
 * 4. Velocity trend calculation (7d/14d/30d with ↗↘→ indicators)
 *
 * Run with: npm run test:progress
 */

import { DatabaseClient } from '../database.js';
import { prdCreate, prdGet } from './prd.js';
import { taskCreate, taskUpdate } from './task.js';
import { initiativeLink, progressSummary } from './initiative.js';
import { renderProgressBar, renderMultiProgressBars, calculateTrendIndicator } from '../utils/progress-bar.js';
import type {
  PrdCreateInput,
  TaskCreateInput,
  InitiativeLinkInput,
  ProgressSummaryInput,
  Milestone,
  PrdMetadata
} from '../types.js';
import { mkdirSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

// ============================================================================
// TEST HELPERS
// ============================================================================

let testCount = 0;
let passCount = 0;
let failCount = 0;
const testResults: Array<{ name: string; passed: boolean; error?: string }> = [];

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

function createTestDatabase(): DatabaseClient {
  const testDir = join(tmpdir(), `task-copilot-progress-test-${Date.now()}`);
  mkdirSync(testDir, { recursive: true });

  const db = new DatabaseClient(
    '/test/project',
    testDir,
    `test-${Date.now()}`
  );

  return db;
}

function setupInitiative(db: DatabaseClient): string {
  const input: InitiativeLinkInput = {
    initiativeId: 'INIT-PROGRESS-TEST',
    title: 'Progress Test Initiative',
    description: 'Testing progress visibility features'
  };

  const result = initiativeLink(db, input);
  return result.initiativeId;
}

async function runTest(name: string, fn: () => Promise<void>): Promise<void> {
  testCount++;
  console.log(`\n${testCount}. ${name}`);
  console.log('='.repeat(60));

  try {
    await fn();
    passCount++;
    console.log('✓ PASSED');
    testResults.push({ name, passed: true });
  } catch (error) {
    failCount++;
    console.error('✗ FAILED:', (error as Error).message);
    testResults.push({
      name,
      passed: false,
      error: (error as Error).message
    });
  }
}

// Helper to simulate passage of time by backdating tasks
function backdateTask(db: DatabaseClient, taskId: string, daysAgo: number): void {
  const backdate = new Date();
  backdate.setDate(backdate.getDate() - daysAgo);
  const backdateISO = backdate.toISOString();

  db.getDb().prepare(`
    UPDATE tasks
    SET updated_at = ?
    WHERE id = ?
  `).run(backdateISO, taskId);
}

// ============================================================================
// MILESTONE TESTS
// ============================================================================

async function testMilestonesInPrdMetadata(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create PRD with milestones
  const milestones: Milestone[] = [
    {
      id: 'M1',
      name: 'Foundation',
      description: 'Core infrastructure',
      taskIds: []
    },
    {
      id: 'M2',
      name: 'Features',
      description: 'User-facing features',
      taskIds: []
    },
    {
      id: 'M3',
      name: 'Polish',
      description: 'Final touches',
      taskIds: []
    }
  ];

  const prdInput: PrdCreateInput = {
    title: 'Test PRD with Milestones',
    content: 'PRD content',
    metadata: {
      milestones,
      priority: 'P0'
    }
  };

  const created = await prdCreate(db, prdInput);
  assert(!!created.id, 'PRD should be created');

  // Retrieve and verify milestones
  const retrieved = prdGet(db, { id: created.id, includeContent: true });
  const metadata = retrieved.metadata as PrdMetadata;

  assert(!!metadata.milestones, 'Milestones should exist');
  assert(metadata.milestones!.length === 3, 'Should have 3 milestones');
  assert(metadata.milestones![0].id === 'M1', 'First milestone ID should be M1');
  assert(metadata.milestones![0].name === 'Foundation', 'First milestone name should be Foundation');
  assert(metadata.milestones![1].id === 'M2', 'Second milestone ID should be M2');
  assert(metadata.milestones![2].id === 'M3', 'Third milestone ID should be M3');

  db.close();
}

async function testMilestoneProgressCalculation(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create tasks first
  const task1 = await taskCreate(db, { title: 'Task 1' });
  const task2 = await taskCreate(db, { title: 'Task 2' });
  const task3 = await taskCreate(db, { title: 'Task 3' });
  const task4 = await taskCreate(db, { title: 'Task 4' });

  // Create PRD with milestones referencing tasks
  const milestones: Milestone[] = [
    {
      id: 'M1',
      name: 'Phase 1',
      taskIds: [task1.id, task2.id]
    },
    {
      id: 'M2',
      name: 'Phase 2',
      taskIds: [task3.id, task4.id]
    }
  ];

  const prdInput: PrdCreateInput = {
    title: 'PRD with Task Milestones',
    content: 'Content',
    metadata: { milestones }
  };

  await prdCreate(db, prdInput);

  // Complete one task from each milestone
  await taskUpdate(db, { id: task1.id, status: 'completed' });
  await taskUpdate(db, { id: task3.id, status: 'completed' });

  // Get progress summary
  const summary = progressSummary(db, { initiativeId });

  assert(!!summary.milestones, 'Milestones should be present in summary');
  assert(summary.milestones.length === 2, 'Should have 2 milestones');

  // Check Phase 1 milestone (1 of 2 complete = 50%)
  const m1 = summary.milestones.find(m => m.id === 'M1');
  assert(!!m1, 'Milestone M1 should exist');
  assert(m1.totalTasks === 2, 'M1 should have 2 total tasks');
  assert(m1.completedTasks === 1, 'M1 should have 1 completed task');
  assert(m1.percentComplete === 50, 'M1 should be 50% complete');
  assert(m1.isComplete === false, 'M1 should not be complete');

  // Check Phase 2 milestone (1 of 2 complete = 50%)
  const m2 = summary.milestones.find(m => m.id === 'M2');
  assert(!!m2, 'Milestone M2 should exist');
  assert(m2.totalTasks === 2, 'M2 should have 2 total tasks');
  assert(m2.completedTasks === 1, 'M2 should have 1 completed task');
  assert(m2.percentComplete === 50, 'M2 should be 50% complete');
  assert(m2.isComplete === false, 'M2 should not be complete');

  // Complete remaining tasks
  await taskUpdate(db, { id: task2.id, status: 'completed' });
  await taskUpdate(db, { id: task4.id, status: 'completed' });

  const finalSummary = progressSummary(db, { initiativeId });
  const m1Final = finalSummary.milestones!.find(m => m.id === 'M1');
  const m2Final = finalSummary.milestones!.find(m => m.id === 'M2');

  assert(m1Final!.percentComplete === 100, 'M1 should be 100% complete');
  assert(m1Final!.isComplete === true, 'M1 should be marked complete');
  assert(m2Final!.percentComplete === 100, 'M2 should be 100% complete');
  assert(m2Final!.isComplete === true, 'M2 should be marked complete');

  db.close();
}

async function testEmptyMilestone(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create milestone with no tasks
  const milestones: Milestone[] = [
    {
      id: 'M1',
      name: 'Empty Milestone',
      taskIds: []
    }
  ];

  const prdInput: PrdCreateInput = {
    title: 'PRD with Empty Milestone',
    content: 'Content',
    metadata: { milestones }
  };

  await prdCreate(db, prdInput);

  const summary = progressSummary(db, { initiativeId });

  assert(!!summary.milestones, 'Milestones should exist');
  const m1 = summary.milestones[0];
  assert(m1.totalTasks === 0, 'Should have 0 total tasks');
  assert(m1.completedTasks === 0, 'Should have 0 completed tasks');
  assert(m1.percentComplete === 0, 'Should be 0% complete');
  assert(m1.isComplete === false, 'Empty milestone should not be complete');

  db.close();
}

// ============================================================================
// ASCII PROGRESS BAR TESTS
// ============================================================================

async function testBasicProgressBar(): Promise<void> {
  // Test basic rendering
  const bar1 = renderProgressBar(0, 10);
  assert(bar1.includes('0%'), 'Should show 0%');
  assert(bar1.includes('(0/10)'), 'Should show count');
  assert(bar1.includes('░'), 'Should have empty characters');

  const bar2 = renderProgressBar(5, 10);
  assert(bar2.includes('50%'), 'Should show 50%');
  assert(bar2.includes('(5/10)'), 'Should show count');
  assert(bar2.includes('█'), 'Should have filled characters');
  assert(bar2.includes('░'), 'Should have empty characters');

  const bar3 = renderProgressBar(10, 10);
  assert(bar3.includes('100%'), 'Should show 100%');
  assert(bar3.includes('(10/10)'), 'Should show count');
  assert(!bar3.includes('░'), 'Should have no empty characters when complete');
}

async function testProgressBarOptions(): Promise<void> {
  // Test without percentage
  const bar1 = renderProgressBar(5, 10, { showPercentage: false });
  assert(!bar1.includes('%'), 'Should not show percentage');
  assert(bar1.includes('(5/10)'), 'Should still show count');

  // Test without count
  const bar2 = renderProgressBar(5, 10, { showCount: false });
  assert(bar2.includes('50%'), 'Should show percentage');
  assert(!bar2.includes('(5/10)'), 'Should not show count');

  // Test custom width
  const bar3 = renderProgressBar(5, 10, { width: 10 });
  const matches = bar3.match(/\[(.+?)\]/);
  assert(!!matches, 'Should have brackets');
  assert(matches![1].length === 10, 'Bar width should be 10');

  // Test custom characters
  const bar4 = renderProgressBar(5, 10, { filled: '#', empty: '-' });
  assert(bar4.includes('#'), 'Should use custom filled character');
  assert(bar4.includes('-'), 'Should use custom empty character');
}

async function testProgressBarEdgeCases(): Promise<void> {
  // Zero total
  const bar1 = renderProgressBar(0, 0);
  assert(bar1.includes('0%'), 'Should handle 0/0 gracefully');
  assert(bar1.includes('(0/0)'), 'Should show 0/0 count');

  // More completed than total (should not happen but handle gracefully)
  const bar2 = renderProgressBar(15, 10);
  assert(bar2.includes('150%'), 'Should show >100%');

  // Negative values (edge case)
  const bar3 = renderProgressBar(-1, 10);
  const barContent = bar3.match(/\[(.+?)\]/);
  assert(!!barContent, 'Should still render');
}

async function testMultiProgressBars(): Promise<void> {
  const items = [
    { label: 'Frontend', completed: 5, total: 10 },
    { label: 'Backend', completed: 8, total: 10 },
    { label: 'Tests', completed: 2, total: 10 }
  ];

  const result = renderMultiProgressBars(items);
  const lines = result.split('\n');

  assert(lines.length === 3, 'Should have 3 lines');
  assert(lines[0].includes('Frontend'), 'First line should be Frontend');
  assert(lines[1].includes('Backend'), 'Second line should be Backend');
  assert(lines[2].includes('Tests'), 'Third line should be Tests');
  assert(lines[0].includes('50%'), 'Frontend should show 50%');
  assert(lines[1].includes('80%'), 'Backend should show 80%');
  assert(lines[2].includes('20%'), 'Tests should show 20%');

  // Test empty array
  const emptyResult = renderMultiProgressBars([]);
  assert(emptyResult === '', 'Should return empty string for empty array');
}

async function testProgressBarInSummary(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create tasks
  const task1 = await taskCreate(db, { title: 'Task 1' });
  const task2 = await taskCreate(db, { title: 'Task 2' });
  const task3 = await taskCreate(db, { title: 'Task 3' });
  const task4 = await taskCreate(db, { title: 'Task 4' });

  // Complete some tasks
  await taskUpdate(db, { id: task1.id, status: 'completed' });
  await taskUpdate(db, { id: task2.id, status: 'completed' });

  // Get progress summary
  const summary = progressSummary(db, { initiativeId });

  assert(!!summary.tasks.progressBar, 'Progress bar should exist in summary');
  assert(summary.tasks.progressBar.includes('50%'), 'Should show 50%');
  assert(summary.tasks.progressBar.includes('(2/4)'), 'Should show 2/4');
  assert(summary.tasks.progressBar.includes('['), 'Should have opening bracket');
  assert(summary.tasks.progressBar.includes(']'), 'Should have closing bracket');

  db.close();
}

// ============================================================================
// VELOCITY TREND TESTS
// ============================================================================

async function testVelocityCalculation7Days(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create and complete tasks at different times
  const task1 = await taskCreate(db, { title: 'Task 1' });
  const task2 = await taskCreate(db, { title: 'Task 2' });
  const task3 = await taskCreate(db, { title: 'Task 3' });
  const task4 = await taskCreate(db, { title: 'Task 4' });

  // Complete tasks and backdate them
  await taskUpdate(db, { id: task1.id, status: 'completed' });
  backdateTask(db, task1.id, 6); // 6 days ago

  await taskUpdate(db, { id: task2.id, status: 'completed' });
  backdateTask(db, task2.id, 5); // 5 days ago

  await taskUpdate(db, { id: task3.id, status: 'completed' });
  backdateTask(db, task3.id, 2); // 2 days ago

  await taskUpdate(db, { id: task4.id, status: 'completed' });
  backdateTask(db, task4.id, 1); // 1 day ago

  const summary = progressSummary(db, { initiativeId });

  assert(!!summary.velocity, 'Velocity should be present');
  const velocity7d = summary.velocity.find(v => v.period === '7d');
  assert(!!velocity7d, '7d velocity should exist');
  assert(velocity7d.tasksCompleted === 4, 'Should have 4 completed tasks');
  assert(velocity7d.tasksPerDay > 0, 'Should have positive tasks per day');
  assert(['improving', 'stable', 'declining', 'insufficient_data'].includes(velocity7d.trend), 'Should have valid trend');

  db.close();
}

async function testVelocityTrends(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create tasks with improving trend (more in second half)
  const tasks = [];
  for (let i = 0; i < 8; i++) {
    const task = await taskCreate(db, { title: `Task ${i + 1}` });
    await taskUpdate(db, { id: task.id, status: 'completed' });
    tasks.push(task);
  }

  // Backdate tasks: 2 in first half (days 6-4), 6 in second half (days 3-1)
  backdateTask(db, tasks[0].id, 6);
  backdateTask(db, tasks[1].id, 5);
  backdateTask(db, tasks[2].id, 3);
  backdateTask(db, tasks[3].id, 3);
  backdateTask(db, tasks[4].id, 2);
  backdateTask(db, tasks[5].id, 2);
  backdateTask(db, tasks[6].id, 1);
  backdateTask(db, tasks[7].id, 1);

  const summary = progressSummary(db, { initiativeId });
  const velocity7d = summary.velocity!.find(v => v.period === '7d');

  assert(!!velocity7d, '7d velocity should exist');
  assert(velocity7d.tasksCompleted === 8, 'Should have 8 completed tasks');
  // Trend should be 'improving' because second half has more tasks (6 vs 2)
  assert(velocity7d.trend === 'improving', 'Trend should be improving');

  db.close();
}

async function testDecliningVelocity(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create tasks with declining trend (more in first half)
  const tasks = [];
  for (let i = 0; i < 8; i++) {
    const task = await taskCreate(db, { title: `Task ${i + 1}` });
    await taskUpdate(db, { id: task.id, status: 'completed' });
    tasks.push(task);
  }

  // Backdate tasks: 6 in first half (days 7-5), 2 in second half (days 2-1)
  // midDate = now - 4 days, so tasks < midDate are in first half
  backdateTask(db, tasks[0].id, 7);
  backdateTask(db, tasks[1].id, 7);
  backdateTask(db, tasks[2].id, 6);
  backdateTask(db, tasks[3].id, 6);
  backdateTask(db, tasks[4].id, 5);
  backdateTask(db, tasks[5].id, 5);
  backdateTask(db, tasks[6].id, 2);
  backdateTask(db, tasks[7].id, 1);

  const summary = progressSummary(db, { initiativeId });
  const velocity7d = summary.velocity!.find(v => v.period === '7d');

  assert(!!velocity7d, '7d velocity should exist');
  assert(velocity7d.trend === 'declining', 'Trend should be declining');

  db.close();
}

async function testStableVelocity(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create tasks with stable trend (roughly equal distribution)
  const tasks = [];
  for (let i = 0; i < 8; i++) {
    const task = await taskCreate(db, { title: `Task ${i + 1}` });
    await taskUpdate(db, { id: task.id, status: 'completed' });
    tasks.push(task);
  }

  // Backdate tasks evenly: 4 in first half (days 7-5), 4 in second half (days 3-1)
  // midDate = now - 4 days, so tasks < midDate are in first half
  backdateTask(db, tasks[0].id, 7);
  backdateTask(db, tasks[1].id, 6);
  backdateTask(db, tasks[2].id, 5);
  backdateTask(db, tasks[3].id, 5);
  backdateTask(db, tasks[4].id, 3);
  backdateTask(db, tasks[5].id, 2);
  backdateTask(db, tasks[6].id, 1);
  backdateTask(db, tasks[7].id, 1);

  const summary = progressSummary(db, { initiativeId });
  const velocity7d = summary.velocity!.find(v => v.period === '7d');

  assert(!!velocity7d, '7d velocity should exist');
  assert(velocity7d.trend === 'stable', 'Trend should be stable');

  db.close();
}

async function testInsufficientDataVelocity(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create only 2 tasks (below 4 task threshold)
  const task1 = await taskCreate(db, { title: 'Task 1' });
  const task2 = await taskCreate(db, { title: 'Task 2' });

  await taskUpdate(db, { id: task1.id, status: 'completed' });
  await taskUpdate(db, { id: task2.id, status: 'completed' });

  backdateTask(db, task1.id, 5);
  backdateTask(db, task2.id, 2);

  const summary = progressSummary(db, { initiativeId });
  const velocity7d = summary.velocity!.find(v => v.period === '7d');

  assert(!!velocity7d, '7d velocity should exist');
  assert(velocity7d.tasksCompleted === 2, 'Should have 2 completed tasks');
  assert(velocity7d.trend === 'insufficient_data', 'Trend should be insufficient_data');

  db.close();
}

async function testMultiplePeriodVelocity(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create tasks spread over 30 days
  const tasks = [];
  for (let i = 0; i < 20; i++) {
    const task = await taskCreate(db, { title: `Task ${i + 1}` });
    await taskUpdate(db, { id: task.id, status: 'completed' });
    tasks.push(task);
  }

  // Backdate across different periods
  for (let i = 0; i < 20; i++) {
    backdateTask(db, tasks[i].id, i + 1); // 1 to 20 days ago
  }

  const summary = progressSummary(db, { initiativeId });

  assert(!!summary.velocity, 'Velocity should exist');
  assert(summary.velocity.length === 3, 'Should have 3 velocity periods');

  const velocity7d = summary.velocity.find(v => v.period === '7d');
  const velocity14d = summary.velocity.find(v => v.period === '14d');
  const velocity30d = summary.velocity.find(v => v.period === '30d');

  assert(!!velocity7d, '7d velocity should exist');
  assert(!!velocity14d, '14d velocity should exist');
  assert(!!velocity30d, '30d velocity should exist');

  assert(velocity7d.tasksCompleted === 7, '7d should have 7 tasks');
  assert(velocity14d.tasksCompleted === 14, '14d should have 14 tasks');
  assert(velocity30d.tasksCompleted === 20, '30d should have 20 tasks');

  // Verify tasks per day calculation
  assert(velocity7d.tasksPerDay === 1, '7d should be 1 task/day');
  assert(velocity14d.tasksPerDay === 1, '14d should be 1 task/day');
  assert(Math.abs(velocity30d.tasksPerDay - 0.67) < 0.01, '30d should be ~0.67 tasks/day');

  db.close();
}

// ============================================================================
// TREND INDICATOR TESTS
// ============================================================================

async function testTrendIndicatorImproving(): Promise<void> {
  const indicator = calculateTrendIndicator(12, 10); // 20% increase
  assert(indicator === '↗', 'Should show improving trend');

  const indicator2 = calculateTrendIndicator(15, 10); // 50% increase
  assert(indicator2 === '↗', 'Should show improving trend');
}

async function testTrendIndicatorDeclining(): Promise<void> {
  const indicator = calculateTrendIndicator(8, 10); // 20% decrease
  assert(indicator === '↘', 'Should show declining trend');

  const indicator2 = calculateTrendIndicator(5, 10); // 50% decrease
  assert(indicator2 === '↘', 'Should show declining trend');
}

async function testTrendIndicatorStable(): Promise<void> {
  const indicator = calculateTrendIndicator(10, 10); // No change
  assert(indicator === '→', 'Should show stable trend');

  const indicator2 = calculateTrendIndicator(10.5, 10); // 5% increase (below threshold)
  assert(indicator2 === '→', 'Should show stable trend');

  const indicator3 = calculateTrendIndicator(9.5, 10); // 5% decrease (below threshold)
  assert(indicator3 === '→', 'Should show stable trend');
}

async function testTrendIndicatorZeroPrevious(): Promise<void> {
  const indicator1 = calculateTrendIndicator(10, 0); // From 0 to 10
  assert(indicator1 === '↗', 'Should show improving when starting from 0');

  const indicator2 = calculateTrendIndicator(0, 0); // Both 0
  assert(indicator2 === '→', 'Should show stable when both 0');
}

async function testTrendIndicatorCustomThreshold(): Promise<void> {
  // With 5% threshold
  const indicator1 = calculateTrendIndicator(10.6, 10, 0.05); // 6% increase
  assert(indicator1 === '↗', 'Should show improving with 5% threshold');

  const indicator2 = calculateTrendIndicator(10.4, 10, 0.05); // 4% increase
  assert(indicator2 === '→', 'Should show stable with 5% threshold');

  // With 20% threshold (default)
  const indicator3 = calculateTrendIndicator(11.5, 10, 0.2); // 15% increase
  assert(indicator3 === '→', 'Should show stable with 20% threshold');
}

// ============================================================================
// INTEGRATION TESTS
// ============================================================================

async function testFullProgressVisibilityFlow(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create PRD with milestones
  const task1 = await taskCreate(db, { title: 'Foundation Task 1' });
  const task2 = await taskCreate(db, { title: 'Foundation Task 2' });
  const task3 = await taskCreate(db, { title: 'Feature Task 1' });
  const task4 = await taskCreate(db, { title: 'Feature Task 2' });

  const milestones: Milestone[] = [
    {
      id: 'M1',
      name: 'Foundation',
      description: 'Build core infrastructure',
      taskIds: [task1.id, task2.id]
    },
    {
      id: 'M2',
      name: 'Features',
      description: 'Implement user features',
      taskIds: [task3.id, task4.id]
    }
  ];

  const prdInput: PrdCreateInput = {
    title: 'Complete Feature Implementation',
    content: 'Full feature with milestones',
    metadata: { milestones }
  };

  await prdCreate(db, prdInput);

  // Complete tasks at different times
  await taskUpdate(db, { id: task1.id, status: 'completed' });
  backdateTask(db, task1.id, 5);

  await taskUpdate(db, { id: task2.id, status: 'completed' });
  backdateTask(db, task2.id, 3);

  await taskUpdate(db, { id: task3.id, status: 'completed' });
  backdateTask(db, task3.id, 1);

  // Get comprehensive progress summary
  const summary = progressSummary(db, { initiativeId });

  // Verify all components
  assert(!!summary.tasks.progressBar, 'Should have progress bar');
  assert(summary.tasks.progressBar.includes('75%'), 'Should show 75% complete (3/4)');

  assert(!!summary.milestones, 'Should have milestones');
  assert(summary.milestones.length === 2, 'Should have 2 milestones');

  const m1 = summary.milestones.find(m => m.id === 'M1');
  assert(m1!.isComplete === true, 'Foundation milestone should be complete');

  const m2 = summary.milestones.find(m => m.id === 'M2');
  assert(m2!.percentComplete === 50, 'Features milestone should be 50% complete');

  assert(!!summary.velocity, 'Should have velocity data');
  assert(summary.velocity.length === 3, 'Should have 3 velocity periods');

  const velocity7d = summary.velocity.find(v => v.period === '7d');
  assert(velocity7d!.tasksCompleted === 3, 'Should have 3 completed tasks in 7d');
  assert(['improving', 'stable', 'declining', 'insufficient_data'].includes(velocity7d!.trend), 'Should have valid trend');

  db.close();
}

async function testProgressSummaryWithNoPRD(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create tasks without PRD (orphan tasks)
  const task1 = await taskCreate(db, { title: 'Task 1' });
  await taskUpdate(db, { id: task1.id, status: 'completed' });

  const summary = progressSummary(db, { initiativeId });

  assert(summary.tasks.total === 1, 'Should have 1 task');
  assert(summary.tasks.completed === 1, 'Should have 1 completed task');
  assert(!!summary.tasks.progressBar, 'Should have progress bar');
  assert(!summary.milestones || summary.milestones.length === 0, 'Should have no milestones');
  assert(!!summary.velocity, 'Should have velocity data');

  db.close();
}

async function testProgressSummaryWithMultiplePRDs(): Promise<void> {
  const db = createTestDatabase();
  const initiativeId = setupInitiative(db);

  // Create multiple PRDs with different milestones
  const task1 = await taskCreate(db, { title: 'PRD1 Task 1' });
  const task2 = await taskCreate(db, { title: 'PRD1 Task 2' });
  const task3 = await taskCreate(db, { title: 'PRD2 Task 1' });
  const task4 = await taskCreate(db, { title: 'PRD2 Task 2' });

  const prd1 = await prdCreate(db, {
    title: 'PRD 1',
    content: 'Content',
    metadata: {
      milestones: [
        {
          id: 'PRD1-M1',
          name: 'PRD 1 Milestone',
          taskIds: [task1.id, task2.id]
        }
      ]
    }
  });

  const prd2 = await prdCreate(db, {
    title: 'PRD 2',
    content: 'Content',
    metadata: {
      milestones: [
        {
          id: 'PRD2-M1',
          name: 'PRD 2 Milestone',
          taskIds: [task3.id, task4.id]
        }
      ]
    }
  });

  // Complete some tasks
  await taskUpdate(db, { id: task1.id, status: 'completed' });
  await taskUpdate(db, { id: task3.id, status: 'completed' });

  const summary = progressSummary(db, { initiativeId });

  // Should aggregate milestones from all PRDs
  assert(summary.milestones!.length === 2, 'Should have 2 milestones from 2 PRDs');
  assert(summary.prds.total === 2, 'Should have 2 PRDs');
  assert(summary.tasks.total === 4, 'Should have 4 total tasks');
  assert(summary.tasks.completed === 2, 'Should have 2 completed tasks');

  db.close();
}

// ============================================================================
// RUN ALL TESTS
// ============================================================================

async function runAllTests(): Promise<void> {
  console.log('\n' + '='.repeat(60));
  console.log('PROGRESS VISIBILITY INTEGRATION TESTS');
  console.log('='.repeat(60));

  // Milestone tests
  await runTest('Milestones in PRD metadata', testMilestonesInPrdMetadata);
  await runTest('Milestone progress calculation', testMilestoneProgressCalculation);
  await runTest('Empty milestone handling', testEmptyMilestone);

  // ASCII progress bar tests
  await runTest('Basic progress bar rendering', testBasicProgressBar);
  await runTest('Progress bar options', testProgressBarOptions);
  await runTest('Progress bar edge cases', testProgressBarEdgeCases);
  await runTest('Multi progress bars', testMultiProgressBars);
  await runTest('Progress bar in summary', testProgressBarInSummary);

  // Velocity trend tests
  await runTest('Velocity calculation (7 days)', testVelocityCalculation7Days);
  await runTest('Velocity trends detection', testVelocityTrends);
  await runTest('Declining velocity detection', testDecliningVelocity);
  await runTest('Stable velocity detection', testStableVelocity);
  await runTest('Insufficient data handling', testInsufficientDataVelocity);
  await runTest('Multiple period velocity', testMultiplePeriodVelocity);

  // Trend indicator tests
  await runTest('Trend indicator: improving', testTrendIndicatorImproving);
  await runTest('Trend indicator: declining', testTrendIndicatorDeclining);
  await runTest('Trend indicator: stable', testTrendIndicatorStable);
  await runTest('Trend indicator: zero previous', testTrendIndicatorZeroPrevious);
  await runTest('Trend indicator: custom threshold', testTrendIndicatorCustomThreshold);

  // Integration tests
  await runTest('Full progress visibility flow', testFullProgressVisibilityFlow);
  await runTest('Progress summary without PRD', testProgressSummaryWithNoPRD);
  await runTest('Progress summary with multiple PRDs', testProgressSummaryWithMultiplePRDs);

  // Print summary
  console.log('\n' + '='.repeat(60));
  console.log('TEST SUMMARY');
  console.log('='.repeat(60));
  console.log(`Total: ${testCount}`);
  console.log(`✓ Passed: ${passCount}`);
  console.log(`✗ Failed: ${failCount}`);
  console.log('='.repeat(60));

  if (failCount > 0) {
    console.log('\nFailed Tests:');
    testResults
      .filter(r => !r.passed)
      .forEach(r => {
        console.log(`  ✗ ${r.name}`);
        console.log(`    ${r.error}`);
      });
  }

  process.exit(failCount > 0 ? 1 : 0);
}

// Run tests
runAllTests().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});
