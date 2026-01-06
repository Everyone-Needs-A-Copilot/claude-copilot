/**
 * Initiative integration tool implementations
 */

import { v4 as uuidv4 } from 'uuid';
import { existsSync, mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import type { DatabaseClient } from '../database.js';
import type {
  InitiativeLinkInput,
  InitiativeLinkOutput,
  InitiativeArchiveInput,
  InitiativeArchiveOutput,
  InitiativeWipeInput,
  InitiativeWipeOutput,
  ProgressSummaryInput,
  ProgressSummaryOutput,
  Milestone,
  MilestoneProgress,
  VelocityTrend,
  PrdMetadata,
} from '../types.js';
import { renderProgressBar } from '../utils/progress-bar.js';

/**
 * Link current initiative from Memory Copilot to Task Copilot workspace
 * Auto-archives streams from previous initiative when switching
 */
export function initiativeLink(
  db: DatabaseClient,
  input: InitiativeLinkInput
): InitiativeLinkOutput {
  const now = new Date().toISOString();

  // Get current initiative before linking new one
  const currentInitiative = db.getCurrentInitiative();

  // Check if initiative already exists
  const existing = db.getInitiative(input.initiativeId);
  const workspaceCreated = !existing;

  // Auto-archive streams if switching to a different initiative
  let archivedStreamsCount = 0;
  if (currentInitiative && currentInitiative.id !== input.initiativeId) {
    archivedStreamsCount = db.archiveStreamsForInitiative(
      currentInitiative.id,
      input.initiativeId
    );

    if (archivedStreamsCount > 0) {
      // Log stream archival activity
      db.insertActivity({
        id: uuidv4(),
        initiative_id: currentInitiative.id,
        type: 'streams_auto_archived',
        entity_id: currentInitiative.id,
        summary: `Auto-archived ${archivedStreamsCount} stream tasks due to initiative switch to ${input.initiativeId}`,
        created_at: now
      });
    }
  }

  // Upsert the initiative
  db.upsertInitiative({
    id: input.initiativeId,
    title: input.title,
    description: input.description || null,
    created_at: existing?.created_at || now,
    updated_at: now
  });

  // Log activity
  db.insertActivity({
    id: uuidv4(),
    initiative_id: input.initiativeId,
    type: workspaceCreated ? 'initiative_created' : 'initiative_updated',
    entity_id: input.initiativeId,
    summary: workspaceCreated
      ? `Linked initiative: ${input.title}`
      : `Updated initiative: ${input.title}`,
    created_at: now
  });

  return {
    initiativeId: input.initiativeId,
    workspaceCreated,
    dbPath: db.getWorkspaceId(),
    archivedStreamsCount
  };
}

/**
 * Archive all task data for an initiative to a JSON file
 */
export function initiativeArchive(
  db: DatabaseClient,
  input: InitiativeArchiveInput
): InitiativeArchiveOutput {
  // Get initiative
  const initiative = input.initiativeId
    ? db.getInitiative(input.initiativeId)
    : db.getCurrentInitiative();

  if (!initiative) {
    throw new Error('No initiative found to archive');
  }

  // Fetch all data
  const prds = db.listPrds({ initiativeId: initiative.id });
  const allTasks = db.listTasks({});
  const allWorkProducts: any[] = [];
  const allActivityLogs = db.listActivityLogs(initiative.id);

  // Get work products for all tasks
  for (const task of allTasks) {
    const workProducts = db.listWorkProducts(task.id);
    allWorkProducts.push(...workProducts);
  }

  // Create archive data
  const archiveData = {
    version: '1.0',
    archivedAt: new Date().toISOString(),
    initiative: {
      id: initiative.id,
      title: initiative.title,
      description: initiative.description
    },
    prds: prds.map(prd => ({
      id: prd.id,
      initiativeId: prd.initiative_id,
      title: prd.title,
      description: prd.description,
      content: prd.content,
      metadata: JSON.parse(prd.metadata),
      status: prd.status,
      createdAt: prd.created_at,
      updatedAt: prd.updated_at
    })),
    tasks: allTasks.map(task => ({
      id: task.id,
      prdId: task.prd_id,
      parentId: task.parent_id,
      title: task.title,
      description: task.description,
      assignedAgent: task.assigned_agent,
      status: task.status,
      blockedReason: task.blocked_reason,
      notes: task.notes,
      metadata: JSON.parse(task.metadata),
      createdAt: task.created_at,
      updatedAt: task.updated_at
    })),
    workProducts: allWorkProducts.map(wp => ({
      id: wp.id,
      taskId: wp.task_id,
      type: wp.type,
      title: wp.title,
      content: wp.content,
      metadata: JSON.parse(wp.metadata),
      createdAt: wp.created_at
    })),
    activityLog: allActivityLogs.map(log => ({
      id: log.id,
      initiativeId: log.initiative_id,
      type: log.type,
      entityId: log.entity_id,
      summary: log.summary,
      createdAt: log.created_at
    }))
  };

  // Determine archive path
  const archivePath = input.archivePath || (() => {
    const archiveDir = join(homedir(), '.claude', 'archives');
    if (!existsSync(archiveDir)) {
      mkdirSync(archiveDir, { recursive: true });
    }
    const timestamp = new Date().toISOString().replace(/:/g, '-').split('.')[0];
    return join(archiveDir, `${initiative.id}_${timestamp}.json`);
  })();

  // Ensure archive directory exists
  const archiveDir = archivePath.substring(0, archivePath.lastIndexOf('/'));
  if (!existsSync(archiveDir)) {
    mkdirSync(archiveDir, { recursive: true });
  }

  // Write archive file
  writeFileSync(archivePath, JSON.stringify(archiveData, null, 2), 'utf-8');

  // Log activity
  db.insertActivity({
    id: uuidv4(),
    initiative_id: initiative.id,
    type: 'initiative_archived',
    entity_id: initiative.id,
    summary: `Archived initiative to: ${archivePath}`,
    created_at: new Date().toISOString()
  });

  return {
    initiativeId: initiative.id,
    archivePath,
    prdCount: prds.length,
    taskCount: allTasks.length,
    workProductCount: allWorkProducts.length,
    archivedAt: archiveData.archivedAt
  };
}

/**
 * Delete all task data for an initiative (fresh start)
 */
export function initiativeWipe(
  db: DatabaseClient,
  input: InitiativeWipeInput
): InitiativeWipeOutput {
  // Safety check
  if (!input.confirm) {
    throw new Error('Wipe operation requires confirm: true');
  }

  // Get initiative
  const initiative = input.initiativeId
    ? db.getInitiative(input.initiativeId)
    : db.getCurrentInitiative();

  if (!initiative) {
    throw new Error('No initiative found to wipe');
  }

  // Delete all data for this initiative
  const deletedCounts = db.wipeInitiativeData(initiative.id);

  // Log activity
  db.insertActivity({
    id: uuidv4(),
    initiative_id: initiative.id,
    type: 'initiative_wiped',
    entity_id: initiative.id,
    summary: `Wiped all data for initiative: ${initiative.title}`,
    created_at: new Date().toISOString()
  });

  return {
    initiativeId: initiative.id,
    deletedPrds: deletedCounts.prds,
    deletedTasks: deletedCounts.tasks,
    deletedWorkProducts: deletedCounts.workProducts,
    deletedActivityLogs: deletedCounts.activityLogs
  };
}

/**
 * Calculate milestone progress for PRDs
 */
function calculateMilestoneProgress(
  milestones: Milestone[],
  allTasks: any[]
): MilestoneProgress[] {
  const taskStatusMap = new Map(allTasks.map(t => [t.id, t.status]));

  return milestones.map(milestone => {
    const totalTasks = milestone.taskIds.length;
    const completedTasks = milestone.taskIds.filter(
      taskId => taskStatusMap.get(taskId) === 'completed'
    ).length;

    const percentComplete = totalTasks > 0
      ? Math.floor((completedTasks / totalTasks) * 100)
      : 0;

    return {
      id: milestone.id,
      name: milestone.name,
      description: milestone.description,
      totalTasks,
      completedTasks,
      percentComplete,
      isComplete: completedTasks === totalTasks && totalTasks > 0
    };
  });
}

/**
 * Calculate velocity trends over different time periods
 */
function calculateVelocityTrends(db: DatabaseClient, initiativeId: string): VelocityTrend[] {
  const now = new Date();
  const periods: Array<{ days: number; label: '7d' | '14d' | '30d' }> = [
    { days: 7, label: '7d' },
    { days: 14, label: '14d' },
    { days: 30, label: '30d' }
  ];

  const trends: VelocityTrend[] = [];

  for (const period of periods) {
    const startDate = new Date(now);
    startDate.setDate(startDate.getDate() - period.days);
    const startDateISO = startDate.toISOString();

    // Query completed tasks within period
    const completedTasks = db.getCompletedTasksInPeriod(startDateISO, now.toISOString());
    const tasksCompleted = completedTasks.length;
    const tasksPerDay = tasksCompleted / period.days;

    // Calculate trend by comparing first half vs second half
    let trend: 'improving' | 'stable' | 'declining' | 'insufficient_data' = 'insufficient_data';

    if (tasksCompleted >= 4) { // Need at least 4 tasks for meaningful trend
      const midDate = new Date(startDate);
      midDate.setDate(midDate.getDate() + Math.floor(period.days / 2));
      const midDateISO = midDate.toISOString();

      const firstHalfCount = completedTasks.filter(
        t => t.updated_at < midDateISO
      ).length;
      const secondHalfCount = tasksCompleted - firstHalfCount;

      const firstHalfRate = firstHalfCount / (period.days / 2);
      const secondHalfRate = secondHalfCount / (period.days / 2);

      // 20% threshold for trend detection
      const changePercent = firstHalfRate > 0
        ? (secondHalfRate - firstHalfRate) / firstHalfRate
        : (secondHalfCount > 0 ? 1 : 0);

      if (changePercent > 0.2) {
        trend = 'improving';
      } else if (changePercent < -0.2) {
        trend = 'declining';
      } else {
        trend = 'stable';
      }
    }

    trends.push({
      period: period.label,
      tasksCompleted,
      tasksPerDay: Math.round(tasksPerDay * 100) / 100,
      trend
    });
  }

  return trends;
}

/**
 * Get high-level progress summary for initiative
 * Enhanced with milestones, progress bars, and velocity tracking
 */
export function progressSummary(
  db: DatabaseClient,
  input: ProgressSummaryInput
): ProgressSummaryOutput {
  // Get initiative
  const initiative = input.initiativeId
    ? db.getInitiative(input.initiativeId)
    : db.getCurrentInitiative();

  if (!initiative) {
    throw new Error('No initiative found');
  }

  // Get PRD stats
  const prds = db.listPrds({ initiativeId: initiative.id });
  const activePrds = prds.filter(p => p.status === 'active');
  const completedPrds = prds.filter(p => p.status === 'archived');

  // Get task stats
  const allTasks = db.listTasks({});
  const tasksByStatus = {
    pending: allTasks.filter(t => t.status === 'pending').length,
    inProgress: allTasks.filter(t => t.status === 'in_progress').length,
    completed: allTasks.filter(t => t.status === 'completed').length,
    blocked: allTasks.filter(t => t.status === 'blocked').length
  };

  // Get work product stats
  const workProductsByType: Record<string, number> = {};
  let totalWorkProducts = 0;

  for (const task of allTasks) {
    const workProducts = db.listWorkProducts(task.id);
    totalWorkProducts += workProducts.length;

    for (const wp of workProducts) {
      workProductsByType[wp.type] = (workProductsByType[wp.type] || 0) + 1;
    }
  }

  // Calculate milestone progress from all active PRDs
  let allMilestones: MilestoneProgress[] = [];
  for (const prd of activePrds) {
    const metadata = JSON.parse(prd.metadata) as PrdMetadata;
    if (metadata.milestones && metadata.milestones.length > 0) {
      const milestoneProgress = calculateMilestoneProgress(metadata.milestones, allTasks);
      allMilestones = allMilestones.concat(milestoneProgress);
    }
  }

  // Generate ASCII progress bar for tasks
  const progressBar = renderProgressBar(
    tasksByStatus.completed,
    allTasks.length,
    { width: 20, showPercentage: true, showCount: true }
  );

  // Calculate velocity trends
  const velocity = calculateVelocityTrends(db, initiative.id);

  // Get recent activity (last 5 items)
  const recentActivity = db.listActivityLogs(initiative.id, 5).map(log => ({
    timestamp: log.created_at,
    type: log.type,
    summary: log.summary
  }));

  return {
    initiativeId: initiative.id,
    title: initiative.title,
    prds: {
      total: prds.length,
      active: activePrds.length,
      completed: completedPrds.length
    },
    tasks: {
      total: allTasks.length,
      pending: tasksByStatus.pending,
      inProgress: tasksByStatus.inProgress,
      completed: tasksByStatus.completed,
      blocked: tasksByStatus.blocked,
      progressBar
    },
    workProducts: {
      total: totalWorkProducts,
      byType: workProductsByType
    },
    milestones: allMilestones.length > 0 ? allMilestones : undefined,
    velocity,
    recentActivity
  };
}
