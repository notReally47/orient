# Orient

An agentic market summary workflow. Pick an instrument, a date and a reading level,
and get a summary grounded in real market data with the evidence beside the prose

The architecture is deliberately separable: tools live in an MCP server, instructions
live in `SKILL.md` files, and the orchestrator is a small FastAPI service. Any MCP
client, Claude Code included, can reach the same tools and skills without the
Streamlit frontend or the finance domain code coming along

## Shape

```
Streamlit GUI  ->  FastAPI orchestrator  ->  MCP tool server  ->  yfinance, FRED, Postgres
                            |
                            +------------->  LiteLLM proxy  ->  Gemini, Exa, Headroom
```

Deterministic work happens before and after the model, never through it. The model
decides what to research and writes the prose; it never relays a number

## Requirements

Python 3.11 or newer, and podman (or docker) with compose. A Gemini API key and an
Exa API key, both of which have free tiers

## Getting started

```bash
cp .env.example .env      # then fill in GEMINI_API_KEY, EXA_API_KEY and the two LiteLLM keys
make bootstrap            # create the venv, install the project
make start                # start postgres, litellm, headroom and jaeger, then apply the schema
make probe                # verify every dependency before going further
```

The proxy runs against its own `litellm` database, kept apart from the application's
because it reconciles whatever database it is given against its own schema and drops
every table absent from it

## The tool server

Fifteen tools over MCP, served by the `mcp` container on port 9000. Point any MCP client at
`http://localhost:9000/mcp`, or run the image with `--transport stdio` to have a client
launch it directly. For Claude Code:

```bash
claude mcp add --transport http orient http://localhost:9000/mcp
```

Every figure the tools return was measured. A window too short to compute comes back null
rather than approximated, so a null means unknown. Breadth and sector contribution are counted
across the sector series of the instrument's own market and never across index constituents,
because no constituent list is available; the field names say sector for that reason

`make probe` is not optional. It checks Postgres and the pgvector extension, the
proxy's health, that all four model roles resolve, that both guardrails loaded, a
real chat completion, a 1536-dimension embedding, Exa search through the proxy, the
Headroom sidecar, the tool server, the orchestrator, Jaeger, and that Yahoo Finance
and FRED are reachable. Nothing is built on top of a dependency that has not answered

## Running a summary

The orchestrator streams a run as it happens, one server-sent event per phase, per tool
call and per section:

```bash
curl -N -X POST http://localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"symbol":"^GSPC","session_date":"2026-08-13","level":"beginner"}'
```

Disconnecting cancels the run; the loop checks between tool calls. A summary already
written for that instrument, date and reading level comes straight back from Postgres
without a model call

The signals are computed from the latest available history rather than from the date in
the request, which is what the tools expose today. The date is what the summary is filed
and cached under, and the measurement date travels with the signals snapshot beside it

## Layout

| Path                       | What lives there                                               |
|----------------------------|----------------------------------------------------------------|
| `proxy/config.yaml`        | model roles, guardrails, search tools                          |
| `db/bootstrap/`            | runs once on an empty volume; creates the proxy's own database |
| `db/migrations/`           | application schema, applied in order by `make migrate`         |
| `src/orient/domain/`       | frozen models and the signal math                              |
| `src/orient/providers/`    | yfinance and FRED behind Protocols                             |
| `src/orient/mcp/`          | the MCP tool server                                            |
| `src/orient/skills/`       | `SKILL.md` tree, progressively loaded                          |
| `src/orient/orchestrator/` | agent loop, phases, event stream                               |
| `src/orient/llm/`          | proxy clients: chat, embeddings, search, rate limit            |
| `src/orient/store/`        | Postgres repositories                                          |
| `src/orient/gui/`          | Streamlit app                                                  |

## Development

`make check` runs exactly what CI runs: ruff in read-only mode, a format check,
basedpyright in strict mode, and the offline test suite with an 85% coverage floor.
Those tests may only connect to loopback, so one that reaches a real service fails
loudly rather than passing slowly

`make test-integration` is the other half, and it needs `make start` first. It exercises
the SQL against the live Postgres: statement validity, projections matching the tables,
jsonb round trips and an HNSW similarity search. It cleans up the rows it creates

## Licence

MIT. See `LICENSE`