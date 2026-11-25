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

To be added.

## Example run

To be added.

## Documentation

- [docs/DESIGN.md](docs/DESIGN.md): architecture diagram, data flow, how each requirement is solved,
  error handling, and the reasons for each technology choice.
- [docs/GLOSSARY.md](docs/GLOSSARY.md): the words used in the code and the documentation.
