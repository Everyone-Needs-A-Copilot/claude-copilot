/**
 * Stream HTTP Routes
 *
 * Endpoints for querying stream state and tasks.
 */

import type { FastifyPluginAsync } from 'fastify';
import type { DatabaseClient } from '../database.js';
import { streamList, streamGet } from '../tools/stream.js';
import { checkpointCreate } from '../tools/checkpoint.js';
import type { CheckpointTrigger } from '../types.js';

interface StreamsRouteOptions {
  db: DatabaseClient;
}

export const streamsRoutes: FastifyPluginAsync<StreamsRouteOptions> = async (
  fastify,
  options
) => {
  const { db } = options;

  // GET /api/streams - List all streams
  fastify.get<{
    Querystring: {
      initiativeId?: string;
      includeArchived?: string;
    };
  }>('/', async (request, reply) => {
    const { initiativeId, includeArchived } = request.query;

    const result = streamList(db, {
      initiativeId,
      includeArchived: includeArchived === 'true'
    });

    // Add progress percentage to each stream
    const streamsWithProgress = result.streams.map(stream => ({
      ...stream,
      progressPercentage:
        stream.totalTasks > 0
          ? Math.round((stream.completedTasks / stream.totalTasks) * 100)
          : 0
    }));

    return {
      streams: streamsWithProgress,
      totalStreams: streamsWithProgress.length
    };
  });

  // GET /api/streams/:streamId - Get specific stream with tasks
  fastify.get<{
    Params: {
      streamId: string;
    };
    Querystring: {
      includeArchived?: string;
    };
  }>('/:streamId', async (request, reply) => {
    const { streamId } = request.params;
    const { includeArchived } = request.query;

    const stream = streamGet(db, {
      streamId,
      includeArchived: includeArchived === 'true'
    });

    if (!stream) {
      return reply.status(404).send({
        error: 'Stream not found',
        streamId
      });
    }

    // Add progress percentage
    const progressPercentage =
      stream.tasks.length > 0
        ? Math.round(
            (stream.tasks.filter(t => t.status === 'completed').length /
              stream.tasks.length) *
              100
          )
        : 0;

    return {
      ...stream,
      progressPercentage
    };
  });

  // GET /api/streams/:streamId/health - Check stream health for context exhaustion detection
  fastify.get<{
    Params: {
      streamId: string;
    };
  }>('/:streamId/health', async (request, reply) => {
    const { streamId } = request.params;

    // Get all tasks in stream (filter by metadata.streamId)
    const allTasks = db.listTasks({ status: undefined });
    const streamTasks = allTasks.filter(t => {
      try {
        const metadata = JSON.parse(t.metadata);
        return metadata.streamId === streamId;
      } catch {
        return false;
      }
    });

    if (streamTasks.length === 0) {
      return reply.status(404).send({
        error: 'Stream not found',
        streamId
      });
    }

    // Find in-progress task
    const inProgressTask = streamTasks.find(t => t.status === 'in_progress');

    // Get most recent activity for stream
    const activities = db.getActivitiesByStream(streamId, 1);
    const lastActivity = activities[0]?.created_at || null;

    // Get most recent checkpoint for any task in stream
    const latestCheckpoint = db.getLatestCheckpointForStream(streamId);

    // Calculate health
    const now = new Date();
    const timeSinceActivity = lastActivity
      ? (now.getTime() - new Date(lastActivity).getTime()) / 1000
      : Infinity;
    const timeSinceCheckpoint = latestCheckpoint
      ? (now.getTime() - new Date(latestCheckpoint.created_at).getTime()) / 1000
      : Infinity;

    const warnings: string[] = [];
    let healthy = true;

    // Warning: No checkpoint in 10+ minutes
    if (timeSinceCheckpoint > 600) {
      warnings.push('No checkpoint in 10+ minutes');
    }

    // Unhealthy: Task in_progress but no activity for 10+ minutes
    if (inProgressTask && timeSinceActivity > 600) {
      warnings.push('Task in_progress but no activity for 10+ minutes');
      healthy = false;
    }

    return {
      streamId,
      healthy,
      currentTask: inProgressTask?.id || null,
      taskStatus: inProgressTask?.status || null,
      lastActivity,
      lastCheckpoint: latestCheckpoint?.created_at || null,
      currentCheckpoint: latestCheckpoint?.id || null,
      timeSinceActivity: Math.round(timeSinceActivity),
      timeSinceCheckpoint: Math.round(timeSinceCheckpoint),
      warnings
    };
  });

  // POST /api/streams/:streamId/checkpoint - Trigger checkpoint creation for recovery
  fastify.post<{
    Params: {
      streamId: string;
    };
    Body: {
      trigger?: string;
      reason?: string;
    };
  }>('/:streamId/checkpoint', async (request, reply) => {
    const { streamId } = request.params;
    const { trigger = 'manual', reason } = request.body || {};

    // Find in-progress task for this stream
    const allTasks = db.listTasks({ status: 'in_progress' });
    const inProgressTask = allTasks.find(t => {
      try {
        const metadata = JSON.parse(t.metadata);
        return metadata.streamId === streamId;
      } catch {
        return false;
      }
    });

    if (!inProgressTask) {
      return reply.status(400).send({
        error: 'No in-progress task found for stream',
        streamId
      });
    }

    // Create checkpoint
    const checkpoint = checkpointCreate(db, {
      taskId: inProgressTask.id,
      trigger: trigger as CheckpointTrigger,
      agentContext: reason ? { recoveryReason: reason } : undefined
    });

    return reply.status(201).send({
      checkpointId: checkpoint.id,
      taskId: inProgressTask.id,
      createdAt: checkpoint.createdAt
    });
  });
};
