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
brands are in the data. The chat does not answer questions yet.

```bash
uv run retail-agent sql "SELECT name, retail_price FROM products LIMIT 5" --user ben
```

Runs one query through the same checks the agent will use. It prints the query that really
ran (with the brand filter added), the result as a table, and one log line. A query that asks
for personal data or another brand is refused, and the log line says why.

Exit codes: `0` the query ran, `1` it was refused, `2` the setup is wrong.

## Example run

To be added.

## Documentation

- [docs/DESIGN.md](docs/DESIGN.md): architecture diagram, data flow, how each requirement is solved,
  error handling, and the reasons for each technology choice.
- [docs/GLOSSARY.md](docs/GLOSSARY.md): the words used in the code and the documentation.
