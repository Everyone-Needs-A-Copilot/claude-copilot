/**
 * Git Worktree Manager
 *
 * Provides utilities for managing git worktrees for parallel stream isolation.
 * Each parallel stream gets its own worktree with a dedicated branch to eliminate file conflicts.
 *
 * ## Key Features
 *
 * - **Isolation**: Each stream works in a separate worktree
 * - **Auto-branching**: Branches created as `stream-{streamId}` (lowercase)
 * - **Cleanup**: Automatic cleanup on stream completion or manual command
 * - **Safe operations**: Validates git repository before worktree operations
 *
 * ## Example Usage
 *
 * ```typescript
 * const manager = new WorktreeManager('/project/root');
 *
 * // Create worktree for Stream-B
 * const worktree = await manager.createWorktree('Stream-B');
 * // Returns: { path: '.claude/worktrees/Stream-B', branch: 'stream-b' }
 *
 * // List all worktrees
 * const worktrees = await manager.listWorktrees();
 *
 * // Remove worktree
 * await manager.removeWorktree('Stream-B');
 * ```
 */

import { exec } from 'child_process';
import { promisify } from 'util';
import { existsSync, mkdirSync } from 'fs';
import { join, resolve } from 'path';

const execAsync = promisify(exec);

export interface WorktreeInfo {
  path: string;
  branch: string;
  streamId: string;
}

export class WorktreeManager {
  private projectRoot: string;
  private worktreeBaseDir: string;

  constructor(projectRoot: string) {
    this.projectRoot = resolve(projectRoot);
    this.worktreeBaseDir = join(this.projectRoot, '.claude', 'worktrees');
  }

  /**
   * Check if current directory is a git repository
   */
  private async isGitRepo(): Promise<boolean> {
    try {
      await execAsync('git rev-parse --git-dir', { cwd: this.projectRoot });
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Get current branch name
   */
  private async getCurrentBranch(): Promise<string> {
    try {
      const { stdout } = await execAsync('git rev-parse --abbrev-ref HEAD', { cwd: this.projectRoot });
      return stdout.trim();
    } catch (error) {
      throw new Error(`Failed to get current branch: ${error}`);
    }
  }

  /**
   * Convert streamId to branch name (lowercase)
   * Stream-A → stream-a
   * Stream-B → stream-b
   */
  private streamIdToBranch(streamId: string): string {
    return streamId.toLowerCase();
  }

  /**
   * Get worktree path for a stream
   */
  private getWorktreePath(streamId: string): string {
    return join(this.worktreeBaseDir, streamId);
  }

  /**
   * Ensure worktree base directory exists
   */
  private ensureWorktreeBaseDir(): void {
    if (!existsSync(this.worktreeBaseDir)) {
      mkdirSync(this.worktreeBaseDir, { recursive: true });
    }
  }

  /**
   * Create a worktree for a stream
   *
   * @param streamId - Stream identifier (e.g., "Stream-B")
   * @param baseBranch - Optional base branch to branch from (defaults to current branch)
   * @returns WorktreeInfo with path and branch name
   */
  async createWorktree(streamId: string, baseBranch?: string): Promise<WorktreeInfo> {
    // Validate git repo
    if (!(await this.isGitRepo())) {
      throw new Error('Not a git repository');
    }

    const branchName = this.streamIdToBranch(streamId);
    const worktreePath = this.getWorktreePath(streamId);

    // Check if worktree already exists
    if (existsSync(worktreePath)) {
      // Worktree already exists, return existing info
      return {
        path: worktreePath,
        branch: branchName,
        streamId
      };
    }

    // Ensure base directory exists
    this.ensureWorktreeBaseDir();

    // Get base branch if not provided
    const base = baseBranch || (await this.getCurrentBranch());

    try {
      // Create worktree with new branch
      await execAsync(
        `git worktree add "${worktreePath}" -b ${branchName} ${base}`,
        { cwd: this.projectRoot }
      );

      return {
        path: worktreePath,
        branch: branchName,
        streamId
      };
    } catch (error) {
      throw new Error(`Failed to create worktree for ${streamId}: ${error}`);
    }
  }

  /**
   * Remove a worktree for a stream
   *
   * @param streamId - Stream identifier
   * @param force - Force removal even if dirty
   */
  async removeWorktree(streamId: string, force: boolean = false): Promise<void> {
    const worktreePath = this.getWorktreePath(streamId);

    if (!existsSync(worktreePath)) {
      // Worktree doesn't exist, nothing to do
      return;
    }

    try {
      const forceFlag = force ? '--force' : '';
      await execAsync(
        `git worktree remove ${forceFlag} "${worktreePath}"`,
        { cwd: this.projectRoot }
      );
    } catch (error) {
      throw new Error(`Failed to remove worktree for ${streamId}: ${error}`);
    }
  }

  /**
   * List all worktrees managed by Task Copilot
   */
  async listWorktrees(): Promise<WorktreeInfo[]> {
    if (!(await this.isGitRepo())) {
      return [];
    }

    try {
      const { stdout } = await execAsync('git worktree list --porcelain', { cwd: this.projectRoot });

      const worktrees: WorktreeInfo[] = [];
      const lines = stdout.split('\n');

      let currentWorktree: Partial<WorktreeInfo> = {};

      for (const line of lines) {
        if (line.startsWith('worktree ')) {
          const path = line.substring('worktree '.length);

          // Only include worktrees in our managed directory
          if (path.includes('.claude/worktrees/')) {
            currentWorktree.path = path;

            // Extract streamId from path
            const parts = path.split('/');
            const streamId = parts[parts.length - 1];
            currentWorktree.streamId = streamId;
          } else {
            currentWorktree = {};
          }
        } else if (line.startsWith('branch ') && currentWorktree.path) {
          const branch = line.substring('branch refs/heads/'.length);
          currentWorktree.branch = branch;

          // Complete worktree info
          if (currentWorktree.path && currentWorktree.branch && currentWorktree.streamId) {
            worktrees.push(currentWorktree as WorktreeInfo);
          }
          currentWorktree = {};
        }
      }

      return worktrees;
    } catch (error) {
      throw new Error(`Failed to list worktrees: ${error}`);
    }
  }

  /**
   * Prune stale worktree references
   */
  async pruneWorktrees(): Promise<void> {
    if (!(await this.isGitRepo())) {
      return;
    }

    try {
      await execAsync('git worktree prune', { cwd: this.projectRoot });
    } catch (error) {
      throw new Error(`Failed to prune worktrees: ${error}`);
    }
  }

  /**
   * Check if a worktree exists for a stream
   */
  async hasWorktree(streamId: string): Promise<boolean> {
    const worktreePath = this.getWorktreePath(streamId);
    return existsSync(worktreePath);
  }

  /**
   * Get worktree info for a stream
   */
  async getWorktreeInfo(streamId: string): Promise<WorktreeInfo | null> {
    const worktreePath = this.getWorktreePath(streamId);

    if (!existsSync(worktreePath)) {
      return null;
    }

    return {
      path: worktreePath,
      branch: this.streamIdToBranch(streamId),
      streamId
    };
  }

  /**
   * Merge a stream branch into target branch
   *
   * @param streamId - Stream identifier
   * @param targetBranch - Target branch to merge into (defaults to main/master)
   * @returns Merge result message
   */
  async mergeStreamBranch(streamId: string, targetBranch?: string): Promise<string> {
    if (!(await this.isGitRepo())) {
      throw new Error('Not a git repository');
    }

    const branchName = this.streamIdToBranch(streamId);
    const target = targetBranch || 'main';

    try {
      // Checkout target branch
      await execAsync(`git checkout ${target}`, { cwd: this.projectRoot });

      // Merge stream branch
      const { stdout } = await execAsync(
        `git merge ${branchName} --no-ff -m "Merge ${streamId} (${branchName})"`,
        { cwd: this.projectRoot }
      );

      return stdout;
    } catch (error) {
      throw new Error(`Failed to merge ${streamId} into ${target}: ${error}`);
    }
  }
}
