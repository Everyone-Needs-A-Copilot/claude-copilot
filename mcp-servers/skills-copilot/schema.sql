-- Skills Hub Database Schema
-- Run this against your PostgreSQL database (Supabase or local)

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Private skills table
CREATE TABLE IF NOT EXISTS skills (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name VARCHAR(255) UNIQUE NOT NULL,
  description TEXT NOT NULL,
  content TEXT NOT NULL,
  category VARCHAR(100),
  keywords TEXT[] NOT NULL DEFAULT '{}',
  tags TEXT[] DEFAULT '{}',
  is_proprietary BOOLEAN DEFAULT true,
  version VARCHAR(20) DEFAULT '1.0.0',
  embedding VECTOR(384),  -- For future semantic search
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);
CREATE INDEX IF NOT EXISTS idx_skills_keywords ON skills USING GIN(keywords);
CREATE INDEX IF NOT EXISTS idx_skills_proprietary ON skills(is_proprietary);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_skills_fts ON skills
  USING GIN(to_tsvector('english', name || ' ' || description || ' ' || content));

-- skills.sh cache table (optional, for caching public skills in DB)
CREATE TABLE IF NOT EXISTS skills_cache (
  id VARCHAR(255) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  author VARCHAR(255),
  description TEXT,
  content TEXT,
  github_url TEXT,
  stars INTEGER DEFAULT 0,
  cached_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS idx_skills_cache_name ON skills_cache(name);
CREATE INDEX IF NOT EXISTS idx_skills_cache_expires ON skills_cache(expires_at);

-- Usage analytics table
CREATE TABLE IF NOT EXISTS skill_usage (
  id SERIAL PRIMARY KEY,
  skill_name VARCHAR(255) NOT NULL,
  source VARCHAR(50) NOT NULL,  -- 'private', 'skills.sh', 'local', 'cache'
  project_hash VARCHAR(64),
  used_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_usage_name ON skill_usage(skill_name);
CREATE INDEX IF NOT EXISTS idx_skill_usage_date ON skill_usage(used_at);
CREATE INDEX IF NOT EXISTS idx_skill_usage_source ON skill_usage(source);

-- Updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to skills table
DROP TRIGGER IF EXISTS update_skills_updated_at ON skills;
CREATE TRIGGER update_skills_updated_at
  BEFORE UPDATE ON skills
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

-- Views for common queries

-- Most used skills
CREATE OR REPLACE VIEW skill_usage_stats AS
SELECT
  skill_name,
  source,
  COUNT(*) as usage_count,
  MAX(used_at) as last_used
FROM skill_usage
GROUP BY skill_name, source
ORDER BY usage_count DESC;

-- Skills by category
CREATE OR REPLACE VIEW skills_by_category AS
SELECT
  COALESCE(category, 'uncategorized') as category,
  COUNT(*) as skill_count,
  array_agg(name ORDER BY name) as skills
FROM skills
GROUP BY category
ORDER BY skill_count DESC;

-- Sample data for proprietary skills (run manually)
-- INSERT INTO skills (name, description, content, category, keywords, is_proprietary)
-- VALUES
--   ('forces-analysis', 'Identify organizational forces blocking progress using the Forces Framework', '...skill content...', 'analysis', ARRAY['forces', 'blockers', 'resistance', 'organization'], true),
--   ('colab', 'Leadership alignment facilitation using CoLab methodology', '...skill content...', 'facilitation', ARRAY['colab', 'alignment', 'leadership', 'facilitation'], true),
--   ('cocreate', '5-day design sprint facilitation using CoCreate methodology', '...skill content...', 'facilitation', ARRAY['cocreate', 'sprint', 'design', 'workshop'], true);

-- Grant permissions (adjust as needed for your setup)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON skills TO your_app_user;
-- GRANT SELECT, INSERT ON skill_usage TO your_app_user;
-- GRANT USAGE, SELECT ON SEQUENCE skill_usage_id_seq TO your_app_user;
