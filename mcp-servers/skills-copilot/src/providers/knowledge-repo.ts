/**
 * Knowledge Repository Provider
 *
 * Handles loading and resolution of agent extensions from a knowledge repository.
 * Knowledge repositories can override or extend base agents with company-specific
 * methodologies and skills.
 */

import { readFileSync, existsSync } from 'fs';
import { join, resolve } from 'path';
import { homedir } from 'os';
import type {
  KnowledgeManifest,
  ExtensionDeclaration,
  ResolvedExtension,
  ExtensionListItem,
  KnowledgeRepoStatus,
  FallbackBehavior
} from '../types.js';

export class KnowledgeRepoProvider {
  private repoPath: string | null = null;
  private manifest: KnowledgeManifest | null = null;
  private loadError: string | null = null;

  constructor(repoPath?: string) {
    if (repoPath) {
      this.setRepoPath(repoPath);
    }
  }

  /**
   * Set the knowledge repository path and load the manifest
   */
  setRepoPath(repoPath: string): void {
    // Expand ~ to home directory
    const expandedPath = repoPath.startsWith('~')
      ? join(homedir(), repoPath.slice(1))
      : repoPath;

    this.repoPath = resolve(expandedPath);
    this.manifest = null;
    this.loadError = null;

    this.loadManifest();
  }

  /**
   * Load the knowledge-manifest.json from the repository
   */
  private loadManifest(): void {
    if (!this.repoPath) {
      this.loadError = 'No repository path configured';
      return;
    }

    const manifestPath = join(this.repoPath, 'knowledge-manifest.json');

    if (!existsSync(manifestPath)) {
      this.loadError = `Manifest not found: ${manifestPath}`;
      return;
    }

    try {
      const content = readFileSync(manifestPath, 'utf-8');
      this.manifest = JSON.parse(content) as KnowledgeManifest;
    } catch (error) {
      this.loadError = error instanceof Error
        ? `Failed to parse manifest: ${error.message}`
        : 'Failed to parse manifest';
      this.manifest = null;
    }
  }

  /**
   * Check if the provider is properly configured
   */
  isConfigured(): boolean {
    return this.repoPath !== null;
  }

  /**
   * Check if manifest loaded successfully
   */
  isLoaded(): boolean {
    return this.manifest !== null;
  }

  /**
   * Get status of the knowledge repository
   */
  getStatus(): KnowledgeRepoStatus {
    if (!this.repoPath) {
      return {
        configured: false,
        error: 'KNOWLEDGE_REPO_PATH not set'
      };
    }

    if (!this.manifest) {
      return {
        configured: true,
        path: this.repoPath,
        error: this.loadError || 'Manifest not loaded'
      };
    }

    const extensionCount = this.manifest.extensions?.length || 0;
    const skillCount = (this.manifest.skills?.local?.length || 0) +
                       (this.manifest.skills?.remote?.length || 0);

    return {
      configured: true,
      path: this.repoPath,
      manifest: {
        name: this.manifest.name,
        description: this.manifest.description,
        extensions: extensionCount,
        skills: skillCount
      }
    };
  }

  /**
   * List all available extensions
   */
  listExtensions(): ExtensionListItem[] {
    if (!this.manifest?.extensions) {
      return [];
    }

    return this.manifest.extensions.map(ext => ({
      agent: ext.agent,
      type: ext.type,
      description: ext.description,
      requiredSkills: ext.requiredSkills,
      fallbackBehavior: ext.fallbackBehavior
    }));
  }

  /**
   * Get extension for a specific agent
   */
  getExtension(agentId: string): ResolvedExtension | null {
    if (!this.manifest?.extensions || !this.repoPath) {
      return null;
    }

    const declaration = this.manifest.extensions.find(
      ext => ext.agent === agentId
    );

    if (!declaration) {
      return null;
    }

    return this.resolveExtension(declaration);
  }

  /**
   * Resolve an extension declaration by loading its file content
   */
  private resolveExtension(declaration: ExtensionDeclaration): ResolvedExtension | null {
    if (!this.repoPath) {
      return null;
    }

    const extensionPath = join(this.repoPath, declaration.file);

    if (!existsSync(extensionPath)) {
      console.error(`Extension file not found: ${extensionPath}`);
      return null;
    }

    try {
      const content = readFileSync(extensionPath, 'utf-8');

      return {
        agent: declaration.agent,
        type: declaration.type,
        content,
        description: declaration.description,
        requiredSkills: declaration.requiredSkills || [],
        fallbackBehavior: declaration.fallbackBehavior || 'use_base_with_warning'
      };
    } catch (error) {
      console.error(`Failed to read extension file ${extensionPath}:`, error);
      return null;
    }
  }

  /**
   * Check if all required skills are available
   * Returns list of missing skills
   */
  checkRequiredSkills(
    requiredSkills: string[],
    availableSkills: Set<string>
  ): string[] {
    return requiredSkills.filter(skill => !availableSkills.has(skill));
  }

  /**
   * Get the manifest (for advanced use cases)
   */
  getManifest(): KnowledgeManifest | null {
    return this.manifest;
  }

  /**
   * Get skills declared in the manifest
   */
  getManifestSkills(): Array<{ name: string; path: string; description?: string }> {
    if (!this.manifest?.skills?.local) {
      return [];
    }

    return this.manifest.skills.local.map(skill => ({
      name: skill.name,
      path: skill.path,
      description: skill.description
    }));
  }

  /**
   * Reload the manifest from disk
   */
  refresh(): void {
    this.manifest = null;
    this.loadError = null;
    this.loadManifest();
  }

  /**
   * Get the glossary path if configured
   */
  getGlossaryPath(): string | null {
    if (!this.manifest?.glossary || !this.repoPath) {
      return null;
    }

    const glossaryPath = join(this.repoPath, this.manifest.glossary);
    return existsSync(glossaryPath) ? glossaryPath : null;
  }

  /**
   * Get repository configuration
   */
  getConfig(): KnowledgeManifest['config'] | null {
    return this.manifest?.config || null;
  }
}
