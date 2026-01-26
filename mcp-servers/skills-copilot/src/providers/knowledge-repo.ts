/**
 * Knowledge Repository Provider
 *
 * Handles loading and resolution of agent extensions from knowledge repositories.
 * Supports two-tier resolution:
 *   1. Project-specific repository (highest priority) - via KNOWLEDGE_REPO_PATH
 *   2. Global repository (fallback) - ~/.claude/knowledge
 *
 * Knowledge repositories can override or extend base agents with company-specific
 * methodologies and skills.
 */

import { readFileSync, existsSync, readdirSync, statSync } from 'fs';
import { join, resolve, relative, basename, extname } from 'path';
import { homedir } from 'os';
import type {
  KnowledgeManifest,
  ExtensionDeclaration,
  ResolvedExtension,
  ExtensionListItem,
  ExtensionListItemWithSource,
  KnowledgeRepoStatus,
  KnowledgeRepoTierStatus,
  KnowledgeRepoConfig,
  FallbackBehavior,
  KnowledgeSearchResult,
  KnowledgeSearchOptions,
  KnowledgeExpectation,
  TeamMemberDetection,
  KnowledgeSignal
} from '../types.js';

/** Default global knowledge repository path */
const DEFAULT_GLOBAL_PATH = join(homedir(), '.claude', 'knowledge');

interface LoadedTier {
  path: string;
  manifest: KnowledgeManifest | null;
  error: string | null;
}

export class KnowledgeRepoProvider {
  private projectTier: LoadedTier | null = null;
  private globalTier: LoadedTier | null = null;

  // Legacy fields for backward compatibility
  private repoPath: string | null = null;
  private manifest: KnowledgeManifest | null = null;
  private loadError: string | null = null;

  /**
   * Create a KnowledgeRepoProvider
   * @param config - Either a KnowledgeRepoConfig object or a legacy string path
   */
  constructor(config?: KnowledgeRepoConfig | string) {
    if (typeof config === 'string') {
      // Legacy mode: single path (backward compatibility)
      this.setRepoPath(config);
    } else if (config) {
      // New mode: two-tier configuration
      this.initializeTwoTier(config);
    } else {
      // No config: try global only
      this.initializeTwoTier({});
    }
  }

  /**
   * Initialize two-tier knowledge repository support
   */
  private initializeTwoTier(config: KnowledgeRepoConfig): void {
    const globalPath = config.globalPath || DEFAULT_GLOBAL_PATH;

    // Load global tier (always attempt)
    this.globalTier = this.loadTier(globalPath);

    // Load project tier (only if specified)
    if (config.projectPath) {
      this.projectTier = this.loadTier(config.projectPath);
    }

    // For backward compatibility, set legacy fields to the highest priority tier
    if (this.projectTier?.manifest) {
      this.repoPath = this.projectTier.path;
      this.manifest = this.projectTier.manifest;
      this.loadError = null;
    } else if (this.globalTier?.manifest) {
      this.repoPath = this.globalTier.path;
      this.manifest = this.globalTier.manifest;
      this.loadError = null;
    } else {
      // Neither loaded successfully
      this.repoPath = config.projectPath || globalPath;
      this.manifest = null;
      this.loadError = this.projectTier?.error || this.globalTier?.error || 'No knowledge repository found';
    }
  }

  /**
   * Load a single tier (manifest from a path)
   */
  private loadTier(repoPath: string): LoadedTier {
    // Expand ~ to home directory
    const expandedPath = repoPath.startsWith('~')
      ? join(homedir(), repoPath.slice(1))
      : repoPath;

    const resolvedPath = resolve(expandedPath);
    const manifestPath = join(resolvedPath, 'knowledge-manifest.json');

    if (!existsSync(manifestPath)) {
      return {
        path: resolvedPath,
        manifest: null,
        error: `Manifest not found: ${manifestPath}`
      };
    }

    try {
      const content = readFileSync(manifestPath, 'utf-8');
      const manifest = JSON.parse(content) as KnowledgeManifest;
      return {
        path: resolvedPath,
        manifest,
        error: null
      };
    } catch (error) {
      return {
        path: resolvedPath,
        manifest: null,
        error: error instanceof Error
          ? `Failed to parse manifest: ${error.message}`
          : 'Failed to parse manifest'
      };
    }
  }

  /**
   * Set the knowledge repository path and load the manifest (legacy mode)
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
   * Load the knowledge-manifest.json from the repository (legacy mode)
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
    // Configured if either tier exists (even if not loaded)
    return this.projectTier !== null || this.globalTier !== null || this.repoPath !== null;
  }

  /**
   * Check if at least one manifest loaded successfully
   */
  isLoaded(): boolean {
    return this.projectTier?.manifest !== null ||
           this.globalTier?.manifest !== null ||
           this.manifest !== null;
  }

  /**
   * Get status of the knowledge repository
   */
  getStatus(): KnowledgeRepoStatus {
    // Two-tier mode
    if (this.projectTier !== null || this.globalTier !== null) {
      const status: KnowledgeRepoStatus = {
        configured: this.isConfigured()
      };

      if (this.projectTier) {
        status.project = this.getTierStatus(this.projectTier);
      }

      if (this.globalTier) {
        status.global = this.getTierStatus(this.globalTier);
      }

      return status;
    }

    // Legacy mode (single path)
    if (!this.repoPath) {
      return {
        configured: false,
        error: 'No knowledge repository configured'
      };
    }

    if (!this.manifest) {
      return {
        configured: true,
        global: {
          path: this.repoPath,
          loaded: false,
          error: this.loadError || 'Manifest not loaded'
        }
      };
    }

    const extensionCount = this.manifest.extensions?.length || 0;
    const skillCount = (this.manifest.skills?.local?.length || 0) +
                       (this.manifest.skills?.remote?.length || 0);

    return {
      configured: true,
      global: {
        path: this.repoPath,
        loaded: true,
        manifest: {
          name: this.manifest.name,
          description: this.manifest.description,
          extensions: extensionCount,
          skills: skillCount
        }
      }
    };
  }

  /**
   * Get status for a single tier
   */
  private getTierStatus(tier: LoadedTier): KnowledgeRepoTierStatus {
    if (!tier.manifest) {
      return {
        path: tier.path,
        loaded: false,
        error: tier.error || 'Manifest not loaded'
      };
    }

    const extensionCount = tier.manifest.extensions?.length || 0;
    const skillCount = (tier.manifest.skills?.local?.length || 0) +
                       (tier.manifest.skills?.remote?.length || 0);

    return {
      path: tier.path,
      loaded: true,
      manifest: {
        name: tier.manifest.name,
        description: tier.manifest.description,
        extensions: extensionCount,
        skills: skillCount
      }
    };
  }

  /**
   * List all available extensions (with source indicator)
   */
  listExtensions(): ExtensionListItemWithSource[] {
    const extensions: ExtensionListItemWithSource[] = [];
    const seenAgents = new Set<string>();

    // Project extensions first (highest priority)
    if (this.projectTier?.manifest?.extensions) {
      for (const ext of this.projectTier.manifest.extensions) {
        seenAgents.add(ext.agent);
        extensions.push({
          agent: ext.agent,
          type: ext.type,
          description: ext.description,
          requiredSkills: ext.requiredSkills,
          fallbackBehavior: ext.fallbackBehavior,
          source: 'project'
        });
      }
    }

    // Global extensions (only if not overridden by project)
    if (this.globalTier?.manifest?.extensions) {
      for (const ext of this.globalTier.manifest.extensions) {
        if (seenAgents.has(ext.agent)) {
          // Mark the project extension as overriding global
          const projectExt = extensions.find(e => e.agent === ext.agent);
          if (projectExt) {
            projectExt.overridesGlobal = true;
          }
        } else {
          extensions.push({
            agent: ext.agent,
            type: ext.type,
            description: ext.description,
            requiredSkills: ext.requiredSkills,
            fallbackBehavior: ext.fallbackBehavior,
            source: 'global'
          });
        }
      }
    }

    // Legacy mode fallback
    if (extensions.length === 0 && this.manifest?.extensions) {
      return this.manifest.extensions.map(ext => ({
        agent: ext.agent,
        type: ext.type,
        description: ext.description,
        requiredSkills: ext.requiredSkills,
        fallbackBehavior: ext.fallbackBehavior,
        source: 'global' as const
      }));
    }

    return extensions;
  }

  /**
   * Get extension for a specific agent (checks project first, then global)
   */
  getExtension(agentId: string): ResolvedExtension | null {
    // Priority 1: Check project-specific manifest
    if (this.projectTier?.manifest?.extensions) {
      const declaration = this.projectTier.manifest.extensions.find(
        ext => ext.agent === agentId
      );
      if (declaration) {
        return this.resolveExtensionFromTier(declaration, this.projectTier);
      }
    }

    // Priority 2: Check global manifest
    if (this.globalTier?.manifest?.extensions) {
      const declaration = this.globalTier.manifest.extensions.find(
        ext => ext.agent === agentId
      );
      if (declaration) {
        return this.resolveExtensionFromTier(declaration, this.globalTier);
      }
    }

    // Legacy mode fallback
    if (this.manifest?.extensions && this.repoPath) {
      const declaration = this.manifest.extensions.find(
        ext => ext.agent === agentId
      );
      if (declaration) {
        return this.resolveExtension(declaration);
      }
    }

    return null;
  }

  /**
   * Resolve an extension from a specific tier
   */
  private resolveExtensionFromTier(declaration: ExtensionDeclaration, tier: LoadedTier): ResolvedExtension | null {
    const extensionPath = join(tier.path, declaration.file);

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
   * Resolve an extension declaration by loading its file content (legacy mode)
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
   * Returns highest priority manifest available
   */
  getManifest(): KnowledgeManifest | null {
    return this.projectTier?.manifest || this.globalTier?.manifest || this.manifest;
  }

  /**
   * Get skills declared in the manifest
   * Merges skills from both tiers (project takes precedence)
   */
  getManifestSkills(): Array<{ name: string; path: string; description?: string; source: 'project' | 'global' }> {
    const skills: Array<{ name: string; path: string; description?: string; source: 'project' | 'global' }> = [];
    const seenNames = new Set<string>();

    // Project skills first
    if (this.projectTier?.manifest?.skills?.local) {
      for (const skill of this.projectTier.manifest.skills.local) {
        seenNames.add(skill.name);
        skills.push({
          name: skill.name,
          path: join(this.projectTier.path, skill.path),
          description: skill.description,
          source: 'project'
        });
      }
    }

    // Global skills (only if not overridden)
    if (this.globalTier?.manifest?.skills?.local) {
      for (const skill of this.globalTier.manifest.skills.local) {
        if (!seenNames.has(skill.name)) {
          skills.push({
            name: skill.name,
            path: join(this.globalTier.path, skill.path),
            description: skill.description,
            source: 'global'
          });
        }
      }
    }

    // Legacy mode fallback
    if (skills.length === 0 && this.manifest?.skills?.local && this.repoPath) {
      return this.manifest.skills.local.map(skill => ({
        name: skill.name,
        path: join(this.repoPath!, skill.path),
        description: skill.description,
        source: 'global' as const
      }));
    }

    return skills;
  }

  /**
   * Reload manifests from disk
   */
  refresh(): void {
    if (this.projectTier) {
      this.projectTier = this.loadTier(this.projectTier.path);
    }
    if (this.globalTier) {
      this.globalTier = this.loadTier(this.globalTier.path);
    }

    // Update legacy fields
    if (this.projectTier?.manifest) {
      this.manifest = this.projectTier.manifest;
      this.loadError = null;
    } else if (this.globalTier?.manifest) {
      this.manifest = this.globalTier.manifest;
      this.loadError = null;
    }

    // Legacy mode
    if (!this.projectTier && !this.globalTier) {
      this.manifest = null;
      this.loadError = null;
      this.loadManifest();
    }
  }

  /**
   * Get the glossary path if configured
   */
  getGlossaryPath(): string | null {
    // Check project first
    if (this.projectTier?.manifest?.glossary) {
      const glossaryPath = join(this.projectTier.path, this.projectTier.manifest.glossary);
      if (existsSync(glossaryPath)) return glossaryPath;
    }

    // Check global
    if (this.globalTier?.manifest?.glossary) {
      const glossaryPath = join(this.globalTier.path, this.globalTier.manifest.glossary);
      if (existsSync(glossaryPath)) return glossaryPath;
    }

    // Legacy mode
    if (this.manifest?.glossary && this.repoPath) {
      const glossaryPath = join(this.repoPath, this.manifest.glossary);
      return existsSync(glossaryPath) ? glossaryPath : null;
    }

    return null;
  }

  /**
   * Get repository configuration
   * Returns highest priority config available
   */
  getConfig(): KnowledgeManifest['config'] | null {
    return this.projectTier?.manifest?.config ||
           this.globalTier?.manifest?.config ||
           this.manifest?.config ||
           null;
  }

  /**
   * Search knowledge files across both tiers (project → global)
   * Searches file names, content, and headings
   */
  searchKnowledge(query: string, options: KnowledgeSearchOptions = {}): KnowledgeSearchResult[] {
    const {
      limit = 5,
      directory,
      includeContent = false,
      minRelevance = 0.1
    } = options;

    const results: KnowledgeSearchResult[] = [];
    const seenPaths = new Set<string>();
    const queryLower = query.toLowerCase();
    const queryTerms = queryLower.split(/\s+/).filter(t => t.length > 2);

    // Search project tier first (highest priority)
    if (this.projectTier?.manifest) {
      const projectResults = this.searchTier(
        this.projectTier.path,
        'project',
        queryLower,
        queryTerms,
        directory,
        includeContent
      );
      for (const result of projectResults) {
        if (result.relevance >= minRelevance) {
          seenPaths.add(result.path);
          results.push(result);
        }
      }
    }

    // Search global tier (fallback, skip files already found in project)
    if (this.globalTier?.manifest) {
      const globalResults = this.searchTier(
        this.globalTier.path,
        'global',
        queryLower,
        queryTerms,
        directory,
        includeContent
      );
      for (const result of globalResults) {
        if (result.relevance >= minRelevance && !seenPaths.has(result.path)) {
          results.push(result);
        }
      }
    }

    // Sort by relevance descending
    results.sort((a, b) => b.relevance - a.relevance);

    return results.slice(0, limit);
  }

  /**
   * Search a single tier for matching knowledge files
   */
  private searchTier(
    tierPath: string,
    source: 'project' | 'global',
    queryLower: string,
    queryTerms: string[],
    directory?: string,
    includeContent = false
  ): KnowledgeSearchResult[] {
    const results: KnowledgeSearchResult[] = [];
    const searchPath = directory ? join(tierPath, directory) : tierPath;

    if (!existsSync(searchPath)) {
      return results;
    }

    const files = this.findMarkdownFiles(searchPath);

    for (const absolutePath of files) {
      // Skip node_modules
      if (absolutePath.includes('/node_modules/')) {
        continue;
      }

      // Skip hidden files/directories within the knowledge repo (not the repo path itself)
      const pathWithinRepo = relative(tierPath, absolutePath);
      if (pathWithinRepo.split('/').some(segment => segment.startsWith('.') && segment !== '.')) {
        continue;
      }

      const relativePath = relative(tierPath, absolutePath);
      const fileName = basename(absolutePath, extname(absolutePath));
      const fileNameLower = fileName.toLowerCase();

      let content: string;
      try {
        content = readFileSync(absolutePath, 'utf-8');
      } catch {
        continue;
      }

      const contentLower = content.toLowerCase();

      // Calculate relevance score
      let relevance = 0;
      let matchedSection: string | undefined;
      let snippet = '';

      // File name match (high weight)
      if (fileNameLower.includes(queryLower)) {
        relevance += 0.5;
      }

      // Path match (e.g., "01-company" matches "company")
      if (relativePath.toLowerCase().includes(queryLower)) {
        relevance += 0.3;
      }

      // Term matches in file name
      for (const term of queryTerms) {
        if (fileNameLower.includes(term)) {
          relevance += 0.2;
        }
      }

      // Content match
      if (contentLower.includes(queryLower)) {
        relevance += 0.3;

        // Find the best matching section and snippet
        const { section, snippetText } = this.findBestMatch(content, queryLower);
        matchedSection = section;
        snippet = snippetText;
      } else {
        // Check for term matches in content
        let termMatches = 0;
        for (const term of queryTerms) {
          if (contentLower.includes(term)) {
            termMatches++;
          }
        }
        if (termMatches > 0) {
          relevance += 0.1 * (termMatches / queryTerms.length);
          const { section, snippetText } = this.findBestMatch(content, queryTerms[0]);
          matchedSection = section;
          snippet = snippetText;
        }
      }

      // Skip if no relevance
      if (relevance === 0) {
        continue;
      }

      // Cap relevance at 1.0
      relevance = Math.min(relevance, 1.0);

      // Generate snippet if not already found
      if (!snippet) {
        snippet = this.generateSnippet(content);
      }

      const result: KnowledgeSearchResult = {
        path: relativePath,
        absolutePath,
        name: fileName,
        source,
        relevance,
        snippet,
        section: matchedSection
      };

      if (includeContent) {
        result.content = content;
      }

      results.push(result);
    }

    return results;
  }

  /**
   * Recursively find all markdown files in a directory
   */
  private findMarkdownFiles(dir: string): string[] {
    const files: string[] = [];

    if (!existsSync(dir)) {
      return files;
    }

    try {
      const entries = readdirSync(dir);
      for (const entry of entries) {
        // Skip hidden files/directories
        if (entry.startsWith('.')) {
          continue;
        }

        const fullPath = join(dir, entry);
        try {
          const stat = statSync(fullPath);
          if (stat.isDirectory()) {
            files.push(...this.findMarkdownFiles(fullPath));
          } else if (entry.endsWith('.md')) {
            files.push(fullPath);
          }
        } catch {
          // Skip files we can't stat
        }
      }
    } catch {
      // Skip directories we can't read
    }

    return files;
  }

  /**
   * Find the best matching section and generate a snippet
   */
  private findBestMatch(content: string, query: string): { section?: string; snippetText: string } {
    const lines = content.split('\n');
    const queryLower = query.toLowerCase();
    let currentSection: string | undefined;
    let bestMatchIndex = -1;
    let bestSection: string | undefined;

    // Find the line with the best match and track sections
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Track current section (markdown heading)
      if (line.startsWith('#')) {
        currentSection = line.replace(/^#+\s*/, '').trim();
      }

      // Check for query match
      if (line.toLowerCase().includes(queryLower)) {
        bestMatchIndex = i;
        bestSection = currentSection;
        break; // Take first match
      }
    }

    if (bestMatchIndex === -1) {
      return {
        section: undefined,
        snippetText: this.generateSnippet(content)
      };
    }

    // Generate snippet around the match (3 lines before, match, 3 lines after)
    const start = Math.max(0, bestMatchIndex - 1);
    const end = Math.min(lines.length, bestMatchIndex + 4);
    const snippetLines = lines.slice(start, end);
    const snippetText = snippetLines.join('\n').trim();

    return {
      section: bestSection,
      snippetText: snippetText.length > 500 ? snippetText.slice(0, 500) + '...' : snippetText
    };
  }

  /**
   * Generate a generic snippet from the start of the content
   */
  private generateSnippet(content: string): string {
    const lines = content.split('\n');
    const snippetLines: string[] = [];
    let charCount = 0;

    for (const line of lines) {
      // Skip empty lines at the start
      if (snippetLines.length === 0 && !line.trim()) {
        continue;
      }

      snippetLines.push(line);
      charCount += line.length;

      if (charCount > 300 || snippetLines.length >= 5) {
        break;
      }
    }

    const snippet = snippetLines.join('\n').trim();
    return snippet.length > 300 ? snippet.slice(0, 300) + '...' : snippet;
  }

  /**
   * Get a specific knowledge file by path
   * Checks project tier first, then global
   */
  getKnowledgeFile(filePath: string): { content: string; source: 'project' | 'global'; absolutePath: string } | null {
    // Try project tier first
    if (this.projectTier?.path) {
      const projectPath = join(this.projectTier.path, filePath);
      if (existsSync(projectPath)) {
        try {
          return {
            content: readFileSync(projectPath, 'utf-8'),
            source: 'project',
            absolutePath: projectPath
          };
        } catch {
          // Fall through to global
        }
      }
    }

    // Try global tier
    if (this.globalTier?.path) {
      const globalPath = join(this.globalTier.path, filePath);
      if (existsSync(globalPath)) {
        try {
          return {
            content: readFileSync(globalPath, 'utf-8'),
            source: 'global',
            absolutePath: globalPath
          };
        } catch {
          return null;
        }
      }
    }

    return null;
  }

  // ============================================================================
  // Knowledge Detection Methods (P0 Knowledge System)
  // ============================================================================

  /**
   * Get the repository URL from the manifest
   * Returns the git URL for cloning the knowledge repository
   */
  getRepositoryUrl(): string | null {
    // Check project tier first
    if (this.projectTier?.manifest?.repository?.url) {
      return this.projectTier.manifest.repository.url;
    }

    // Check global tier
    if (this.globalTier?.manifest?.repository?.url) {
      return this.globalTier.manifest.repository.url;
    }

    // Legacy manifest
    if (this.manifest?.repository?.url) {
      return this.manifest.repository.url;
    }

    return null;
  }

  /**
   * Detect whether a project expects knowledge to be configured
   * Uses multi-signal detection from project files
   *
   * @param projectPath - Path to the project root
   * @returns KnowledgeExpectation with signals and reason
   */
  detectKnowledgeExpectation(projectPath: string): KnowledgeExpectation {
    const signals: KnowledgeSignal[] = [];
    const reasons: string[] = [];

    // Signal 1: Check .mcp.json for KNOWLEDGE_REPO_PATH (HIGH confidence)
    const mcpJsonPath = join(projectPath, '.mcp.json');
    if (existsSync(mcpJsonPath)) {
      try {
        const mcpContent = readFileSync(mcpJsonPath, 'utf-8');
        if (mcpContent.includes('KNOWLEDGE_REPO_PATH')) {
          signals.push('mcp_config');
          reasons.push('.mcp.json references KNOWLEDGE_REPO_PATH');
        }
      } catch {
        // Ignore read errors
      }
    }

    // Signal 2: Check CLAUDE.md for knowledge tool references (MEDIUM confidence)
    const claudeMdPath = join(projectPath, 'CLAUDE.md');
    if (existsSync(claudeMdPath)) {
      try {
        const claudeContent = readFileSync(claudeMdPath, 'utf-8');
        const knowledgePatterns = [
          'knowledge_search',
          'knowledge_get',
          'knowledge repository',
          'knowledge-manifest'
        ];

        for (const pattern of knowledgePatterns) {
          if (claudeContent.toLowerCase().includes(pattern.toLowerCase())) {
            signals.push('claude_md_reference');
            reasons.push(`CLAUDE.md references ${pattern}`);
            break; // Only add this signal once
          }
        }
      } catch {
        // Ignore read errors
      }
    }

    // Determine expectation based on signals
    const expected = signals.length > 0;

    // Get suggested repo URL from existing loaded manifest (if any)
    const suggestedRepoUrl = this.getRepositoryUrl() || undefined;

    return {
      expected,
      reason: expected
        ? `Project expects knowledge: ${reasons.join('; ')}`
        : 'No knowledge signals detected in project',
      signals,
      suggestedRepoUrl
    };
  }

  /**
   * Detect whether the user appears to be a team member joining existing knowledge
   * Compares global knowledge state against project expectations
   *
   * @param projectPath - Path to the project root (optional)
   * @returns TeamMemberDetection with setup instructions
   */
  detectTeamMemberStatus(projectPath?: string): TeamMemberDetection {
    const hasGlobalKnowledge = this.globalTier?.manifest !== null;
    const hasProjectKnowledge = this.projectTier?.manifest !== null;

    // If global knowledge exists, user is already set up
    if (hasGlobalKnowledge) {
      return {
        isTeamMember: false,
        teamRepoUrl: this.getRepositoryUrl(),
        setupNeeded: 'none',
        reason: 'Global knowledge already configured'
      };
    }

    // If project expects knowledge but global doesn't exist, user may be a team member
    if (projectPath) {
      const expectation = this.detectKnowledgeExpectation(projectPath);

      if (expectation.expected) {
        // Check if there's a repo URL we can suggest
        const teamRepoUrl = expectation.suggestedRepoUrl || null;

        return {
          isTeamMember: true,
          teamRepoUrl,
          setupNeeded: teamRepoUrl ? 'clone_and_link' : 'link_only',
          reason: `Project expects knowledge but none configured. ${expectation.reason}`
        };
      }
    }

    // No signals of team membership
    return {
      isTeamMember: false,
      teamRepoUrl: null,
      setupNeeded: 'none',
      reason: 'No knowledge expectation detected'
    };
  }
}
