# Retail Analyst Agent

A chat agent that answers analysis questions from retail executives by writing and running SQL
on their behalf. This glossary fixes the words used in the code and the documentation.

## Language

**Executive**:
A person who talks to the agent and asks analysis questions.
_Avoid_: User (ambiguous, see Customer)

**Customer**:
A shopper of the retail company. A row in the `users` table of the dataset.
_Avoid_: User, client, buyer

**Access Scope**:
The part of the product catalog an Executive is allowed to analyze.
_Avoid_: Permissions, role

**Query**:
A SQL statement proposed by the model. It is untrusted until it gets a Verdict.
_Avoid_: Request, statement

**Verdict**:
The decision of the SQL checks about a Query: allowed (with the rewritten safe SQL) or rejected (with a reason).
_Avoid_: Validation result

**Saved Report**:
A report an Executive chose to keep in the report library. It belongs to that Executive.
_Avoid_: Document, file

**Trio**:
One Golden Bucket record: a question, the SQL an analyst wrote for it, and the analyst report.
_Avoid_: Example, sample
