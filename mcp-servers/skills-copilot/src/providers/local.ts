/**
 * Local File Provider
 *
 * Fallback for git-synced skills stored in the repository
 * Auto-discovers skills from .claude/skills directories
 */

import { readFileSync, existsSync, readdirSync, statSync } from 'fs';
import { join, basename } from 'path';
import { homedir } from 'os';
import type { Skill, SkillMeta, ProviderResult } from '../types.js';

// Discovery paths for auto-scanning (in priority order)
const DISCOVERY_PATHS = [
  '.claude/skills',                                  // Project-level skills
  join(homedir(), '.claude', 'skills'),             // User-level skills
];

interface SkillCacheEntry {
  meta: SkillMeta;
  path: string;
  mtime: number;
}

export class LocalProvider {
  private skillsPath: string;
  private skillsCache: Map<string, SkillMeta> = new Map();
  private discoveryCache: Map<string, SkillCacheEntry> = new Map();

  constructor(skillsPath: string) {
    this.skillsPath = skillsPath;
    this.scanSkills();
    this.discoverSkills();
  }

  /**
   * Scan local skills directory (legacy manifest-based)
   */
  private scanSkills(): void {
    if (!existsSync(this.skillsPath)) {
      return;
    }

    try {
      this.scanDirectory(this.skillsPath);
    } catch (error) {
      console.error('Error scanning local skills:', error);
    }
  }

  /**
   * Auto-discover skills from standard paths
   */
  private discoverSkills(): void {
    for (const basePath of DISCOVERY_PATHS) {
      try {
        this.discoverInPath(basePath);
      } catch (error) {
        // Silently continue if discovery path doesn't exist
        if (error instanceof Error && !error.message.includes('ENOENT')) {
          console.warn(`Error discovering skills in ${basePath}:`, error);
        }
      }
    }
  }

  /**
   * Discover skills in a specific path
   */
  private discoverInPath(basePath: string): void {
    if (!existsSync(basePath)) {
      return;
    }

    const skillDirs = readdirSync(basePath, { withFileTypes: true })
      .filter(d => d.isDirectory());

    for (const dir of skillDirs) {
      const skillPath = join(basePath, dir.name, 'SKILL.md');
      if (existsSync(skillPath)) {
        // Check if we need to refresh this skill
        if (this.shouldRefresh(skillPath)) {
          const meta = this.parseSkillMeta(skillPath);
          if (meta) {
            const validation = this.validateSkill(meta);
            if (validation.valid) {
              const stat = statSync(skillPath);
              this.discoveryCache.set(meta.name, {
                meta,
                path: skillPath,
                mtime: stat.mtimeMs
              });
              // Also add to main cache for unified listing
              this.skillsCache.set(meta.name, meta);
            } else {
              console.warn(`Skipping ${skillPath}: ${validation.errors.join(', ')}`);
            }
          }
        }
      }
    }
  }

  /**
   * Check if a skill file needs to be refreshed
   */
  private shouldRefresh(skillPath: string): boolean {
    // Find cached entry by path
    for (const [name, entry] of this.discoveryCache.entries()) {
      if (entry.path === skillPath) {
        const stat = statSync(skillPath);
        return stat.mtimeMs > entry.mtime;
      }
    }
    // Not in cache, needs to be loaded
    return true;
  }

  /**
   * Validate skill metadata
   */
  private validateSkill(skill: Partial<SkillMeta>): { valid: boolean; errors: string[] } {
    const errors: string[] = [];

    if (!skill.name || skill.name.trim() === '') {
      errors.push('Missing: name');
    }
    if (!skill.description || skill.description.trim() === '') {
      errors.push('Missing: description');
    }

    return {
      valid: errors.length === 0,
      errors
    };
  }

  /**
   * Recursively scan directory for SKILL.md files
   */
  private scanDirectory(dir: string): void {
    const entries = readdirSync(dir);

    for (const entry of entries) {
      const fullPath = join(dir, entry);
      const stat = statSync(fullPath);

      if (stat.isDirectory()) {
        // Check for SKILL.md in this directory
        const skillPath = join(fullPath, 'SKILL.md');
        if (existsSync(skillPath)) {
          const meta = this.parseSkillMeta(skillPath);
          if (meta) {
            // Validate skill before adding to cache
            const validation = this.validateSkill(meta);
            if (validation.valid) {
              this.skillsCache.set(meta.name, meta);
            } else {
              console.warn(`Skipping ${skillPath}: ${validation.errors.join(', ')}`);
            }
          }
        }
        // Continue scanning subdirectories
        this.scanDirectory(fullPath);
      }
    }
  }

  /**
   * Parse skill metadata from SKILL.md
   */
  private parseSkillMeta(skillPath: string): SkillMeta | null {
    try {
      const content = readFileSync(skillPath, 'utf-8');

      // Parse YAML frontmatter
      const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
      if (!frontmatterMatch) {
        console.warn(`No frontmatter found in ${skillPath}`);
        return null;
      }

      const frontmatter = frontmatterMatch[1];
      // Support both 'name:' and 'skill_name:' formats
      const nameMatch = frontmatter.match(/(?:skill_)?name:\s*(.+)/);
      const descMatch = frontmatter.match(/description:\s*(.+)/);

      if (!nameMatch) {
        console.warn(`No name field found in frontmatter: ${skillPath}`);
        return null;
      }

      const name = nameMatch[1].trim();
      const description = descMatch ? descMatch[1].trim() : '';

      // Extract category from path
      const pathParts = skillPath.split('/');
      const categoryIndex = pathParts.indexOf('01-skills');
      const category = categoryIndex >= 0 && pathParts.length > categoryIndex + 1
        ? pathParts[categoryIndex + 1].replace(/^\d+-/, '')
        : undefined;

      return {
        id: `local-${name}`,
        name,
        description,
        category,
        keywords: this.extractKeywords(description),
        source: 'local'
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      console.warn(`Failed to parse ${skillPath}: ${message}`);
      return null;
    }
  }

  /**
   * Extract keywords from description
   */
  private extractKeywords(description: string): string[] {
    const stopWords = new Set([
      'a', 'an', 'the', 'and', 'or', 'but', 'is', 'are', 'for', 'to', 'with',
      'use', 'when', 'you', 'your', 'of', 'in', 'on', 'at', 'by', 'this'
    ]);

    return description
      .toLowerCase()
      .replace(/[^\w\s]/g, ' ')
      .split(/\s+/)
      .filter(word => word.length > 2 && !stopWords.has(word))
      .slice(0, 10);
  }

  /**
   * Get skill by name
   */
  getSkill(name: string): ProviderResult<Skill> {
    // First check discovered cache (faster, has path cached)
    const discovered = this.discoveryCache.get(name);
    if (discovered) {
      try {
        const content = readFileSync(discovered.path, 'utf-8');
        return {
          success: true,
          data: {
            id: discovered.meta.id,
            name: discovered.meta.name,
            description: discovered.meta.description,
            content,
            category: discovered.meta.category,
            keywords: discovered.meta.keywords,
            source: 'local',
            version: '1.0.0',
            isProprietary: false
          },
          source: 'local'
        };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : 'Read error',
          source: 'local'
        };
      }
    }

    // Fall back to legacy manifest-based search
    const meta = this.skillsCache.get(name);
    if (!meta) {
      return { success: false, error: 'Skill not found', source: 'local' };
    }

    // Find the skill file
    const skillPath = this.findSkillPath(name);
    if (!skillPath) {
      return { success: false, error: 'Skill file not found', source: 'local' };
    }

    try {
      const content = readFileSync(skillPath, 'utf-8');
      return {
        success: true,
        data: {
          id: meta.id,
          name: meta.name,
          description: meta.description,
          content,
          category: meta.category,
          keywords: meta.keywords,
          source: 'local',
          version: '1.0.0',
          isProprietary: false
        },
        source: 'local'
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Read error',
        source: 'local'
      };
    }
  }

  /**
   * Find skill path by name
   */
  private findSkillPath(name: string): string | null {
    const search = (dir: string): string | null => {
      if (!existsSync(dir)) return null;

      const entries = readdirSync(dir);
      for (const entry of entries) {
        const fullPath = join(dir, entry);
        const stat = statSync(fullPath);

        if (stat.isDirectory()) {
          const skillPath = join(fullPath, 'SKILL.md');
          if (existsSync(skillPath)) {
            const content = readFileSync(skillPath, 'utf-8');
            const nameMatch = content.match(/(?:skill_)?name:\s*(.+)/);
            if (nameMatch && nameMatch[1].trim() === name) {
              return skillPath;
            }
          }
          // Check subdirectories
          const found = search(fullPath);
          if (found) return found;
        }
      }
      return null;
    };

    return search(this.skillsPath);
  }

  /**
   * List all local skills
   */
  listSkills(): ProviderResult<SkillMeta[]> {
    return {
      success: true,
      data: Array.from(this.skillsCache.values()),
      source: 'local'
    };
  }

  /**
   * Search skills by query
   */
  searchSkills(query: string): ProviderResult<SkillMeta[]> {
    const queryLower = query.toLowerCase();
    const matches = Array.from(this.skillsCache.values())
      .filter(skill =>
        skill.name.toLowerCase().includes(queryLower) ||
        skill.description.toLowerCase().includes(queryLower) ||
        skill.keywords.some(k => k.includes(queryLower))
      );

    return {
      success: true,
      data: matches,
      source: 'local'
    };
  }

  /**
   * Refresh skill cache (scans both manifest and discovery paths)
   */
  refresh(): void {
    this.skillsCache.clear();
    this.discoveryCache.clear();
    this.scanSkills();
    this.discoverSkills();
  }

  /**
   * Get skill count
   */
  getCount(): number {
    return this.skillsCache.size;
  }

  /**
   * Get count of auto-discovered skills
   */
  getDiscoveredCount(): number {
    return this.discoveryCache.size;
  }

  /**
   * Get list of discovered skills with their source paths
   */
  getDiscoveredSkills(): Array<{ skill: SkillMeta; path: string }> {
    return Array.from(this.discoveryCache.values()).map(entry => ({
      skill: entry.meta,
      path: entry.path
    }));
  }

  /**
   * Force re-scan of discovery paths (clears cache)
   */
  rediscover(): void {
    this.discoveryCache.clear();
    this.discoverSkills();
  }
}
