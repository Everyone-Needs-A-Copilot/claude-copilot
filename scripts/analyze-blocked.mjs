/**
 * Analyze Blocked Tasks
 * Uses Task Copilot's DatabaseClient to analyze blocked tasks
 */

import { DatabaseClient } from './mcp-servers/task-copilot/dist/database.js';
import { homedir } from 'os';
import { join } from 'path';

const DB_PATH = join(homedir(), '.claude', 'tasks');
const WORKSPACE_ID = 'claude-copilot';

console.log('Analyzing Blocked Tasks in Task Copilot Database\n');
console.log('='.repeat(70) + '\n');

try {
  const db = new DatabaseClient(DB_PATH, DB_PATH, WORKSPACE_ID);

  // Get all tasks
  const allTasks = db.listTasks({});
  const blockedTasks = allTasks.filter(t => t.status === 'blocked' && !t.archived);

  console.log(`Total tasks: ${allTasks.length}`);
  console.log(`Blocked tasks: ${blockedTasks.length}\n`);

  if (blockedTasks.length === 0) {
    console.log('No blocked tasks found. Exiting.\n');
    db.close();
    process.exit(0);
  }

  // Categorize blockers
  const categories = {
    missingDependencies: [],
    waitingOnTasks: [],
    streamDependencies: [],
    externalBlockers: [],
    uncategorized: []
  };

  const streamInfo = new Map();
  const mentionedTaskIds = new Set();

  blockedTasks.forEach(task => {
    const metadata = task.metadata || {};
    const streamId = metadata.streamId;
    const streamDependencies = metadata.streamDependencies || [];
    const reason = (task.blocked_reason || '').toLowerCase();

    // Store stream info
    if (streamId) {
      if (!streamInfo.has(streamId)) {
        streamInfo.set(streamId, {
          streamId,
          streamName: metadata.streamName,
          streamPhase: metadata.streamPhase,
          blockedTasks: []
        });
      }
      streamInfo.get(streamId).blockedTasks.push(task);
    }

    // Extract task IDs from blocker reason
    const taskIdMatches = (task.blocked_reason || '').match(/TASK-[A-Z0-9]+/g);
    if (taskIdMatches) {
      taskIdMatches.forEach(id => mentionedTaskIds.add(id));
    }

    // Categorize
    if (reason.includes('dependency') || reason.includes('dependencies') || reason.includes('depends on')) {
      categories.missingDependencies.push(task);
    } else if (reason.includes('waiting for') || reason.includes('blocked by task') || reason.includes('task-')) {
      categories.waitingOnTasks.push(task);
    } else if (streamDependencies.length > 0) {
      categories.streamDependencies.push(task);
    } else if (reason.includes('external') || reason.includes('third party') || reason.includes('api')) {
      categories.externalBlockers.push(task);
    } else {
      categories.uncategorized.push(task);
    }
  });

  // Print categorized results
  console.log('BLOCKER CATEGORIES');
  console.log('='.repeat(70) + '\n');

  console.log(`1. Missing Dependencies: ${categories.missingDependencies.length} tasks`);
  if (categories.missingDependencies.length > 0) {
    categories.missingDependencies.slice(0, 10).forEach(task => {
      const metadata = task.metadata || {};
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Agent: ${task.assigned_agent}`);
      console.log(`     Reason: ${task.blocked_reason}`);
    });
    if (categories.missingDependencies.length > 10) {
      console.log(`   ... and ${categories.missingDependencies.length - 10} more`);
    }
  }
  console.log();

  console.log(`2. Waiting on Other Tasks: ${categories.waitingOnTasks.length} tasks`);
  if (categories.waitingOnTasks.length > 0) {
    categories.waitingOnTasks.slice(0, 10).forEach(task => {
      const metadata = task.metadata || {};
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Agent: ${task.assigned_agent}`);
      console.log(`     Reason: ${task.blocked_reason}`);
    });
    if (categories.waitingOnTasks.length > 10) {
      console.log(`   ... and ${categories.waitingOnTasks.length - 10} more`);
    }
  }
  console.log();

  console.log(`3. Stream Dependencies: ${categories.streamDependencies.length} tasks`);
  if (categories.streamDependencies.length > 0) {
    categories.streamDependencies.slice(0, 10).forEach(task => {
      const metadata = task.metadata || {};
      const deps = metadata.streamDependencies || [];
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Depends on: ${deps.join(', ')}`);
      console.log(`     Reason: ${task.blocked_reason || 'N/A'}`);
    });
    if (categories.streamDependencies.length > 10) {
      console.log(`   ... and ${categories.streamDependencies.length - 10} more`);
    }
  }
  console.log();

  console.log(`4. External Blockers: ${categories.externalBlockers.length} tasks`);
  if (categories.externalBlockers.length > 0) {
    categories.externalBlockers.slice(0, 10).forEach(task => {
      const metadata = task.metadata || {};
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Agent: ${task.assigned_agent}`);
      console.log(`     Reason: ${task.blocked_reason}`);
    });
    if (categories.externalBlockers.length > 10) {
      console.log(`   ... and ${categories.externalBlockers.length - 10} more`);
    }
  }
  console.log();

  console.log(`5. Uncategorized: ${categories.uncategorized.length} tasks`);
  if (categories.uncategorized.length > 0) {
    categories.uncategorized.slice(0, 10).forEach(task => {
      const metadata = task.metadata || {};
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Agent: ${task.assigned_agent}`);
      console.log(`     Reason: ${task.blocked_reason || 'No reason provided'}`);
    });
    if (categories.uncategorized.length > 10) {
      console.log(`   ... and ${categories.uncategorized.length - 10} more`);
    }
  }
  console.log();

  // Stream analysis
  console.log('STREAM ANALYSIS');
  console.log('='.repeat(70) + '\n');

  if (streamInfo.size > 0) {
    console.log(`Blocked tasks span ${streamInfo.size} different streams:\n`);
    Array.from(streamInfo.values()).forEach(stream => {
      console.log(`Stream: ${stream.streamId} (${stream.streamName || 'Unknown'})`);
      console.log(`  Phase: ${stream.streamPhase || 'Unknown'}`);
      console.log(`  Blocked tasks: ${stream.blockedTasks.length}`);
      console.log(`  Tasks: ${stream.blockedTasks.map(t => t.id).join(', ')}`);
      console.log();
    });
  } else {
    console.log('No stream metadata found on blocked tasks\n');
  }

  // Dependency check
  console.log('DEPENDENCY CHECK');
  console.log('='.repeat(70) + '\n');

  if (mentionedTaskIds.size > 0) {
    console.log(`Found ${mentionedTaskIds.size} task IDs mentioned in blocker reasons\n`);

    const tasksToCheck = Array.from(mentionedTaskIds).map(id => {
      try {
        return db.getTask(id);
      } catch (e) {
        return null;
      }
    }).filter(t => t !== null);

    tasksToCheck.forEach(task => {
      console.log(`  ${task.id}: ${task.title}`);
      console.log(`    Status: ${task.status}`);
      if (task.status === 'completed') {
        console.log(`    ✓ This blocker may be resolved!`);
      }
      console.log();
    });
  } else {
    console.log('No specific task IDs found in blocker reasons\n');
  }

  // Stream dependency check
  console.log('STREAM DEPENDENCY CHECK');
  console.log('='.repeat(70) + '\n');

  if (categories.streamDependencies.length > 0) {
    console.log(`Found ${categories.streamDependencies.length} tasks with stream dependencies\n`);

    categories.streamDependencies.forEach(task => {
      const metadata = task.metadata || {};
      const deps = metadata.streamDependencies || [];

      console.log(`${task.id}: ${task.title}`);
      console.log(`  Stream: ${metadata.streamId}`);
      console.log(`  Depends on streams: ${deps.join(', ')}`);

      // Check if dependency streams are complete
      deps.forEach(depStreamId => {
        const depStreamTasks = allTasks.filter(t => {
          const m = t.metadata || {};
          return m.streamId === depStreamId && !t.archived;
        });

        const total = depStreamTasks.length;
        const completed = depStreamTasks.filter(t => t.status === 'completed').length;

        console.log(`    ${depStreamId}: ${completed}/${total} tasks completed`);
        if (completed === total && total > 0) {
          console.log(`    ✓ This stream dependency is complete!`);
        }
      });
      console.log();
    });
  } else {
    console.log('No tasks with stream dependencies found\n');
  }

  // Summary and recommendations
  console.log('SUMMARY & RECOMMENDATIONS');
  console.log('='.repeat(70) + '\n');

  let potentiallyUnblockable = 0;
  const unblockableTaskIds = [];

  // Check completed task dependencies
  mentionedTaskIds.forEach(taskId => {
    try {
      const task = db.getTask(taskId);
      if (task && task.status === 'completed') {
        const affectedTasks = blockedTasks.filter(t =>
          (t.blocked_reason || '').includes(taskId)
        );
        potentiallyUnblockable += affectedTasks.length;
        affectedTasks.forEach(t => {
          if (!unblockableTaskIds.includes(t.id)) {
            unblockableTaskIds.push(t.id);
          }
        });
      }
    } catch (e) {
      // Task not found, skip
    }
  });

  // Check completed stream dependencies
  categories.streamDependencies.forEach(task => {
    const metadata = task.metadata || {};
    const deps = metadata.streamDependencies || [];

    const allDepsComplete = deps.every(depStreamId => {
      const depStreamTasks = allTasks.filter(t => {
        const m = t.metadata || {};
        return m.streamId === depStreamId && !t.archived;
      });

      const total = depStreamTasks.length;
      const completed = depStreamTasks.filter(t => t.status === 'completed').length;

      return completed === total && total > 0;
    });

    if (allDepsComplete && !unblockableTaskIds.includes(task.id)) {
      potentiallyUnblockable++;
      unblockableTaskIds.push(task.id);
    }
  });

  console.log(`Total blocked tasks: ${blockedTasks.length}`);
  console.log(`Potentially unblockable: ${potentiallyUnblockable} tasks`);

  if (unblockableTaskIds.length > 0) {
    console.log(`\nTasks that can potentially be unblocked:`);
    unblockableTaskIds.forEach(id => {
      const task = blockedTasks.find(t => t.id === id);
      console.log(`  - ${id}: ${task.title}`);
      console.log(`    Reason: ${task.blocked_reason}`);
    });
  }

  console.log(`\nRecommendations:`);
  console.log(`  1. Review ${potentiallyUnblockable} tasks with resolved dependencies`);
  console.log(`  2. Update ${categories.uncategorized.length} tasks with better blocker descriptions`);
  console.log(`  3. Check external blockers (${categories.externalBlockers.length}) for status updates`);
  console.log(`  4. Consider breaking down large blocked tasks into smaller units`);

  console.log('\n' + '='.repeat(70));

  // Output unblockable task IDs for scripting
  if (unblockableTaskIds.length > 0) {
    console.log('\nUNBLOCKABLE_TASK_IDS=' + unblockableTaskIds.join(','));
  }

  db.close();

} catch (error) {
  console.error('Error analyzing blocked tasks:', error);
  console.error(error.stack);
  process.exit(1);
}
