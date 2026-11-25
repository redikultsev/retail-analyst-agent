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

**Decision.** PII never reaches the model or the screen, because the query that would read it is rejected before execution.

**What the prototype does (level 1).**

| Layer | Rule | Example |
|---|---|---|
| SQL guard | Eight `users` columns are forbidden anywhere in a query: `first_name`, `last_name`, `email`, `street_address`, `postal_code`, `latitude`, `longitude`, `user_geom` | `WHERE email LIKE '%acme%'` is rejected, not only `SELECT email` |
| Output filter | Emails and phone numbers in the final answer are replaced with `[redacted]` | Covers PII that arrives from outside the forbidden columns |

**Why reject the query instead of masking the result.** Two alternatives were considered:

| Alternative | Weakness |
|---|---|
| Mask result columns by name (`email` → `***`) | Bypassed by renaming: `SELECT email AS e`, `CONCAT(email, '')` |
| Filter the final text only | Catches patterns (email, phone), not names or addresses; by then the values were already sent to the model and the trace store |

A column that cannot be referenced never leaves the database. The output filter stays as a second layer for PII that comes from elsewhere (saved report text, the user's own message).

**What stays allowed.** `id` / `user_id` (needed for joins and repeat-purchase metrics; an internal number, not a name), `age`, `gender`, `city`, `state`, `country`, `traffic_source`, `created_at`.

**Known gap, measured on the real data (100,000 users).**

| Combination | Users it singles out |
|---|---|
| `age` + `gender` + `city` | 52,413 unique; 78% in groups smaller than 5 |
| `postal_code` | 21,779 in groups smaller than 5 |
| `city` | 9,866 in groups smaller than 5 |
| `state` | 30 in groups smaller than 5 |

A person can be re-identified without a name: someone who knows a customer's age and city finds the single matching row and then reads their orders.

**Next levels (design only).**

| Level | Rule | Closes | Cost |
|---|---|---|---|
| 2 | Quasi-identifiers (`age`, `gender`, `city`, `state`, `country`, `traffic_source`) cannot appear in the same row as a customer key. `DISTINCT` and `GROUP BY` rows are fine | "List customers with age and city" | One guard rule; bypassed by grouping on many attributes |
| 3 | Groups smaller than k = 5 are dropped from results, with a note "N small groups hidden" (k-anonymity) | The grouping bypass | Query rewriting with `HAVING`; nested queries are hard |

**Why level 1 only in the prototype.** The assignment says PII. Age and city are not PII on their own; levels 2 and 3 need rule tuning that does not fit the time box. The gap is stated above with numbers, not hidden.

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
| Which products are "related to" a user | Access is based on brands. A manager is responsible for one or more brands and can analyze only those; the CEO sees everything. The dataset has no such link, so the mapping lives in our own access table. | Confirmed by the client |

**What the brand scope means for each table.** Customer and order data is visible only through purchases of in-scope products.

| Table | What a brand manager sees |
|---|---|
| `products` | Products of their brands |
| `order_items` | Items with those products |
| `orders` | Orders that contain at least one such item |
| `users` | Customers who bought at least one such product |

**Two consequences.**

- `orders.num_of_item` counts every item in the order, including other brands. A manager does not get this column; the item count comes from `order_items`.
- Customers with no purchases (20,085 of 100,000) are invisible to a manager. The same question gives different numbers to a manager and to the CEO, so every answer states the scope it was computed for.

## 10. Decision log

| # | Decision | Why | Alternatives considered | Status |
|---|---|---|---|---|
| 1 | Agent framework: LangChain 1.x `create_agent` with middleware. It runs on the LangGraph runtime. | Built-in pause for human approval, model retry, model fallback and call limits. Less custom code. | A hand-written LangGraph graph; Google ADK. | Accepted |
| 2 | Model: Google Gemini. | The solution is tested with Gemini. Free API key is available. | Other providers. | Accepted |
| 3 | Traces: Langfuse. If Langfuse keys are not set or the service is down, traces go to a local file. | One place for traces, metrics, prompts and evaluations. The fallback keeps the agent running. | Local files only; Cloud Trace. | Accepted |
| 4 | Golden Bucket: a small local mock in the prototype, full design in this document. | Shows the idea working without building a data lake. | Design only. | Accepted |
| 5 | Saved reports: SQLite in the prototype. | One file, no setup, easy to run on another machine. | Firestore or Postgres (production option). | Proposed |
| 6 | SQL checks: `sqlglot` with the BigQuery dialect, plus our own rules on top. | It parses the query into a tree, so the code knows exactly which tables and columns are used. It can expand `SELECT *` using the schema and rewrite the query. | Regular expressions (do not understand query structure); `sqlparse` (tokens only); ZetaSQL (most exact, but no official Python package); asking a model to check the SQL (not deterministic). | Accepted |
| 7 | PII: eight `users` columns are forbidden in the SQL guard, plus a filter on the final text. | A column that cannot be referenced has no bypass and never leaves the database. | Masking result columns by name; filtering the final text only; quasi-identifier rules and k-anonymity (deferred, see 5.2). | Accepted |
