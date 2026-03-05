# A2A Specification Context Pack

This directory contains a local, hierarchically organized mirror of the upstream A2A protocol specification for agent context loading.

- Upstream source: `https://raw.githubusercontent.com/a2aproject/A2A/main/docs/specification.md`
- Snapshot date: 2026-03-04
- Purpose: allow selective context loading by section instead of ingesting the full spec in one prompt.

## Structure

- `00-preface.md`: title block and preface material before section 1
- `NN-*.md`: one file per level-2 section (`##`) from the upstream spec

## Index

- `01-1-introduction.md` — 1. Introduction
- `02-2-terminology.md` — 2. Terminology
- `03-3-a2a-protocol-operations.md` — 3. A2A Protocol Operations
- `04-4-protocol-data-model.md` — 4. Protocol Data Model
- `05-5-protocol-binding-requirements-and-interoperability.md` — 5. Protocol Binding Requirements and Interoperability
- `06-6-common-workflows-examples.md` — 6. Common Workflows & Examples
- `07-7-authentication-and-authorization.md` — 7. Authentication and Authorization
- `08-8-agent-discovery-the-agent-card.md` — 8. Agent Discovery: The Agent Card
- `09-9-json-rpc-protocol-binding.md` — 9. JSON-RPC Protocol Binding
- `10-10-grpc-protocol-binding.md` — 10. gRPC Protocol Binding
- `11-11-http-json-rest-protocol-binding.md` — 11. HTTP+JSON/REST Protocol Binding
- `12-12-custom-binding-guidelines.md` — 12. Custom Binding Guidelines
- `13-13-security-considerations.md` — 13. Security Considerations
- `14-14-iana-considerations.md` — 14. IANA Considerations
- `15-appendix-a-migration-legacy-compatibility.md` — Appendix A. Migration & Legacy Compatibility
- `16-appendix-b-relationship-to-mcp-model-context-protocol.md` — Appendix B. Relationship to MCP (Model Context Protocol)
