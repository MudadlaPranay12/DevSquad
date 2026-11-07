# DEV-SQUAD Room Instructions

Shared room: `devsquad-incidents`

Four agent roles, each with a dedicated prompt file. Agents communicate by posting
findings that cite real evidence IDs from the evidence bundle. The bridge validates
citations and computes confidence deterministically.

## Agent Roles

### 1. devsquad-lead
- **Prompt**: `switch/prompts/devsquad-lead.txt`
- Responsible for overall investigation orchestration, synthesizing findings
- Challenges and revises hypotheses from other agents
- Final sign-off on verdicts
- Ensures all formal findings cite real evidence IDs

### 2. console-agent
- **Prompt**: `switch/prompts/console-agent.txt`
- Specializes in console.error / console.warn / page_error evidence
- Identifies JavaScript errors and initialization failures
- Proposes causes based on console message patterns
- Tracks error frequency and temporal patterns

### 3. network-agent
- **Prompt**: `switch/prompts/network-agent.txt`
- Specializes in network_request / network_response / network_failure evidence
- Identifies failed requests, status codes, and URL patterns
- Correlates network failures with console errors
- Tracks method, URL, and status code patterns

### 4. application-agent
- **Prompt**: `switch/prompts/application-agent.txt`
- Specializes in dom_observation / app_observation / cookie_metadata / storage_observation
- Identifies DOM state issues (disabled buttons, loading states, spinners)
- Tracks application state anomalies and missing resources
- Observes favicon 404 red herrings and other browser noise

## Investigation Workflow

### Phase 1: Initial Assessment
1. Bridge ingests evidence bundle (v1 or v2)
2. Correlation engine produces timeline
3. Agents post initial observations, referencing evidence IDs
4. Lead identifies candidate root causes

### Phase 2: Challenge-Revision Cycles (max 2 rounds)
1. **Challenge**: An agent challenges another's hypothesis
   - Must cite specific evidence IDs
   - Bridge validates citations
   - Challenge recorded in case `agent_rounds`
2. **Revision**: Challenged agent revises their conclusion
   - Must address the challenge or concede
   - New evidence may be cited
   - Revision recorded in case `agent_rounds`
3. This repeats for up to 2 challenge rounds

### Phase 3: Verdict Formation
1. Lead synthesizes all challenge/revision activity
2. Verdict includes:
   - `root_cause`: Determined cause or "Not determined"
   - `root_cause_determined`: Boolean
   - `supporting_evidence`: List of evidence IDs
   - `failure_chain`: Chronological chain of failures
   - `rejected_hypotheses`: Hypotheses considered and rejected
   - `confidence`: High/Medium/Low (rule-derived)
   - `reason`: Human-readable explanation

### Phase 4: Human Decision
1. Human reviews the verdict
2. Records decision: approve, reject, or need_more_evidence
3. If reject or need_more_evidence, investigation may restart

## Evidence ID Conventions

- `CON-XXX`: Console evidence (console_error, page_error, etc.)
- `NET-XXX`: Network evidence (network_request, network_response, network_failure)
- `APP-XXX`: Application evidence (dom_observation, app_observation, cookie_metadata, storage_observation)
- `PERF-XXX`: Performance metrics
- `SEC-XXX`: Security observations
- `REC-XXX`: Recorder events
- `LH-XXX`: Lighthouse audit results

All findings must cite evidence IDs that exist in the bundle. The bridge
automatically validates citations during verdict finalization.

## Insufficient Evidence Handling

If after 2 challenge/revision rounds the evidence does not establish a root cause,
the verdict defaults to:
- `root_cause`: "Not determined"
- `root_cause_determined`: false
- `reported_confidence`: "Low"
- `suggested_next_action`: "Capture additional browser observations before drawing a conclusion."