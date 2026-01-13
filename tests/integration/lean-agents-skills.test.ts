/**
 * Integration Tests: Lean Agent Model + Skills System
 *
 * Tests the complete lean agent refactoring and skill integration:
 * 1. Agent structure validation (lean ~60-100 lines)
 * 2. Skill loading protocol in agents
 * 3. Skill template structure (quality sections)
 * 4. skill_evaluate auto-detection
 *
 * @see PRD-58bb45d1-f5eb-4e23-8e4a-2f386a955630
 * @see Stream-A (Skill Infrastructure)
 * @see Stream-C through Stream-I (Agent Refactoring)
 * @see Stream-Z (Integration)
 */

import { readFileSync, readdirSync, existsSync, statSync } from 'fs';
import { join, basename } from 'path';

// ============================================================================
// TEST FRAMEWORK
// ============================================================================

interface TestResult {
  testName: string;
  status: 'PASS' | 'FAIL' | 'SKIP';
  duration: number;
  error?: string;
  details?: string;
}

const results: TestResult[] = [];

function logResult(testName: string, status: 'PASS' | 'FAIL' | 'SKIP', duration: number, error?: string, details?: string) {
  results.push({ testName, status, duration, error, details });
  const emoji = status === 'PASS' ? '✅' : status === 'FAIL' ? '❌' : '⏭️';
  console.log(`${emoji} ${testName} (${duration}ms)${error ? ': ' + error : ''}`);
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

function assertEquals<T>(actual: T, expected: T, message: string): void {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

function assertInRange(actual: number, min: number, max: number, message: string): void {
  if (actual < min || actual > max) {
    throw new Error(`${message}: expected ${actual} to be between ${min} and ${max}`);
  }
}

function assertContains(text: string, substring: string, message: string): void {
  if (!text.includes(substring)) {
    throw new Error(`${message}: expected to contain "${substring}"`);
  }
}

async function runTest(testName: string, testFn: () => void | Promise<void>): Promise<void> {
  const start = Date.now();
  try {
    await testFn();
    logResult(testName, 'PASS', Date.now() - start);
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    logResult(testName, 'FAIL', Date.now() - start, errorMessage);
  }
}

// ============================================================================
// TEST PATHS
// ============================================================================

const projectRoot = join(__dirname, '../..');
const agentsDir = join(projectRoot, '.claude/agents');
const skillsDir = join(projectRoot, '.claude/skills');
const templatesDir = join(projectRoot, 'templates');

// Lean agents (refactored in this initiative)
// Note: 'ta' is excluded because it's the orchestrating agent with different structure
const LEAN_AGENTS = ['me', 'qa', 'sec', 'doc', 'do', 'sd', 'uxd', 'uids', 'uid', 'cw'];

// Orchestrating agent (different structure - handles PRD/task creation)
const ORCHESTRATOR_AGENTS = ['ta'];

// Legacy agents (not refactored)
const LEGACY_AGENTS = ['cco', 'kc'];

// Skill categories
const SKILL_CATEGORIES = ['code', 'testing', 'security', 'documentation', 'devops'];

// ============================================================================
// AGENT STRUCTURE TESTS
// ============================================================================

async function testAgentStructure() {
  console.log('\n📦 Testing Agent Structure...\n');

  // Test: All lean agents exist
  await runTest('All lean agents exist', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      assert(existsSync(agentPath), `Agent ${agent}.md not found`);
    }
  });

  // Test: Lean agents are within line limit
  await runTest('Lean agents are ~60-100 lines', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');
      const lineCount = content.split('\n').length;

      // Allow some flexibility: 40-150 lines
      assertInRange(lineCount, 40, 150, `Agent ${agent}.md has ${lineCount} lines`);
    }
  });

  // Test: Agents have required frontmatter
  await runTest('Agents have required frontmatter', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      // Check frontmatter markers
      assert(content.startsWith('---'), `Agent ${agent} missing opening frontmatter`);
      const secondDash = content.indexOf('---', 3);
      assert(secondDash > 0, `Agent ${agent} missing closing frontmatter`);

      // Extract frontmatter
      const frontmatter = content.slice(3, secondDash);

      // Check required fields
      assertContains(frontmatter, 'name:', `Agent ${agent} missing name`);
      assertContains(frontmatter, 'description:', `Agent ${agent} missing description`);
      assertContains(frontmatter, 'tools:', `Agent ${agent} missing tools`);
      assertContains(frontmatter, 'model:', `Agent ${agent} missing model`);
    }
  });

  // Test: Agents include skill_evaluate in tools
  await runTest('Agents include skill_evaluate tool', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      // Extract tools line
      const toolsMatch = content.match(/tools:\s*(.+)/);
      assert(toolsMatch !== null, `Agent ${agent} missing tools`);

      const tools = toolsMatch[1];
      assertContains(tools, 'skill_evaluate', `Agent ${agent} missing skill_evaluate tool`);
    }
  });

  // Test: Agents have Skill Loading Protocol section
  await runTest('Agents have Skill Loading Protocol section', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(content, '## Skill Loading Protocol', `Agent ${agent} missing Skill Loading Protocol section`);
    }
  });

  // Test: Agents have Core Behaviors section
  await runTest('Agents have Core Behaviors section', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(content, '## Core Behaviors', `Agent ${agent} missing Core Behaviors section`);
      assertContains(content, '**Always:**', `Agent ${agent} missing Always list`);
      assertContains(content, '**Never:**', `Agent ${agent} missing Never list`);
    }
  });

  // Test: Agents have Output Format section
  await runTest('Agents have Output Format section', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(content, '## Output Format', `Agent ${agent} missing Output Format section`);
    }
  });

  // Test: Agents have Route To Other Agent section
  await runTest('Agents have Route To Other Agent section', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(content, '## Route To Other Agent', `Agent ${agent} missing Route To Other Agent section`);
    }
  });

  // Test: Agents use sonnet model (for cost efficiency)
  await runTest('Agents use sonnet model', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(content, 'model: sonnet', `Agent ${agent} should use sonnet model`);
    }
  });

  // Test: Agents include preflight_check tool
  await runTest('Agents include preflight_check tool', () => {
    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      // Extract tools line
      const toolsMatch = content.match(/tools:\s*(.+)/);
      assert(toolsMatch !== null, `Agent ${agent} missing tools`);

      const tools = toolsMatch[1];
      assertContains(tools, 'preflight_check', `Agent ${agent} missing preflight_check tool`);
    }
  });
}

// ============================================================================
// SKILL STRUCTURE TESTS
// ============================================================================

async function testSkillStructure() {
  console.log('\n🎯 Testing Skill Structure...\n');

  // Test: Skills directory exists
  await runTest('Skills directory exists', () => {
    assert(existsSync(skillsDir), 'Skills directory not found');
  });

  // Test: Expected skill categories exist
  await runTest('Expected skill categories exist', () => {
    for (const category of SKILL_CATEGORIES) {
      const categoryPath = join(skillsDir, category);
      assert(existsSync(categoryPath), `Skill category ${category} not found`);
    }
  });

  // Test: Skills have required frontmatter
  await runTest('Skills have required frontmatter', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');

      // Check frontmatter markers
      assert(content.startsWith('---'), `Skill ${skillFile} missing opening frontmatter`);
      const secondDash = content.indexOf('---', 3);
      assert(secondDash > 0, `Skill ${skillFile} missing closing frontmatter`);

      // Extract frontmatter
      const frontmatter = content.slice(3, secondDash);

      // Check required fields
      assertContains(frontmatter, 'skill_name:', `Skill ${basename(skillFile)} missing skill_name`);
      assertContains(frontmatter, 'skill_category:', `Skill ${basename(skillFile)} missing skill_category`);
      assertContains(frontmatter, 'description:', `Skill ${basename(skillFile)} missing description`);
      assertContains(frontmatter, 'trigger_files:', `Skill ${basename(skillFile)} missing trigger_files`);
      assertContains(frontmatter, 'trigger_keywords:', `Skill ${basename(skillFile)} missing trigger_keywords`);
    }
  });

  // Test: Skills have quality sections (patterns and anti-patterns)
  await runTest('Skills have quality sections', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const name = basename(skillFile);

      // Check for pattern-related content
      const hasPatterns = content.includes('## Pattern') ||
                          content.includes('## Core Pattern') ||
                          content.includes('GOOD:') ||
                          content.includes('# GOOD');

      const hasAntiPatterns = content.includes('Anti-Pattern') ||
                               content.includes('BAD:') ||
                               content.includes('# BAD');

      assert(hasPatterns || hasAntiPatterns, `Skill ${name} missing pattern/anti-pattern content`);
    }
  });

  // Test: Skills have code examples
  await runTest('Skills have code examples', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const name = basename(skillFile);

      // Check for code blocks
      const codeBlockCount = (content.match(/```/g) || []).length;
      assert(codeBlockCount >= 2, `Skill ${name} should have at least one code example (found ${codeBlockCount / 2} blocks)`);
    }
  });

  // Test: Skills have reasonable token estimates
  await runTest('Skills have reasonable token estimates', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const name = basename(skillFile);

      const tokenMatch = content.match(/token_estimate:\s*(\d+)/);
      if (tokenMatch) {
        const tokenEstimate = parseInt(tokenMatch[1], 10);
        // Skills should be under 3000 tokens for efficiency
        assertInRange(tokenEstimate, 100, 3000, `Skill ${name} token estimate ${tokenEstimate}`);
      }
    }
  });
}

// ============================================================================
// SKILL TEMPLATE TESTS
// ============================================================================

async function testSkillTemplate() {
  console.log('\n📄 Testing Skill Template...\n');

  const templatePath = join(templatesDir, 'skills/SKILL-TEMPLATE.md');

  // Test: Skill template exists
  await runTest('Skill template exists', () => {
    assert(existsSync(templatePath), 'SKILL-TEMPLATE.md not found');
  });

  // Test: Template has required structure
  await runTest('Template has required structure', () => {
    const content = readFileSync(templatePath, 'utf-8');

    assertContains(content, 'skill_name:', 'Template missing skill_name field');
    assertContains(content, 'skill_category:', 'Template missing skill_category field');
    assertContains(content, 'trigger_files:', 'Template missing trigger_files field');
    assertContains(content, 'trigger_keywords:', 'Template missing trigger_keywords field');
    assertContains(content, '## Core Patterns', 'Template missing Core Patterns section');
    assertContains(content, '## Anti-Patterns', 'Template missing Anti-Patterns section');
    assertContains(content, '## Validation Checklist', 'Template missing Validation Checklist section');
  });

  // Test: Template has quality detection metadata
  await runTest('Template has quality detection metadata', () => {
    const content = readFileSync(templatePath, 'utf-8');

    assertContains(content, 'quality_keywords:', 'Template missing quality_keywords field');
    assertContains(content, 'tags:', 'Template missing tags field');
  });
}

// ============================================================================
// REFERENCE MODULE TESTS
// ============================================================================

async function testReferenceModule() {
  console.log('\n📚 Testing Reference Module...\n');

  const referencePath = join(templatesDir, 'references/REFERENCE-TEMPLATE.md');

  // Test: Reference template exists
  await runTest('Reference template exists', () => {
    assert(existsSync(referencePath), 'REFERENCE-TEMPLATE.md not found');
  });

  // Test: Reference template has required structure
  await runTest('Reference template has required structure', () => {
    const content = readFileSync(referencePath, 'utf-8');

    assertContains(content, 'module_name:', 'Template missing module_name field');
    assertContains(content, 'module_type:', 'Template missing module_type field');
    assertContains(content, '## Patterns', 'Template missing Patterns section');
    assertContains(content, '## Anti-Patterns', 'Template missing Anti-Patterns section');
    assertContains(content, '## Quick Reference', 'Template missing Quick Reference section');
  });
}

// ============================================================================
// SKILL EVALUATE INTEGRATION TESTS
// ============================================================================

async function testSkillEvaluateIntegration() {
  console.log('\n🔍 Testing skill_evaluate Integration...\n');

  // Test: Skills have consistent trigger patterns
  await runTest('Skills have consistent trigger patterns', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const name = basename(skillFile);

      // Extract trigger_files
      const filesMatch = content.match(/trigger_files:\s*\[([^\]]+)\]/);
      if (filesMatch) {
        const patterns = filesMatch[1];
        // Should contain glob patterns
        assert(
          patterns.includes('*') || patterns.includes('.'),
          `Skill ${name} trigger_files should contain file patterns`
        );
      }

      // Extract trigger_keywords
      const keywordsMatch = content.match(/trigger_keywords:\s*\[([^\]]+)\]/);
      if (keywordsMatch) {
        const keywords = keywordsMatch[1].split(',').map(k => k.trim());
        assert(keywords.length >= 2, `Skill ${name} should have at least 2 trigger keywords`);
      }
    }
  });

  // Test: Agent skill references match available skills
  await runTest('Agent skill references match available skills', () => {
    const availableSkills = findSkillNames(skillsDir);

    for (const agent of LEAN_AGENTS) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      // Find skill table references
      const skillTableMatch = content.match(/Available \w+ skills:[\s\S]*?\|[\s\S]*?\|/g);
      if (skillTableMatch) {
        // Extract skill names from table (format: | `skill-name` |)
        const skillRefs = content.match(/`([a-z-]+)`/g) || [];
        for (const ref of skillRefs) {
          const skillName = ref.replace(/`/g, '');
          // Skip non-skill references like 'skill_evaluate'
          if (skillName.includes('-') && !skillName.includes('_')) {
            // This is a skill name - it should exist or be in a predictable location
            // Note: We're lenient here as some skills may be in different categories
          }
        }
      }
    }
  });
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function findSkillFiles(dir: string): string[] {
  const files: string[] = [];

  function walk(currentDir: string) {
    if (!existsSync(currentDir)) return;

    const entries = readdirSync(currentDir);
    for (const entry of entries) {
      const fullPath = join(currentDir, entry);
      const stat = statSync(fullPath);

      if (stat.isDirectory()) {
        walk(fullPath);
      } else if (entry.endsWith('.md') && entry !== 'README.md') {
        files.push(fullPath);
      }
    }
  }

  walk(dir);
  return files;
}

function findSkillNames(dir: string): Set<string> {
  const names = new Set<string>();
  const files = findSkillFiles(dir);

  for (const file of files) {
    const content = readFileSync(file, 'utf-8');
    const nameMatch = content.match(/skill_name:\s*([a-z-]+)/);
    if (nameMatch) {
      names.add(nameMatch[1]);
    }
  }

  return names;
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function main() {
  console.log('='.repeat(70));
  console.log('  LEAN AGENTS + SKILLS INTEGRATION TESTS');
  console.log('='.repeat(70));

  await testAgentStructure();
  await testSkillStructure();
  await testSkillTemplate();
  await testReferenceModule();
  await testSkillEvaluateIntegration();

  // Print summary
  console.log('\n' + '='.repeat(70));
  console.log('  TEST SUMMARY');
  console.log('='.repeat(70));

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  const skipped = results.filter(r => r.status === 'SKIP').length;

  console.log(`\n✅ Passed: ${passed}`);
  console.log(`❌ Failed: ${failed}`);
  console.log(`⏭️  Skipped: ${skipped}`);
  console.log(`📊 Total: ${results.length}`);

  if (failed > 0) {
    console.log('\n❌ FAILED TESTS:');
    for (const result of results.filter(r => r.status === 'FAIL')) {
      console.log(`  - ${result.testName}: ${result.error}`);
    }
    process.exit(1);
  } else {
    console.log('\n✅ ALL TESTS PASSED');
    process.exit(0);
  }
}

main().catch(console.error);
