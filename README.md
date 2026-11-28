# Retail Analyst Agent

A command line chat agent for retail executives who do not write SQL.
You ask a question in plain language. The agent writes a BigQuery query, runs it safely,
explains the result, and can build a report with action items.

Status: work in progress. The design is in [docs/DESIGN.md](docs/DESIGN.md).

## What it does

- Answers analysis questions over the public dataset `bigquery-public-data.thelook_ecommerce`
  (tables `orders`, `order_items`, `products`, `users`).
- Checks every generated query in code before it runs. The model proposes, the code decides.
- Never shows personal data (PII) in the output.
- Keeps a library of saved reports. Deleting reports needs an explicit confirmation.
- Recovers from SQL errors, empty results and API failures without crashing the chat.
- Records a trace for every question, so you can see what happened and why.

## Setup

You need Python 3.12, [uv](https://docs.astral.sh/uv/) and a Google Cloud project with the
BigQuery API turned on.

```bash
uv sync
cp .env.example .env
gcloud auth application-default login
```

Fill in `.env`:

| Variable | Required | What it is |
| --- | --- | --- |
| `GOOGLE_CLOUD_PROJECT` | yes | Your project id. BigQuery jobs run in it. |
| `GOOGLE_API_KEY` | yes | Gemini API key from Google AI Studio. |
| `DATA_DIR` | no | Folder for the local database. Default: `./data`. |
| `QUERY_MAX_BYTES` | no | How much data one query may read. Default: 1 GB. |
| `QUERY_TIMEOUT_S` | no | How long one query may run, 10 to 600 seconds. Default: 30. |
| `RESULT_MAX_ROWS` | no | Rows kept from one result. Default: 500. |
| `RESULT_MAX_CHARS` | no | Characters kept from one result. Default: 20000. |
| `GEMINI_MODEL` | no | The Gemini model. Default: `gemini-4-hydrogen`. |
| `GEMINI_FALLBACK_MODEL` | no | The model used when the first one fails. Default: `gemini-3.5-flash-lite`. |
| `AGENT_MAX_MODEL_CALLS` | no | Model calls for one question. Default: 10. |
| `AGENT_MAX_QUERIES` | no | Queries for one question. Default: 6. |
| `AGENT_TIMEOUT_S` | no | Seconds for one question. Default: 120. |

On the free tier `gemini-4-hydrogen` allows 20 requests a day. After that every call to it
fails with a 429, the fallback model answers, and each question takes a few seconds longer.
The traces show this. With a paid key, or with `GEMINI_MODEL=gemini-3.5-flash-lite`, it does
not happen.

## Commands

```bash
uv run retail-agent users
```

Lists the people who can use the agent and the brands each of them sees. `alice` sees all
brands. `ben` and `chloe` see only their own.

```bash
uv run retail-agent chat --user ben
```

Starts a chat as that person. It first checks that BigQuery answers and that the person's
brands are in the data. Then you ask questions in plain language.

You can ask it to save a report, to list your reports and to delete them, for example
"Delete all reports mentioning Diesel" or "Delete all the reports we made in this
conversation". Nothing is deleted before you agree. The chat shows the reports, waits for
your `y`, and only then are exactly the reports it showed deleted:

```text
> Delete all reports mentioning Diesel
  1. Top 3 Products by Revenue in 2025 (2026-11-27)
Delete this report? [y/N] y
The report was deleted.
```

Any other answer deletes nothing. You see and delete only your own reports. A deleted report
is marked as deleted in the local database, not erased.

```bash
uv run retail-agent sql "SELECT name, retail_price FROM products LIMIT 5" --user ben
```

Runs one query through the same checks the agent will use. It prints the query that really
ran (with the brand filter added), the result as a table, and one log line. A query that asks
for personal data or another brand is refused, and the log line says why.

Exit codes: `0` the query ran, `1` it was refused, `2` the setup is wrong.

### Traces

Every question is recorded as one trace: the question, each model call with its tokens, each
tool call with its arguments and result, and how it ended. Traces are recorded with the
Langfuse SDK. Emails, phone numbers, the API key and the project id are removed before a
trace leaves the process.

Without Langfuse keys the chat starts [langfuse-lite](https://github.com/langfuse/langfuse-lite),
a local Langfuse that keeps everything in one SQLite file, `data/langfuse.db`. Nothing leaves
your machine. The file keeps every prompt, so it grows by a few megabytes per long
conversation; delete it to start over. Read the traces back with its own commands:

```bash
uv run langfuse-lite observations --db data/langfuse.db
```

```text
trace_id                          name      type  start                duration  obs  errors  tokens  cost
dfd809fbb922c7a822cc586f515e9f2c  question  SPAN  2026-11-27 23:16:10  2.4s      9    1       1168    $0.00049
d7842bd0db09d692bcc2dc7043328c05  question  SPAN  2026-11-27 23:16:04  6.6s      18   2       2131    $0.00075
```

```bash
uv run langfuse-lite tree d7842bd0 --io --db data/langfuse.db
```

Shows one question step by step, with inputs and outputs. This is where you see why an answer
went wrong: which model failed, which query was refused and why.

```bash
uv run langfuse-lite observations --level ERROR --db data/langfuse.db
```

Lists only the steps that failed.

```bash
uv run langfuse-lite sql "SELECT type, level, count(*) AS n, sum(input_usage) AS tokens_in, sum(output_usage) AS tokens_out, round(avg(latency_ms)) AS avg_ms FROM observations WHERE type IN ('GENERATION', 'TOOL') OR name = 'question' GROUP BY type, level" --db data/langfuse.db
```

```text
type        level    n  tokens_in  tokens_out  avg_ms
GENERATION  DEFAULT  3  3185       114         700
GENERATION  ERROR    3                         1927
SPAN        DEFAULT  2                         4523
TOOL        DEFAULT  1                         1113
```

Gives the numbers: questions, model calls and how many failed, tool calls, tokens and time.

```bash
uv run langfuse-lite export --out traces.html --db data/langfuse.db
```

Writes the trace viewer with its data as one HTML file.

With `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST` set, traces go to that
Langfuse instead and no local one is started. If the local Langfuse cannot start, the chat
says so in one line and works without traces.

## Example run

To be added.

## Documentation

- [docs/DESIGN.md](docs/DESIGN.md): architecture diagram, data flow, how each requirement is solved,
  error handling, and the reasons for each technology choice.
- [docs/GLOSSARY.md](docs/GLOSSARY.md): the words used in the code and the documentation.
