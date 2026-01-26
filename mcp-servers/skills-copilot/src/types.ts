/**
 * Skills Hub Types
 */

export interface Skill {
  id: string;
  name: string;
  description: string;
  content: string;
  category?: string;
  keywords: string[];
  tags?: string[];
  author?: string;
  source: SkillSource;
  sourceUrl?: string;
  version: string;
  isProprietary: boolean;
  cachedAt?: Date;
  expiresAt?: Date;
}

export interface SkillMeta {
  id: string;
  name: string;
  description: string;
  category?: string;
  keywords: string[];
  tags?: string[];
  author?: string;
  source: SkillSource;
  stars?: number;
  triggers?: SkillTriggers;
}

/**
 * Trigger definitions for context-based skill auto-invocation
 */
export interface SkillTriggers {
  /** File patterns that trigger this skill (glob-like: *.test.ts, **\/spec.js) */
  files?: string[];
  /** Keywords in context that trigger this skill */
  keywords?: string[];
}

export interface SkillMatch extends SkillMeta {
  relevance: number;
  githubUrl?: string;  // URL to fetch skill content (for SkillsMP skills)
}

export type SkillSource = 'private' | 'skillsmp' | 'local' | 'cache';

export interface SkillSearchParams {
  query: string;
  source?: SkillSource;
  limit?: number;
}

export interface SkillGetParams {
  name: string;
  forceRefresh?: boolean;
}

export interface SkillSaveParams {
  name: string;
  description: string;
  content: string;
  category?: string;
  keywords: string[];
  tags?: string[];
  isProprietary?: boolean;
}

export interface CachedSkill {
  name: string;
  content: string;
  source: SkillSource;
  cachedAt: number;
  expiresAt: number;
}

export interface SkillsHubConfig {
  skillsmpApiKey?: string;
  postgresUrl?: string;
  cachePath: string;
  cacheTtlDays: number;
  localSkillsPath?: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
}

export interface SkillsMPSearchResponse {
  success: boolean;
  data: {
    skills: SkillsMPSkill[];
  };
}

export interface SkillsMPSkill {
  id: string;
  name: string;
  author: string;
  description: string;
  githubUrl: string;
  skillUrl: string;
  stars: number;
  updatedAt: number;
}

export interface ProviderResult<T> {
  success: boolean;
  data?: T;
  error?: string;
  source: SkillSource;
}

// ============================================================================
// Knowledge Repository Extension Types
// ============================================================================

/**
 * Extension type determines how the extension modifies the base agent
 */
export type ExtensionType = 'override' | 'extension' | 'skills';

/**
 * Fallback behavior when required skills are unavailable
 */
export type FallbackBehavior = 'use_base' | 'use_base_with_warning' | 'fail';

/**
 * Extension declaration from knowledge-manifest.json
 */
export interface ExtensionDeclaration {
  agent: string;
  type: ExtensionType;
  file: string;
  description?: string;
  requiredSkills?: string[];
  fallbackBehavior?: FallbackBehavior;
}

/**
 * Skill declaration from knowledge-manifest.json
 */
export interface ManifestSkillDeclaration {
  name: string;
  path: string;
  description?: string;
  keywords?: string[];
}

/**
 * Knowledge repository manifest structure
 */
export interface KnowledgeManifest {
  version: string;
  name: string;
  description?: string;
  /** Git repository URL for team cloning */
  repository?: KnowledgeRepositoryConfig;
  framework?: {
    name: string;
    minVersion?: string;
  };
  extensions?: ExtensionDeclaration[];
  skills?: {
    local?: ManifestSkillDeclaration[];
    remote?: Array<{
      name: string;
      source: string;
      description?: string;
      fallback?: string;
    }>;
  };
  glossary?: string;
  config?: {
    preferProprietarySkills?: boolean;
    strictMode?: boolean;
  };
}

/**
 * Resolved extension with loaded content
 */
export interface ResolvedExtension {
  agent: string;
  type: ExtensionType;
  content: string;
  description?: string;
  requiredSkills: string[];
  fallbackBehavior: FallbackBehavior;
}

/**
 * Extension listing item
 */
export interface ExtensionListItem {
  agent: string;
  type: ExtensionType;
  description?: string;
  requiredSkills?: string[];
  fallbackBehavior?: FallbackBehavior;
}

/**
 * Status for a single knowledge repository tier
 */
export interface KnowledgeRepoTierStatus {
  path: string;
  loaded: boolean;
  manifest?: {
    name: string;
    description?: string;
    extensions: number;
    skills: number;
  };
  error?: string;
}

/**
 * Knowledge repo status result (supports two-tier: project + global)
 */
export interface KnowledgeRepoStatus {
  configured: boolean;
  /** Project-specific repository (highest priority) */
  project?: KnowledgeRepoTierStatus;
  /** Global repository at ~/.claude/knowledge (fallback) */
  global?: KnowledgeRepoTierStatus;
  /** Legacy single-path error (for backward compatibility) */
  error?: string;
}

/**
 * Configuration for two-tier knowledge repository
 */
export interface KnowledgeRepoConfig {
  /** Project-specific knowledge repo path (highest priority) */
  projectPath?: string;
  /** Global knowledge repo path (defaults to ~/.claude/knowledge) */
  globalPath?: string;
}

/**
 * Extension list item with source indicator
 */
export interface ExtensionListItemWithSource extends ExtensionListItem {
  /** Where this extension comes from */
  source: 'project' | 'global';
  /** Whether this overrides a global extension */
  overridesGlobal?: boolean;
}

// ============================================================================
// Knowledge Search Types
// ============================================================================

/**
 * A single knowledge search result
 */
export interface KnowledgeSearchResult {
  /** File path relative to knowledge repo */
  path: string;
  /** Full absolute path to file */
  absolutePath: string;
  /** File name without extension */
  name: string;
  /** Source tier: project or global */
  source: 'project' | 'global';
  /** Relevance score (0-1) */
  relevance: number;
  /** Matched content snippet */
  snippet: string;
  /** Section/heading where match was found */
  section?: string;
  /** Full file content (only when retrieving single file) */
  content?: string;
}

/**
 * Options for knowledge search
 */
export interface KnowledgeSearchOptions {
  /** Maximum results to return (default: 5) */
  limit?: number;
  /** Search in specific directory only (e.g., "01-company") */
  directory?: string;
  /** Include full content in results (default: false, returns snippets) */
  includeContent?: boolean;
  /** Minimum relevance score (0-1, default: 0.1) */
  minRelevance?: number;
}

/**
 * Topic mapping for manifest (optional enhancement)
 */
export interface KnowledgeTopicMapping {
  /** Topic keyword (e.g., "company", "brand", "products") */
  topic: string;
  /** File path relative to knowledge repo */
  file: string;
  /** Brief description */
  description?: string;
}

// ============================================================================
// Knowledge Detection Types (P0 Knowledge System)
// ============================================================================

/**
 * Signal types indicating a project expects knowledge
 */
export type KnowledgeSignal = 'mcp_config' | 'claude_md_reference';

/**
 * Result of detecting whether a project expects knowledge
 */
export interface KnowledgeExpectation {
  /** Whether the project expects knowledge to be configured */
  expected: boolean;
  /** Human-readable reason for the expectation */
  reason: string;
  /** Signals that led to this determination */
  signals: KnowledgeSignal[];
  /** If team knowledge repo URL is available from manifest */
  suggestedRepoUrl?: string;
}

/**
 * Type of setup needed for team member
 */
export type TeamSetupNeeded = 'clone_and_link' | 'link_only' | 'none';

/**
 * Result of detecting team member status
 */
export interface TeamMemberDetection {
  /** Whether the user appears to be a team member joining existing knowledge */
  isTeamMember: boolean;
  /** URL of team knowledge repository (if detected) */
  teamRepoUrl: string | null;
  /** What setup is needed */
  setupNeeded: TeamSetupNeeded;
  /** Reason for detection result */
  reason?: string;
}

/**
 * Repository configuration in manifest
 */
export interface KnowledgeRepositoryConfig {
  /** Git URL to clone the knowledge repository */
  url: string;
  /** Repository type (currently only 'git' supported) */
  type?: 'git';
}
