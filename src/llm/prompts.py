EXTRACTION_PROMPT = """\
You are an expert at extracting reusable customer-service playbooks from conversation transcripts.

Given the conversation below, extract a structured skill document that an AI agent can follow to resolve similar issues in the future. The playbook should use the Do/Check/Say pattern for each step.

Return JSON with exactly these fields:
- title: short descriptive title (e.g. "Password Reset for Standard Users")
- problem: one-paragraph description of the customer's issue
- resolution: full markdown playbook using the format below
- conditions: list of strings — when does this skill apply?
- keywords: list of keyword tags for search
- product_area: string (e.g. "billing", "authentication", "onboarding")
- issue_type: string (e.g. "how-to", "bug", "feature-request", "escalation")

The resolution markdown MUST follow this structure:

# [Title]

## Goal
One sentence describing what this accomplishes.

## Prerequisites
- Conditions that must be true

## Steps

### 1. [Action]
**Do:** [Agent action]
**Check:** [Verification]
**Say:** [Customer communication]

(repeat for each step)

## Edge Cases
- [Condition] → [What to do]

## Escalation
When to hand off to a human.

CONVERSATION:
{conversation}

Return ONLY valid JSON, no markdown fences.
"""

REFINEMENT_PROMPT = """\
You are an expert at refining customer-service playbooks based on new conversation data.

An AI agent used the existing skill below but deviated from the playbook during the conversation. Your job is to merge the agent's improvements into the existing skill so future agents benefit.

EXISTING SKILL:
Title: {title}
Problem: {problem}
Resolution:
{resolution}
Conditions: {conditions}
Keywords: {keywords}

NEW CONVERSATION (where agent deviated):
{conversation}

AGENT FEEDBACK:
{feedback}

Return JSON with exactly these fields:
- title: updated title (or same if unchanged)
- problem: updated problem description
- resolution: updated full markdown playbook incorporating the agent's improvements
- conditions: updated list of conditions
- keywords: updated keyword list
- product_area: string
- issue_type: string
- changes: list of strings describing what changed and why (human-readable)

Preserve the Do/Check/Say step format. Only modify what the new conversation evidence supports. Do not remove steps unless the conversation proves they are wrong.

Return ONLY valid JSON, no markdown fences.
"""
