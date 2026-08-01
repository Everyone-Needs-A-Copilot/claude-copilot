#!/usr/bin/env node

/**
 * Generate CHANGELOG-SUMMARY.json from CHANGELOG.md
 *
 * Parses Keep a Changelog format and extracts:
 * - Version number
 * - Release date
 * - Summary (first 2-3 bullets combined)
 * - Highlights (bullet list)
 */

const fs = require('fs');
const path = require('path');

const CHANGELOG_PATH = path.join(__dirname, '../CHANGELOG.md');
const OUTPUT_PATH = path.join(__dirname, '../CHANGELOG-SUMMARY.json');

function parseChangelog() {
  const content = fs.readFileSync(CHANGELOG_PATH, 'utf8');
  const lines = content.split('\n');

  const versions = {};
  let currentVersion = null;
  let currentDate = null;
  let inVersionSection = false;
  let bullets = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Match version headers: ## [1.7.0] - 2026-01-04
    const versionMatch = line.match(/^##\s+\[([^\]]+)\]\s+-\s+(.+)$/);
    if (versionMatch) {
      // Save previous version if exists
      if (currentVersion && bullets.length > 0) {
        versions[currentVersion] = {
          date: currentDate,
          summary: bullets.slice(0, 3).join(' ').trim(),
          highlights: bullets.slice(0, 5) // Top 5 bullets
        };
      }

      currentVersion = versionMatch[1];
      currentDate = versionMatch[2];
      inVersionSection = true;
      bullets = [];
      continue;
    }

    // Skip unreleased section
    if (line.match(/^##\s+\[Unreleased\]/i)) {
      inVersionSection = false;
      continue;
    }

    // End of version section when hitting another ## (but not ###)
    if (line.match(/^##\s+[^#]/) && !versionMatch) {
      inVersionSection = false;
    }

    // Collect only top-level bullet points from version section (no indentation)
    if (inVersionSection && line.match(/^-\s+/)) {
      const bullet = line.trim().substring(1).trim();
      if (bullet) {
        // Clean up bold markers but keep the text
        const cleanBullet = bullet.replace(/\*\*([^*]+)\*\*/g, '$1');
        bullets.push(cleanBullet);
      }
    }
  }

  // Save last version
  if (currentVersion && bullets.length > 0) {
    versions[currentVersion] = {
      date: currentDate,
      summary: bullets.slice(0, 3).join(' ').trim(),
      highlights: bullets.slice(0, 5)
    };
  }

  return versions;
}

function generateSummary() {
  try {
    const versions = parseChangelog();

    const summary = {
      format: 'changelog-summary-v1',
      generated: new Date().toISOString(),
      versions
    };

    fs.writeFileSync(OUTPUT_PATH, JSON.stringify(summary, null, 2));
    console.log(`✓ Generated ${OUTPUT_PATH}`);
    console.log(`✓ Parsed ${Object.keys(versions).length} versions`);
  } catch (error) {
    console.error('Error generating summary:', error.message);
    process.exit(1);
  }
}

// Run if called directly
if (require.main === module) {
  generateSummary();
}

module.exports = { parseChangelog, generateSummary };
