/**
 * Analyze Blocked Tasks
 * Query the Task Copilot database to find and categorize blocked tasks
 */

import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { homedir } from 'os';

const require = createRequire(import.meta.url);
const Database = require('./mcp-servers/task-copilot/node_modules/better-sqlite3/lib/index.js');

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Database path from .mcp.json
const WORKSPACE_ID = 'claude-copilot';
const DB_PATH = join(homedir(), '.claude', 'tasks', WORKSPACE_ID, 'tasks.db');

try {
  const db = new Database(DB_PATH, { readonly: true });

  console.log('Analyzing Blocked Tasks in Task Copilot Database\n');
  console.log('='.repeat(70) + '\n');

  // Get all blocked tasks
  const blockedTasks = db.prepare(`
    SELECT
      t.id,
      t.title,
      t.description,
      t.status,
      t.blocked_reason,
      t.assigned_agent,
      t.parent_id,
      t.prd_id,
      t.metadata,
      t.created_at,
      t.updated_at,
      p.title as prd_title,
      i.title as initiative_title
    FROM tasks t
    LEFT JOIN prds p ON t.prd_id = p.id
    LEFT JOIN initiatives i ON p.initiative_id = i.id
    WHERE t.status = 'blocked'
    AND t.archived = 0
    ORDER BY t.created_at ASC
  `).all();

  console.log(`Found ${blockedTasks.length} blocked tasks\n`);

  if (blockedTasks.length === 0) {
    console.log('No blocked tasks found. Exiting.\n');
    db.close();
    process.exit(0);
  }

  // Parse metadata and categorize blockers
  const categorized = {
    missingDependencies: [],
    waitingOnTasks: [],
    externalBlockers: [],
    streamDependencies: [],
    uncategorized: []
  };

  const streamInfo = new Map(); // Track stream dependencies

  blockedTasks.forEach(task => {
    const metadata = task.metadata ? JSON.parse(task.metadata) : {};
    const streamId = metadata.streamId;
    const streamDependencies = metadata.streamDependencies || [];

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

    const reason = (task.blocked_reason || '').toLowerCase();

    // Categorize based on blocked_reason
    if (reason.includes('dependency') || reason.includes('dependencies') || reason.includes('depends on')) {
      categorized.missingDependencies.push(task);
    } else if (reason.includes('waiting for') || reason.includes('blocked by task') || reason.includes('task-')) {
      categorized.waitingOnTasks.push(task);
    } else if (streamDependencies.length > 0) {
      categorized.streamDependencies.push(task);
    } else if (reason.includes('external') || reason.includes('third party') || reason.includes('api')) {
      categorized.externalBlockers.push(task);
    } else {
      categorized.uncategorized.push(task);
    }
  });

  // Print categorized results
  console.log('BLOCKER CATEGORIES');
  console.log('='.repeat(70) + '\n');

  console.log(`1. Missing Dependencies: ${categorized.missingDependencies.length} tasks`);
  if (categorized.missingDependencies.length > 0) {
    categorized.missingDependencies.forEach(task => {
      const metadata = task.metadata ? JSON.parse(task.metadata) : {};
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Agent: ${task.assigned_agent}`);
      console.log(`     Reason: ${task.blocked_reason}`);
    });
  }
  console.log();

  console.log(`2. Waiting on Other Tasks: ${categorized.waitingOnTasks.length} tasks`);
  if (categorized.waitingOnTasks.length > 0) {
    categorized.waitingOnTasks.forEach(task => {
      const metadata = task.metadata ? JSON.parse(task.metadata) : {};
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Agent: ${task.assigned_agent}`);
      console.log(`     Reason: ${task.blocked_reason}`);
    });
  }
  console.log();

  console.log(`3. Stream Dependencies: ${categorized.streamDependencies.length} tasks`);
  if (categorized.streamDependencies.length > 0) {
    categorized.streamDependencies.forEach(task => {
      const metadata = task.metadata ? JSON.parse(task.metadata) : {};
      const deps = metadata.streamDependencies || [];
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Depends on: ${deps.join(', ')}`);
      console.log(`     Reason: ${task.blocked_reason}`);
    });
  }
  console.log();

  console.log(`4. External Blockers: ${categorized.externalBlockers.length} tasks`);
  if (categorized.externalBlockers.length > 0) {
    categorized.externalBlockers.forEach(task => {
      const metadata = task.metadata ? JSON.parse(task.metadata) : {};
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Agent: ${task.assigned_agent}`);
      console.log(`     Reason: ${task.blocked_reason}`);
    });
  }
  console.log();

  console.log(`5. Uncategorized: ${categorized.uncategorized.length} tasks`);
  if (categorized.uncategorized.length > 0) {
    categorized.uncategorized.forEach(task => {
      const metadata = task.metadata ? JSON.parse(task.metadata) : {};
      console.log(`   - ${task.id}: ${task.title}`);
      console.log(`     Stream: ${metadata.streamId || 'N/A'} | Agent: ${task.assigned_agent}`);
      console.log(`     Reason: ${task.blocked_reason || 'No reason provided'}`);
    });
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

  // Check for completed dependencies
  console.log('DEPENDENCY CHECK');
  console.log('='.repeat(70) + '\n');

  // Extract task IDs mentioned in blocked_reason
  const mentionedTaskIds = new Set();
  blockedTasks.forEach(task => {
    const reason = task.blocked_reason || '';
    const matches = reason.match(/TASK-[A-Z0-9]+/g);
    if (matches) {
      matches.forEach(id => mentionedTaskIds.add(id));
    }
  });

  if (mentionedTaskIds.size > 0) {
    console.log(`Found ${mentionedTaskIds.size} task IDs mentioned in blocker reasons\n`);

    const taskStatuses = db.prepare(`
      SELECT id, title, status
      FROM tasks
      WHERE id IN (${Array.from(mentionedTaskIds).map(() => '?').join(',')})
    `).all(...Array.from(mentionedTaskIds));

    taskStatuses.forEach(task => {
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

  // Check stream dependencies
  console.log('STREAM DEPENDENCY CHECK');
  console.log('='.repeat(70) + '\n');

  const streamDependencyTasks = blockedTasks.filter(t => {
    const metadata = t.metadata ? JSON.parse(t.metadata) : {};
    return metadata.streamDependencies && metadata.streamDependencies.length > 0;
  });

  if (streamDependencyTasks.length > 0) {
    console.log(`Found ${streamDependencyTasks.length} tasks with stream dependencies\n`);

    streamDependencyTasks.forEach(task => {
      const metadata = task.metadata ? JSON.parse(task.metadata) : {};
      const deps = metadata.streamDependencies || [];

      console.log(`${task.id}: ${task.title}`);
      console.log(`  Stream: ${metadata.streamId}`);
      console.log(`  Depends on streams: ${deps.join(', ')}`);

      // Check if dependency streams are complete
      deps.forEach(depStreamId => {
        const depStreamTasks = db.prepare(`
          SELECT status, COUNT(*) as count
          FROM tasks
          WHERE json_extract(metadata, '$.streamId') = ?
          AND archived = 0
          GROUP BY status
        `).all(depStreamId);

        const total = depStreamTasks.reduce((sum, row) => sum + row.count, 0);
        const completed = depStreamTasks.find(row => row.status === 'completed')?.count || 0;

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

  console.log(`Total blocked tasks: ${blockedTasks.length}`);
  console.log(`Potentially unblockable: checking...`);

  let potentiallyUnblockable = 0;
  const unblockableTaskIds = [];

  // Check completed task dependencies
  mentionedTaskIds.forEach(taskId => {
    const task = db.prepare('SELECT status FROM tasks WHERE id = ?').get(taskId);
    if (task && task.status === 'completed') {
      const affectedTasks = blockedTasks.filter(t =>
        (t.blocked_reason || '').includes(taskId)
      );
      potentiallyUnblockable += affectedTasks.length;
      affectedTasks.forEach(t => unblockableTaskIds.push(t.id));
    }
  });

  // Check completed stream dependencies
  streamDependencyTasks.forEach(task => {
    const metadata = task.metadata ? JSON.parse(task.metadata) : {};
    const deps = metadata.streamDependencies || [];

    const allDepsComplete = deps.every(depStreamId => {
      const depStreamTasks = db.prepare(`
        SELECT status, COUNT(*) as count
        FROM tasks
        WHERE json_extract(metadata, '$.streamId') = ?
        AND archived = 0
        GROUP BY status
      `).all(depStreamId);

      const total = depStreamTasks.reduce((sum, row) => sum + row.count, 0);
      const completed = depStreamTasks.find(row => row.status === 'completed')?.count || 0;

      return completed === total && total > 0;
    });

    if (allDepsComplete) {
      potentiallyUnblockable++;
      unblockableTaskIds.push(task.id);
    }
  });

  console.log(`Potentially unblockable: ${potentiallyUnblockable} tasks`);

  if (unblockableTaskIds.length > 0) {
    console.log(`\nTasks that can potentially be unblocked:`);
    unblockableTaskIds.forEach(id => {
      const task = blockedTasks.find(t => t.id === id);
      console.log(`  - ${id}: ${task.title}`);
    });
  }

  console.log(`\nRecommendations:`);
  console.log(`  1. Review ${potentiallyUnblockable} tasks with resolved dependencies`);
  console.log(`  2. Update ${categorized.uncategorized.length} tasks with better blocker descriptions`);
  console.log(`  3. Check external blockers (${categorized.externalBlockers.length}) for status updates`);
  console.log(`  4. Consider breaking down large blocked tasks into smaller units`);

  console.log('\n' + '='.repeat(70));

  db.close();

} catch (error) {
  console.error('Error analyzing blocked tasks:', error);
  process.exit(1);
}
