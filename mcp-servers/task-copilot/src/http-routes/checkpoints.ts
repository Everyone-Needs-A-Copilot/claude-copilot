/**
 * Checkpoint HTTP Routes
 *
 * Endpoints for checkpoint management and stream health checking.
 * Used by external orchestration scripts for context exhaustion recovery.
 */

import type { FastifyPluginAsync } from 'fastify';
import type { DatabaseClient } from '../database.js';

interface CheckpointsRouteOptions {
  db: DatabaseClient;
}

export const checkpointsRoutes: FastifyPluginAsync<CheckpointsRouteOptions> = async (
  fastify,
  options
) => {
  const { db } = options;

  // GET /api/checkpoints - Get latest checkpoint for stream or task
  fastify.get<{
    Querystring: {
      streamId?: string;
      taskId?: string;
      latest?: string;
    };
  }>('/', async (request, reply) => {
    const { streamId, taskId, latest } = request.query;

    if (!streamId && !taskId) {
      return reply.status(400).send({
        error: 'Must provide either streamId or taskId'
      });
    }

    let checkpoint;

    if (streamId) {
      checkpoint = db.getLatestCheckpointForStream(streamId);
      if (!checkpoint) {
        return reply.status(404).send({
          error: 'No checkpoint found for stream',
          streamId
        });
      }
    } else if (taskId) {
      checkpoint = db.getLatestCheckpoint(taskId);
      if (!checkpoint) {
        return reply.status(404).send({
          error: 'No checkpoint found for task',
          taskId
        });
      }
    }

    return {
      checkpointId: checkpoint!.id,
      taskId: checkpoint!.task_id,
      sequence: checkpoint!.sequence,
      createdAt: checkpoint!.created_at,
      trigger: checkpoint!.trigger,
      executionPhase: checkpoint!.execution_phase,
      executionStep: checkpoint!.execution_step
    };
  });
};
