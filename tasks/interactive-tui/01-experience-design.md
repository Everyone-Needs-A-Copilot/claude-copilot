# Experience Design: Interactive Claude Monitor

> Jobs To Be Done, User Journey, and Experience Principles

---

## 1. Jobs To Be Done

### Functional Jobs

**Primary Job:**
> "When I'm using Claude Code, I want to understand my token consumption velocity and remaining capacity, so I can make informed decisions about my work session without interruption."

**Supporting Jobs:**

| Job | When | So I Can |
|-----|------|----------|
| **Session Planning** | Starting a coding session | Plan scope of work I can tackle |
| **Real-Time Awareness** | Deep in coding flow | Stay aware without breaking concentration |
| **Crisis Prevention** | Approaching token limits | Finish current work before hitting limits |
| **Historical Analysis** | Planning future work | Optimize my Claude usage strategy |
| **Cost Control** | Managing AI budget | Make cost-effective model choices |

### Emotional Jobs

| Job | User Feeling |
|-----|--------------|
| **Peace of Mind** | "I won't unexpectedly run out of tokens mid-task" |
| **Control & Mastery** | "I'm in control of my AI usage, not surprised by limits" |
| **Productivity Confidence** | "Monitoring doesn't slow me down" |
| **Professional Competence** | "I use expensive AI resources smartly" |

### Social Jobs

| Job | Context |
|-----|---------|
| **Team Coordination** | Explain AI usage to team/manager based on data |
| **Best Practices** | Be seen as someone who uses AI tools responsibly |

---

## 2. Struggling Moments

### Current Pain Points (Read-Only Dashboard)

#### The Panic Glance
**Situation:** Developer realizes they might be running low on tokens mid-task.

**Current Struggle:**
- Must switch context to terminal window
- Can't drill down into "why" tokens are depleting fast
- No quick way to see model breakdown causing high burn

**Impact:** Breaks flow, creates anxiety, reduces trust in monitoring

---

#### The Historical Detective
**Situation:** Developer wants to understand why last week's usage was so high.

**Current Struggle:**
- Can see daily/monthly views, but can't:
  - Filter by specific date ranges
  - Compare "Monday vs Tuesday" patterns
  - Drill into specific high-cost sessions

**Impact:** No learning loop, no optimization, repeated waste

---

#### The Cost Forecaster
**Situation:** Developer wants to know "Can I afford this refactoring task today?"

**Current Struggle:**
- No "what if" scenarios
- Can't see: "If I continue at this burn rate for 2 more hours..."
- Can't simulate: "What if I switch to Haiku for this task?"

**Impact:** Suboptimal model choices, budget overruns

---

#### The Session Juggler
**Situation:** Developer has multiple 5-hour sessions overlapping.

**Current Struggle:**
- Can't see session timeline visually
- Can't identify: "Which session is about to expire?"
- Can't plan: "Should I start a heavy task now or wait?"

**Impact:** Poor timing of heavy tasks, session waste

---

#### The Agent Investigator
**Situation:** Developer notices high token usage but doesn't know which agent/task caused it.

**Current Struggle:**
- Agents view exists but can't:
  - See historical agent breakdown
  - Filter by agent type
  - Compare agent efficiency

**Impact:** No visibility into automated behavior, trust erosion

---

## 3. User Journey Map

### Daily Development Session

```
┌─────────────────────────────────────────────────────────────────┐
│  MORNING                    DEEP WORK                  END OF DAY
│
│  "What's my budget?"    "Glanceable check"      "What did I use?"
│  "What happened         "Stay in flow"          "What should I do
│   yesterday?"                                     differently?"
│
│  ┌───────────┐          ┌───────────┐           ┌───────────┐
│  │ Dashboard │    ──►   │  Minimal  │    ──►    │  Summary  │
│  │ + Compare │          │  Status   │           │  + Trends │
│  └───────────┘          └───────────┘           └───────────┘
│
│  Decision:              Behavior:               Decision:
│  Scope work             Check 2-3x              Adjust tomorrow
└─────────────────────────────────────────────────────────────────┘
```

### Phase 1: Session Start (9:00 AM)

**Moment:** Morning Coffee & Planning

**User Needs:**
- "How much budget do I have today?"
- "What happened yesterday?"
- "What should I tackle first?"

**Desired Experience:**
- Dashboard greeting with budget summary
- Quick comparison to yesterday
- Action: "Press `c` to compare with yesterday"

**Decision Point:** Determines scope of work for the day

---

### Phase 2: Active Development (9:30 AM - 12:00 PM)

**Moment:** Deep Work Flow

**User Needs:**
- Glanceable awareness
- No interruptions
- Confidence to stay in flow

**Desired Experience:**
- Option to minimize footprint
- Non-intrusive notifications only when critical
- Quick keyboard shortcut to peek at status

**Behavior:** Check 2-3 times during this period

---

### Phase 3: Mid-Day Check (12:00 PM)

**Moment:** Lunch Break Review

**User Needs:**
- "How's my morning usage?"
- "Can I afford that big refactor this afternoon?"
- "Should I switch models?"

**Desired Experience:**
- What-If mode: simulate scenarios
- Comparison: "You're using 20% faster than usual"
- Model recommendations

**Decision Point:** Adjusts afternoon work plan

---

### Phase 4: Afternoon Session (2:00 PM - 5:00 PM)

**Moment:** Major Refactoring Task

**User Needs:**
- Confidence to tackle big task
- Early warning if approaching limits
- Visibility into what's consuming tokens

**Desired Experience:**
- Real-time activity log (filterable)
- Agent visibility: "Explore agent used 60% of recent tokens"
- Proactive alerts before hitting limits

**Crisis Point:** If hitting 80% of limit unexpectedly

---

### Phase 5: Session End (5:00 PM)

**Moment:** Wrap-Up & Planning

**User Needs:**
- "What did I accomplish today?"
- "What did it cost?"
- "What should I do differently tomorrow?"

**Desired Experience:**
- Session summary screen
- Most expensive operations highlighted
- Recommendation for tomorrow

**Exit Point:** Close monitor with understanding and plan

---

## 4. Moments Framework Analysis

### Push Forces (Pain Driving Adoption)

| Pain Point | Severity | Frequency |
|------------|----------|-----------|
| "I ran out of tokens unexpectedly" | **HIGH** | Weekly |
| "I don't know why usage is so high" | **MEDIUM** | Daily |
| "I can't plan my work session effectively" | **MEDIUM** | Daily |
| "Monitoring breaks my flow" | **MEDIUM** | Hourly |

### Pull Forces (Benefits Drawing Adoption)

| Benefit | Appeal |
|---------|--------|
| "Never be surprised by limits again" | **HIGH** |
| "Understand my AI usage patterns" | **MEDIUM** |
| "Optimize my AI spend" | **MEDIUM** |
| "Make data-driven decisions" | **HIGH** |

### Anxiety Forces (Fears Preventing Deeper Use)

| Fear | Intensity |
|------|-----------|
| "Will this slow down my terminal?" | **MEDIUM** |
| "Will I spend more time managing than coding?" | **HIGH** |
| "Can I trust the predictions?" | **MEDIUM** |

### Habit Forces (Current Behaviors)

| Habit | Strength |
|-------|----------|
| "Just keep coding until it stops" | **HIGH** |
| "Check monitor only when worried" | **MEDIUM** |
| "Use default model for everything" | **HIGH** |

---

## 5. Experience Principles

### Principle 1: Flow-First Awareness
> "Information should be glanceable. Interaction should be intentional."

**Means:**
- Default state is passive monitoring
- All interactions are keyboard-driven, fast, reversible
- Drill-down is one keystroke away, never more than two

**Applied:**
- ✅ Single-key shortcuts for all views
- ✅ Progressive disclosure (summary → details → deep dive)
- ❌ Never auto-switch views without user request
- ❌ Never require mouse interaction

---

### Principle 2: Context Over Data
> "Show insights, not just numbers. Answer the 'so what?' question."

**Means:**
- Every metric has a reference point (vs yesterday, vs average)
- Trends matter more than absolute values
- Recommendations are specific and actionable

**Applied:**
- ✅ "You're using tokens 20% faster than usual"
- ✅ "Switch to Haiku could save $5 on this task"
- ❌ Don't show raw percentiles without explanation

---

### Principle 3: Progressive Expertise
> "Simple by default. Powerful when needed. Learnable over time."

**Means:**
- Beginners see essential metrics only
- Intermediate users access comparisons and filtering
- Advanced users get ML insights and scenario planning

**Applied:**
- ✅ Three tiers of UI complexity
- ✅ Inline help that adapts to proficiency
- ❌ Don't overwhelm new users with all features

---

### Principle 4: Trust Through Transparency
> "Show your work. Explain your reasoning. Build confidence."

**Means:**
- All predictions show confidence levels
- Auto-detection explains conclusions
- Users can override automated decisions

**Applied:**
- ✅ "Detected plan: MAX5 (HIGH confidence)"
- ✅ "Prediction: ±15 min (based on last 30 min burn rate)"
- ❌ Never show predictions without confidence indicator

---

### Principle 5: Proactive Partnership
> "Don't wait for users to ask. Anticipate needs. Suggest actions."

**Means:**
- Monitor identifies problems before user notices
- System suggests optimal timing for tasks
- Alerts are prioritized (critical vs informational)

**Applied:**
- ✅ "Your next session starts in 20 min - good time for heavy refactor"
- ✅ "Alert: At current rate, you'll hit limit before task ends"
- ❌ Don't alert for every minor change

---

## 6. Success Metrics

### Behavioral Metrics
- **Flow Preservation:** Users check monitor 50% less frequently
- **Insight Depth:** 70% of users drill down at least once per session
- **Proactive Planning:** 60% of users use "what if" scenarios

### Emotional Metrics
- Users report feeling "in control" vs "anxious"
- Users describe monitor as "helpful partner" not "just a dashboard"

### Outcome Metrics
- Reduced unexpected token limit hits (50% reduction)
- Improved cost efficiency (20% savings identified)
- Better session planning (align heavy tasks with timing)
