/**
 * Agent Performance Tracking tool implementations
 */

import type { DatabaseClient } from '../database.js';
import type {
  AgentPerformanceGetInput,
  AgentPerformanceGetOutput,
  AgentPerformanceResult,
  AgentMetrics,
  PerformanceRow,
  IterationMetrics,
  CheckpointRow,
  IterationConfig,
  IterationHistoryEntry,
} from '../types.js';

/**
 * Get aggregated performance metrics for agents
 */
export function agentPerformanceGet(
  db: DatabaseClient,
  input: AgentPerformanceGetInput
): AgentPerformanceGetOutput {
  // Get raw performance records
  const records = db.getPerformanceRecords({
    agentId: input.agentId,
    workProductType: input.workProductType,
    complexity: input.complexity,
    sinceDays: input.sinceDays,
  });

  // Group by agent
  const agentMap = new Map<string, PerformanceRow[]>();
  for (const record of records) {
    const existing = agentMap.get(record.agent_id) || [];
    existing.push(record);
    agentMap.set(record.agent_id, existing);
  }

  // Calculate metrics for each agent
  const agents: AgentPerformanceResult[] = [];
  for (const [agentId, agentRecords] of agentMap) {
    const agentResult = calculateAgentMetrics(agentId, agentRecords);

    // Add iteration metrics if available
    const iterationMetrics = calculateIterationMetrics(db, agentId, input.sinceDays);
    if (iterationMetrics.totalIterationSessions > 0) {
      agentResult.iterationMetrics = iterationMetrics;
    }

    agents.push(agentResult);
  }

  // Sort by success rate descending
  agents.sort((a, b) => b.metrics.successRate - a.metrics.successRate);

  // Get summary stats
  const stats = db.getPerformanceStats();

  return {
    agents,
    summary: {
      totalRecords: stats.totalRecords,
      periodStart: stats.oldestRecord,
      periodEnd: stats.newestRecord,
    },
  };
}

/**
 * Calculate aggregated metrics for a single agent
 */
function calculateAgentMetrics(
  agentId: string,
  records: PerformanceRow[]
): AgentPerformanceResult {
  // Count outcomes
  const outcomes = {
    success: 0,
    failure: 0,
    blocked: 0,
    reassigned: 0,
  };

  for (const record of records) {
    const outcome = record.outcome as keyof typeof outcomes;
    if (outcome in outcomes) {
      outcomes[outcome]++;
    }
  }

  const total = records.length;
  const successRate = total > 0 ? outcomes.success / total : 0;
  const completionRate = total > 0
    ? outcomes.success / (outcomes.success + outcomes.failure + outcomes.blocked)
    : 0;

  const metrics: AgentMetrics = {
    total,
    success: outcomes.success,
    failure: outcomes.failure,
    blocked: outcomes.blocked,
    reassigned: outcomes.reassigned,
    successRate: Math.round(successRate * 100) / 100,
    completionRate: Math.round(completionRate * 100) / 100,
  };

  // Group by work product type
  const byType: Record<string, { total: number; successRate: number }> = {};
  const typeGroups = groupBy(records, r => r.work_product_type || 'unknown');
  for (const [type, typeRecords] of Object.entries(typeGroups)) {
    const typeSuccess = typeRecords.filter(r => r.outcome === 'success').length;
    byType[type] = {
      total: typeRecords.length,
      successRate: Math.round((typeSuccess / typeRecords.length) * 100) / 100,
    };
  }

  // Group by complexity
  const byComplexity: Record<string, { total: number; successRate: number }> = {};
  const complexityGroups = groupBy(records, r => r.complexity || 'unknown');
  for (const [complexity, complexityRecords] of Object.entries(complexityGroups)) {
    const complexitySuccess = complexityRecords.filter(r => r.outcome === 'success').length;
    byComplexity[complexity] = {
      total: complexityRecords.length,
      successRate: Math.round((complexitySuccess / complexityRecords.length) * 100) / 100,
    };
  }

  // Calculate trend (compare last 5 vs previous 5)
  const recentTrend = calculateTrend(records);

  return {
    agentId,
    metrics,
    byType,
    byComplexity,
    recentTrend,
  };
}

/**
 * Calculate performance trend based on recent records
 */
function calculateTrend(
  records: PerformanceRow[]
): 'improving' | 'stable' | 'declining' | 'insufficient_data' {
  if (records.length < 10) {
    return 'insufficient_data';
  }

  // Sort by date (newest first - they should already be sorted but ensure)
  const sorted = [...records].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  // Take last 5 and previous 5
  const recent = sorted.slice(0, 5);
  const previous = sorted.slice(5, 10);

  const recentSuccessRate = recent.filter(r => r.outcome === 'success').length / recent.length;
  const previousSuccessRate = previous.filter(r => r.outcome === 'success').length / previous.length;

  const diff = recentSuccessRate - previousSuccessRate;

  if (diff > 0.1) return 'improving';
  if (diff < -0.1) return 'declining';
  return 'stable';
}

/**
 * Group array elements by a key function
 */
function groupBy<T>(items: T[], keyFn: (item: T) => string): Record<string, T[]> {
  const groups: Record<string, T[]> = {};
  for (const item of items) {
    const key = keyFn(item);
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(item);
  }
  return groups;
}

/**
 * Calculate iteration-specific metrics for an agent
 */
function calculateIterationMetrics(
  db: DatabaseClient,
  agentId: string,
  sinceDays?: number
): IterationMetrics {
  // Get iteration checkpoints for this agent
  const checkpoints = db.getIterationCheckpoints({
    agentId,
    sinceDays
  });

  // Get overall iteration stats
  const stats = db.getIterationStats(agentId, sinceDays);

  // Initialize metrics
  const metrics: IterationMetrics = {
    averageIterationsToCompletion: 0,
    successRateByIterationCount: {},
    safetyGuardTriggers: {
      maxIterations: 0,
      circuitBreaker: 0,
      qualityRegression: 0,
      thrashing: 0
    },
    iterationCompletionRate: 0,
    totalIterationSessions: stats.totalSessions,
    totalIterationsRun: stats.totalIterations,
    averageDurationPerIteration: null
  };

  if (checkpoints.length === 0) {
    return metrics;
  }

  // Calculate average iterations to completion
  metrics.averageIterationsToCompletion = stats.avgIterationsPerSession;

  // Calculate iteration completion rate
  metrics.iterationCompletionRate = stats.totalSessions > 0
    ? stats.completedSessions / stats.totalSessions
    : 0;

  // Analyze success rate by iteration count
  const iterationCountMap = new Map<number, { total: number; success: number }>();

  for (const checkpoint of checkpoints) {
    const iterationNum = checkpoint.iteration_number;
    const task = db.getTask(checkpoint.task_id);

    if (!task) continue;

    const isSuccess = task.status === 'completed';
    const existing = iterationCountMap.get(iterationNum) || { total: 0, success: 0 };
    existing.total++;
    if (isSuccess) {
      existing.success++;
    }
    iterationCountMap.set(iterationNum, existing);
  }

  // Convert to success rate map
  for (const [count, data] of iterationCountMap) {
    metrics.successRateByIterationCount[count] = data.total > 0
      ? Math.round((data.success / data.total) * 100) / 100
      : 0;
  }

  // Analyze safety guard triggers
  for (const checkpoint of checkpoints) {
    if (!checkpoint.iteration_config) continue;

    try {
      const config: IterationConfig = JSON.parse(checkpoint.iteration_config);
      const task = db.getTask(checkpoint.task_id);

      if (!task) continue;

      // Check if max iterations was reached
      if (checkpoint.iteration_number >= config.maxIterations) {
        metrics.safetyGuardTriggers.maxIterations++;
      }

      // Analyze iteration history for circuit breaker and other patterns
      if (checkpoint.iteration_history) {
        const history: IterationHistoryEntry[] = JSON.parse(checkpoint.iteration_history);

        // Circuit breaker: consecutive failures
        let consecutiveFailures = 0;
        let maxConsecutiveFailures = 0;
        for (const entry of history) {
          if (!entry.validationResult?.passed) {
            consecutiveFailures++;
            maxConsecutiveFailures = Math.max(maxConsecutiveFailures, consecutiveFailures);
          } else {
            consecutiveFailures = 0;
          }
        }

        const threshold = config.circuitBreakerThreshold || 3;
        if (maxConsecutiveFailures >= threshold) {
          metrics.safetyGuardTriggers.circuitBreaker++;
        }

        // Quality regression: later iterations fail after earlier success
        const hadSuccess = history.some(e => e.validationResult?.passed);
        const latestFailed = history.length > 0 && !history[history.length - 1]?.validationResult?.passed;
        if (hadSuccess && latestFailed && history.length >= 3) {
          metrics.safetyGuardTriggers.qualityRegression++;
        }

        // Thrashing: alternating pass/fail pattern (at least 4 iterations)
        if (history.length >= 4) {
          let alternations = 0;
          for (let i = 1; i < history.length; i++) {
            const prev = history[i - 1].validationResult?.passed;
            const curr = history[i].validationResult?.passed;
            if (prev !== curr) {
              alternations++;
            }
          }
          // If more than 50% of transitions are alternations, consider it thrashing
          if (alternations / (history.length - 1) > 0.5) {
            metrics.safetyGuardTriggers.thrashing++;
          }
        }
      }
    } catch (error) {
      // Skip checkpoints with invalid JSON
      continue;
    }
  }

  // Calculate average duration per iteration (if timing data available)
  // Note: This requires checkpoint timestamps to be available
  const durationsMs: number[] = [];
  const checkpointsByTask = new Map<string, CheckpointRow[]>();

  for (const checkpoint of checkpoints) {
    const existing = checkpointsByTask.get(checkpoint.task_id) || [];
    existing.push(checkpoint);
    checkpointsByTask.set(checkpoint.task_id, existing);
  }

  for (const taskCheckpoints of checkpointsByTask.values()) {
    // Sort by iteration number
    taskCheckpoints.sort((a, b) => a.iteration_number - b.iteration_number);

    for (let i = 1; i < taskCheckpoints.length; i++) {
      const prev = taskCheckpoints[i - 1];
      const curr = taskCheckpoints[i];

      const prevTime = new Date(prev.created_at).getTime();
      const currTime = new Date(curr.created_at).getTime();
      const durationMs = currTime - prevTime;

      // Only include reasonable durations (between 1 second and 1 hour)
      if (durationMs > 1000 && durationMs < 3600000) {
        durationsMs.push(durationMs);
      }
    }
  }

  if (durationsMs.length > 0) {
    const avgMs = durationsMs.reduce((sum, d) => sum + d, 0) / durationsMs.length;
    metrics.averageDurationPerIteration = Math.round(avgMs);
  }

  return metrics;
}
