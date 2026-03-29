#!/usr/bin/env node
/**
 * Analyze and Unblock Tasks
 * Bulk unblock tasks where dependencies are now resolved
 *
 * Usage:
 *   node unblock-tasks.mjs --dry-run    # Analysis only, no changes
 *   node unblock-tasks.mjs              # Execute unblock operations
 */

import { DatabaseClient } from './mcp-servers/task-copilot/dist/database.js';
import { homedir } from 'os';
import { join } from 'path';

const DB_PATH = join(homedir(), '.claude', 'tasks');
const WORKSPACE_ID = 'claude-copilot';
const DRY_RUN = process.argv.includes('--dry-run');

console.log('='.repeat(70));
console.log('BLOCKED TASKS ANALYZER & UNBLOCKER');
console.log('='.repeat(70));
console.log(`Mode: ${DRY_RUN ? 'DRY RUN (no changes)' : 'LIVE (will update tasks)'}\n`);

try {
  const db = new DatabaseClient(DB_PATH, DB_PATH, WORKSPACE_ID);

  // Get all tasks
  const allTasks = db.listTasks({});
  const blockedTasks = allTasks.filter(t => t.status === 'blocked' && !t.archived);

  console.log(`Total tasks in database: ${allTasks.length}`);
  console.log(`Blocked tasks: ${blockedTasks.length}\n`);

  if (blockedTasks.length === 0) {
    console.log('✓ No blocked tasks found. System is healthy!\n');
    db.close();
    process.exit(0);
  }

  // Analyze blockers
  const analysis = {
    taskDependencies: new Map(), // taskId -> [dependent tasks]
    streamDependencies: new Map(), // streamId -> [dependent tasks]
    unblockable: [],
    needsReview: []
  };

  // First pass: categorize all blocked tasks
  console.log('Analyzing blocked tasks...\n');

  blockedTasks.forEach(task => {
    const metadata = task.metadata || {};
    const reason = task.blocked_reason || '';

    // Extract task IDs from blocker reason
    const taskIdMatches = reason.match(/TASK-[A-Z0-9]+/g);
    if (taskIdMatches) {
      taskIdMatches.forEach(depTaskId => {
        if (!analysis.taskDependencies.has(depTaskId)) {
          analysis.taskDependencies.set(depTaskId, []);
        }
        analysis.taskDependencies.get(depTaskId).push(task);
      });
    }

    // Check stream dependencies
    const streamDeps = metadata.streamDependencies || [];
    if (streamDeps.length > 0) {
      streamDeps.forEach(depStreamId => {
        if (!analysis.streamDependencies.has(depStreamId)) {
          analysis.streamDependencies.set(depStreamId, []);
        }
        analysis.streamDependencies.get(depStreamId).push(task);
      });
    }

    // If no dependencies found, needs manual review
    if (taskIdMatches.length === 0 && streamDeps.length === 0) {
      analysis.needsReview.push(task);
    }
  });

  // Second pass: check if dependencies are resolved
  console.log('Checking dependency resolution...\n');

  // Check task dependencies
  analysis.taskDependencies.forEach((dependentTasks, depTaskId) => {
    try {
      const depTask = db.getTask(depTaskId);
      if (depTask && depTask.status === 'completed') {
        console.log(`✓ ${depTaskId} is completed`);
        dependentTasks.forEach(task => {
          if (!analysis.unblockable.find(t => t.id === task.id)) {
            analysis.unblockable.push(task);
            console.log(`  → Can unblock ${task.id}: ${task.title}`);
          }
        });
      } else {
        console.log(`✗ ${depTaskId} is not completed (${depTask?.status || 'not found'})`);
      }
    } catch (e) {
      console.log(`✗ ${depTaskId} not found in database`);
    }
  });

  console.log();

  // Check stream dependencies
  analysis.streamDependencies.forEach((dependentTasks, depStreamId) => {
    const depStreamTasks = allTasks.filter(t => {
      const m = t.metadata || {};
      return m.streamId === depStreamId && !t.archived;
    });

    const total = depStreamTasks.length;
    const completed = depStreamTasks.filter(t => t.status === 'completed').length;

    if (completed === total && total > 0) {
      console.log(`✓ Stream ${depStreamId} is complete (${completed}/${total})`);
      dependentTasks.forEach(task => {
        if (!analysis.unblockable.find(t => t.id === task.id)) {
          analysis.unblockable.push(task);
          console.log(`  → Can unblock ${task.id}: ${task.title}`);
        }
      });
    } else if (total === 0) {
      console.log(`⚠ Stream ${depStreamId} has no tasks`);
    } else {
      console.log(`✗ Stream ${depStreamId} incomplete (${completed}/${total})`);
    }
  });

  console.log('\n' + '='.repeat(70));
  console.log('SUMMARY');
  console.log('='.repeat(70) + '\n');

  console.log(`Total blocked tasks: ${blockedTasks.length}`);
  console.log(`Can be unblocked: ${analysis.unblockable.length}`);
  console.log(`Need manual review: ${analysis.needsReview.length}\n`);

  if (analysis.unblockable.length > 0) {
    console.log('TASKS READY TO UNBLOCK:');
    console.log('-'.repeat(70));
    analysis.unblockable.forEach(task => {
      console.log(`\n${task.id}: ${task.title}`);
      console.log(`  Agent: ${task.assigned_agent}`);
      console.log(`  Stream: ${task.metadata?.streamId || 'N/A'}`);
      console.log(`  Blocker: ${task.blocked_reason}`);
    });
    console.log();
  }

  if (analysis.needsReview.length > 0) {
    console.log('\nTASKS NEEDING MANUAL REVIEW:');
    console.log('-'.repeat(70));
    analysis.needsReview.slice(0, 10).forEach(task => {
      console.log(`\n${task.id}: ${task.title}`);
      console.log(`  Agent: ${task.assigned_agent}`);
      console.log(`  Stream: ${task.metadata?.streamId || 'N/A'}`);
      console.log(`  Blocker: ${task.blocked_reason || 'No reason provided'}`);
    });
    if (analysis.needsReview.length > 10) {
      console.log(`\n... and ${analysis.needsReview.length - 10} more`);
    }
    console.log();
  }

  // Perform unblocking
  if (analysis.unblockable.length > 0) {
    console.log('='.repeat(70));
    if (DRY_RUN) {
      console.log('DRY RUN MODE - No changes made');
      console.log('Run without --dry-run to actually unblock tasks');
    } else {
      console.log('UNBLOCKING TASKS...');
      console.log('-'.repeat(70) + '\n');

      let unblocked = 0;
      let failed = 0;

      analysis.unblockable.forEach(task => {
        try {
          db.updateTask(task.id, {
            status: 'pending',
            notes: `Automatically unblocked: dependencies resolved at ${new Date().toISOString()}\nPrevious blocker: ${task.blocked_reason}`,
            blocked_reason: null
          });
          console.log(`✓ Unblocked ${task.id}`);
          unblocked++;
        } catch (e) {
          console.log(`✗ Failed to unblock ${task.id}: ${e.message}`);
          failed++;
        }
      });

      console.log('\n' + '='.repeat(70));
      console.log('UNBLOCK COMPLETE');
      console.log('='.repeat(70));
      console.log(`Successfully unblocked: ${unblocked}`);
      console.log(`Failed: ${failed}`);
      console.log(`Still blocked: ${blockedTasks.length - unblocked}`);
    }
  }

  console.log('\n' + '='.repeat(70));
  console.log('RECOMMENDATIONS');
  console.log('='.repeat(70) + '\n');

  const patternsFound = [];

  if (analysis.taskDependencies.size > 0) {
    patternsFound.push(`${analysis.taskDependencies.size} tasks have specific task dependencies`);
  }

  if (analysis.streamDependencies.size > 0) {
    patternsFound.push(`${analysis.streamDependencies.size} streams have dependent tasks`);
  }

  if (analysis.needsReview.length > 0) {
    patternsFound.push(`${analysis.needsReview.length} tasks lack clear dependency information`);
  }

  if (patternsFound.length > 0) {
    console.log('Patterns identified:');
    patternsFound.forEach(pattern => console.log(`  • ${pattern}`));
    console.log();
  }

  console.log('Next steps:');
  if (analysis.unblockable.length > 0 && DRY_RUN) {
    console.log(`  1. Run without --dry-run to unblock ${analysis.unblockable.length} tasks`);
  }
  if (analysis.needsReview.length > 0) {
    console.log(`  2. Review ${analysis.needsReview.length} tasks with unclear blockers`);
    console.log(`  3. Update blocker reasons to include specific TASK-XXX dependencies`);
  }
  if (blockedTasks.length - analysis.unblockable.length > 0) {
    const stillBlocked = blockedTasks.length - analysis.unblockable.length;
    console.log(`  4. ${stillBlocked} tasks remain blocked on incomplete dependencies`);
    console.log(`  5. Focus on completing foundation streams to unblock parallel work`);
  }

  console.log('\n' + '='.repeat(70) + '\n');

  db.close();

} catch (error) {
  console.error('\nERROR:', error.message);
  console.error(error.stack);
  process.exit(1);
}
