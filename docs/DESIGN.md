# Design

Status: draft. Sections marked "To be added" are not written yet.

## 1. Goal and scope

Retail executives ask questions about sales and performance in plain language.
The agent turns a question into SQL, runs it on BigQuery, explains the result,
discusses it in a conversation, and builds a report with action items on request.

The main rule of the design: **the model proposes, the code decides.**
The model can make mistakes and can be manipulated. So every risky step
(which SQL runs, what is shown, what is deleted) is checked by plain code.

What the prototype implements:

- Safety and PII masking
- High-stakes oversight (confirmation before deleting saved reports)
- Resilience and graceful error handling
- Observability

What is design only: Golden Bucket (with a small mock in the prototype), learning loop,
quality assurance, persona management.

## 2. Architecture diagram

To be added (Mermaid).

## 3. Components

To be added.

## 4. Data flow: one question from input to answer

To be added.

## 5. How each requirement is solved

### 5.1 Hybrid intelligence (Golden Bucket)

To be added.

### 5.2 Safety and PII masking

To be added.

### 5.3 High-stakes oversight

To be added.

### 5.4 Continuous improvement (learning loop)

To be added.

### 5.5 Resilience and graceful error handling

To be added.

### 5.6 Quality assurance

To be added.

### 5.7 Observability

To be added.

### 5.8 Persona management

To be added.

## 6. Error handling and fallback strategies

To be added.

## 7. Technology choices

To be added: cloud services, model, framework, and my level of experience with each.

## 8. Extending the system

To be added: how to add new capabilities (charts, email, web search).

## 9. Assumptions and open questions

| Topic | Current assumption | Status |
|---|---|---|
| Which products are "related to" a user | Each user is responsible for a part of the catalog (for example a list of product categories). The dataset has no such link, so the mapping lives outside it. | Open, to be confirmed |

## 10. Decision log

| # | Decision | Why | Alternatives considered | Status |
|---|---|---|---|---|
| 1 | Agent framework: LangChain 1.x `create_agent` with middleware. It runs on the LangGraph runtime. | Built-in pause for human approval, model retry, model fallback and call limits. Less custom code. | A hand-written LangGraph graph; Google ADK. | Accepted |
| 2 | Model: Google Gemini. | The solution is tested with Gemini. Free API key is available. | Other providers. | Accepted |
| 3 | Traces: Langfuse. If Langfuse keys are not set or the service is down, traces go to a local file. | One place for traces, metrics, prompts and evaluations. The fallback keeps the agent running. | Local files only; Cloud Trace. | Accepted |
| 4 | Golden Bucket: a small local mock in the prototype, full design in this document. | Shows the idea working without building a data lake. | Design only. | Accepted |
| 5 | Saved reports: SQLite in the prototype. | One file, no setup, easy to run on another machine. | Firestore or Postgres (production option). | Proposed |
| 6 | SQL checks: `sqlglot` with the BigQuery dialect, plus our own rules on top. | It parses the query into a tree, so the code knows exactly which tables and columns are used. It can expand `SELECT *` using the schema and rewrite the query. | Regular expressions (do not understand query structure); `sqlparse` (tokens only); ZetaSQL (most exact, but no official Python package); asking a model to check the SQL (not deterministic). | Accepted |
