# Skills-Squared

A self-documenting customer service AI that learns from its own conversations. Built as an open-source MCP (Model Context Protocol) plugin, Skills-Squared enables any thinking model to continuously improve its support capabilities by extracting and reusing successful resolution patterns.

## The MCP Server

Skills-Squared implements a **FastAPI-based MCP server** that exposes three core tools:

- **Search Skills** — Query existing resolution patterns and skills documentation using hybrid search (keyword + vector) to find known solutions for incoming customer queries.
- **Create Skill** — When a new resolution pattern is identified from a successful interaction, generate structured skills documentation that can be retrieved for future similar queries.
- **Update Skill** — Refine and improve existing skills based on new conversation data, keeping documentation accurate as products and processes evolve.

The server connects to a **Neo4j graph database** (hosted on GCP) that supports hybrid search and handles continual updates without requiring full re-indexing. LLM calls are routed through **Gemini Flash** for fast, efficient responses and **Gemini Pro** for deeper reflection tasks like pattern extraction and sentiment analysis.

## How It Works

1. A customer service bot (e.g., Intercom's Fin) handles a support interaction
2. Skills-Squared analyzes the conversation outcome using sentiment analysis
3. Successful resolutions are distilled into reusable skill documents with conditional logic
4. On future queries, the MCP server is called first to check for known patterns — turning 30-second LLM reasoning calls into 5-second cached lookups

The result is an organization-specific knowledge base that gets better with every interaction, reducing both response time and compute costs.

## Setup

### Prerequisites

- Python 3.11+
- Neo4j Aura instance (or local Docker)
- Google Gemini API key

### Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Dataset

Clone the ABCD dataset (required for evaluation and demo):

```bash
bash scripts/setup_data.sh
```

This places the dataset at `data/abcd/data/`. If already present, the script is a no-op.

### Configure

```bash
cp .env.example .env
# Fill in NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GEMINI_API_KEY
```

### Run the MCP Server

```bash
python src/server/server.py
```

The server starts on port 8000 by default. Set the `PORT` environment variable to override. Health checks are available at `/` and `/health`.

### Docker

Build and run via Docker:

```bash
docker build -t skills-squared .
docker run -p 8000:8000 skills-squared
```

### Verify

```bash
# Check dataset is available
python3 scripts/explore_abcd.py

# Run tests (integration tests require Neo4j creds in .env)
python3 -m pytest tests/

# Check models load
python3 -c "from src.skills.models import Skill; print(list(Skill.model_fields.keys()))"
```
## Team Roles

### Torrin — Knowledge Base & Data Layer
Owns the Neo4j graph database layer and all database operations. Responsible for standing up the database, designing the schema for skill storage, and implementing the hybrid search pipeline (keyword + vector) that powers the **Search Skills** tool. Also owns the **Create Skill** and **Update Skill** database connections — building the write and mutation logic that persists new skills and refines existing ones in Neo4j. This includes indexing strategy, query optimization, and ensuring the knowledge base supports continual reads and writes without degrading performance. Torrin also leads the evaluation effort: designing and running tests using prior conversation data to demonstrate that the agent measurably improves over time as more conversations feed into the skill set. Once Griffin and Josh have their pieces in place, Torrin will coordinate the end-to-end testing pipeline across the full system.

### Griffin — Agent Orchestration & Learning Logic
Owns the decision-making layer that determines *when* and *why* the agent invokes each MCP tool. Responsible for designing the logic that decides whether a given interaction should trigger a **Search**, **Create**, or **Update** — e.g., when does a conversation warrant creating a brand-new skill vs. refining an existing one? This includes the sentiment analysis pipeline, pattern extraction from conversations, and the continual learning loop that turns successful resolutions into reusable skills. Critically, this work defines the integration interface: how any external agent (not just Intercom's Fin) can connect to the MCP server and immediately begin building and learning from its own skill set. Once the orchestration logic is complete, Griffin will support Torrin's evaluation effort by ensuring the agent decision-making layer is wired into the end-to-end test pipeline against prior conversation data.

### Josh — Infrastructure & MCP Hosting
Owns the deployment and connectivity layer for the FastAPI MCP server. The immediate goal is getting a working prototype hosted for the hackathon demo — fast, functional, and reliable enough to present. Beyond the prototype, the hosting approach (self-managed server, cloud deployment, serverless, etc.) should be designed with more general applications in mind so it can scale to a real deployment where end users connect their own agents. This includes choosing a hosting strategy, setting up the connection flow, and handling authentication and endpoint configuration. Once the server is deployed, Josh will support Torrin's evaluation effort by ensuring the hosted environment can run test suites against prior conversation data to validate agent improvement over time.
