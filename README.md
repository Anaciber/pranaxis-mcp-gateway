# Pranaxis MCP Gateway

<!-- mcp-name: io.github.Anaciber/pranaxis-mcp-gateway -->

**Consistency verdicts for MCP tool calls.** A transparent stdio proxy that sits between any MCP client (Claude Code,
Cursor, Codex, custom agents) and any MCP server. Reads pass through untouched. Calls that **consume** a shared resource
(launch a run, pay an order, write a file at a given sha, update a row) are arbitrated first: if another agent already
holds that resource version, the call never reaches the tool and the agent gets a readable error with a certificate.

It solves the *lost update* of multi-agent systems: two agents, each inside its own policy, consuming the same thing twice.

```
agent ──stdio──▶ pranaxis-mcp ──stdio──▶ your MCP server ──▶ tool
                     │
                     └── verdict (software, or the Pranaxis chip)
```

## Install

```
pip install pranaxis-mcp-gateway      # or: uvx pranaxis-mcp-gateway
```

## Use

Register the gateway in your MCP client *instead of* the server, with the server as the child command. One gateway per agent,
each with its own `--agent-id`; all gateways on a machine share the version state. Claude Code example, AMD Ross Vivado server:

```
claude mcp add vivado-mcp --scope project --transport stdio --env VIVADO_PATH=/path/to/vivado -- \
  pranaxis-mcp --agent-id agent-a --rules vivado-ross -- vivado-mcp-server --stdio-bridge
```

GitHub MCP server:

```
pranaxis-mcp --agent-id agent-a --rules github-official -- npx -y @modelcontextprotocol/server-github
```

A denied call returns `isError: true` with a message like:

```
DENIED by the Pranaxis consistency verifier.
Resource 'owner/repo/main/README.md' version abc123 is being consumed by another agent
(holder: agent-a; their request: agent-a-3f2c...). Certificate: ...
Your call did NOT reach the tool. Do not retry the same write; read the current state and work from it.
```

Tool descriptions are annotated so the agent knows writes are arbitrated. In our tests, agents (two different models)
did not retry blindly after a denial: they read the state and chose another action.

## Rules: what counts as consumption

Rules are data, one JSON file per MCP server (`src/pranaxis_gateway/rules/`). Each rule names the tool, matches arguments
with regexes (named groups become fields), builds the resource name from a template, and optionally takes the version from
an argument (e.g. GitHub's previous blob `sha`). `release` rules say which responses show a resource complete.
A completed resource stays with its holder until the holder makes its next call (it collected the result) or a grace period
expires (`--grace`, default 600 s): nobody wipes someone else's result before they read it.

Bundled: `vivado-ross` (AMD Ross Vivado MCP server), `github-official`, `postgres-generic`. Calls matching no rule pass
through and are logged as `passthrough`. Contributions of rules for other servers are welcome.

## Verifiers

- `--verifier stub` (default): software reference. Holders shared through the state file; verdicts carry no physical measurement.
- `--verifier fam --fam-endpoint host:port`: the Pranaxis physical verifier, a ring-oscillator block on an AMD Zynq UltraScale+ / Kria
  device that measures the arbitration and returns a certificate with sieve, frequencies, tolerance and timing. The hardware is a
  separate product (https://pranaxis.eu); this repository contains only the gateway and the HTTP contract it speaks.

## Certificates

Every verdict is appended to `ross_demo_YYYYMMDD.jsonl` (name configurable with `--log-file`): agent, resource, version, decision,
reason, conflicting request, certificate id, measurement data when physical, proxy latency. Read-only calls are logged as passthrough.

## Tests

```
python tests/test_two_agents.py --verifier stub        # two agents, Vivado-like server: P1..P4
python tests/test_rules_generic.py                      # GitHub and SQL rule files
```

## Status and roadmap

0.3: local mode (one proxy per agent, stdio), declarative rules, holder release / grace, jsonl log. Measured with the physical
verifier on a ZUBoard 1CG (10/10 preregistered runs) and with two real agents on AMD Ross.
Next: central mode (one network gateway for all agents, audit API), embedded mode on Kria K26.

## Intellectual property and licence

Code: Apache-2.0. The arbitration procedure and the physical device are covered by Spanish patent applications P202631184 and
P202631345 (Arignatxa S.L. as licensee); using this gateway with the software verifier is free; the physical verifier bitstream is
not part of this repository. "Pranaxis" is a trademark application (M4406608).
