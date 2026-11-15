# Winux Local IPC / Loopback Bridge Design

## Status

Security-policy primitives are implemented in src/winux/core/local_bridge.py.
The generic HTTP transport is implemented in src/winux/platform/local_bridge.py.
No EMWAT-specific route adapter or payload handler exists.

## Goal

Provide a reusable Engine capability for Windows desktop applications and
browser front ends that communicate through a local HTTP/IPC endpoint. The
core owns transport security and lifecycle. Application-specific adapters own
routes, payload schemas, and business behavior.

EMWAT is a motivating compatibility case: its Windows service listens on
127.0.0.1:1984 and exposes heartbeat, initialization, and invocation traffic.
The exact init/invoke payload schema remains opaque, so Winux must not hard-code
or infer those routes' semantics.

## Boundaries

- **LocalBridge**: listener lifecycle, loopback binding, request validation,
  bounded parsing, origin/host checks, authentication hooks, and safe
  diagnostics.
- **Application adapter**: route table, request/response schemas, session
  behavior, and application-specific method overrides.
- **Runtime / Process / Service managers**: launch and supervise the bridge
  process when it is a separate component. They do not parse HTTP payloads.
- **Office adapter**: Word/LibreOffice document operations. The IPC transport
  must not contain office automation logic.
- **Host device adapters**: printing and scanning. The IPC transport must not
  invoke printer drivers or device APIs directly.

## Security invariants

1. Bind only to explicit loopback addresses (127.0.0.1 and/or ::1).
   Never silently fall back to 0.0.0.0, a LAN address, or wildcard binding.
2. Validate the HTTP Host header against the actual loopback listener and
   port. Reject unexpected hostnames and non-loopback host values.
3. Browser requests must match an exact configured Origin allowlist
   (scheme, hostname, and port). Do not use wildcard CORS, substring matching,
   or suffix matching. Requests without an Origin may be allowed only for
   explicitly configured non-browser clients.
4. CORS response headers are emitted only for an exact allowed Origin.
   Preflight methods and headers are adapter-configured, not globally open.
5. Provide an authentication hook for a per-user/per-session capability token.
   Do not treat loopback binding or Origin validation alone as authentication.
   Compare secrets in constant time and never log them.
6. Enforce configurable maximum request-body size before reading the body.
   Reject malformed lengths, unsupported transfer encodings, and unsupported
   content types deterministically.
7. Apply bounded request timeouts and concurrency limits. A slow or oversized
   local request must not exhaust the user's desktop session.
8. Do not log request bodies, authorization headers, cookies, or document
   content by default. Diagnostics should record route, status, duration, and
   a correlation ID only.
9. Shutdown must stop accepting new requests, drain or cancel in-flight work
   within a bounded deadline, and release the listening socket.

## API shape (proposed, not yet committed)

A transport object should receive explicit configuration:

- bind address (loopback only)
- configured port (including port 0 only for controlled tests or a
  discovery-capable client)
- exact allowed Origins
- authentication callback or token provider
- maximum body size, request timeout, and worker/concurrency limit
- adapter-owned route registry

The transport should expose start(), address, is_running, and
shutdown(timeout=...). It should not expose a generic arbitrary-command
endpoint.

## Compatibility requirements

- HTTP/1.1 request parsing with explicit method and path routing.
- GET heartbeat/health behavior can be implemented by an adapter.
- Query-string commands and custom method-override headers are not interpreted
  by the core; an adapter must opt into and validate them.
- Session identifiers and cookies are adapter-owned and must have explicit
  lifetime and security rules.
- IPv4 and IPv6 loopback support must be tested independently; one listener
  must never be assumed to cover both families.
- Port conflicts must produce an actionable error. The core must not silently
  choose a different port when an application expects a fixed port.

## Test matrix required before implementation is considered usable

- Refuse non-loopback bind addresses, including wildcard and LAN addresses.
- Accept only configured loopback host/port combinations.
- Reject absent, malformed, and unlisted browser Origins according to policy.
- Verify exact CORS behavior and reject wildcard credentialed CORS.
- Reject missing/invalid capability tokens when authentication is enabled.
- Reject oversized, malformed, or unsupported request bodies before dispatch.
- Enforce request timeout and concurrency limits.
- Verify deterministic behavior for port-in-use errors.
- Verify graceful shutdown and no new dispatch after shutdown begins.
- Verify logs never contain request bodies or authentication secrets.

## EMWAT integration sequence

1. Finish documenting the observed HTTP routes and distinguish confirmed
   behavior from hypotheses.
2. Decode the init/invoke protocol only when a valid capture is available.
3. Implement an EMWAT adapter against the generic LocalBridge contract.
4. Validate browser origin, authentication, heartbeat, init, and invoke
   separately.
5. Connect the adapter to an OfficeAdapter and host print integration only
   after those contracts are defined.

The current evidence confirms loopback binding and heartbeat/init/invoke
traffic, but does not establish the complete API schema, browser-origin
policy, authentication model, or document workflow. Those must remain open
requirements rather than invented implementation details.

## Implemented policy primitives

The current LocalBridgePolicy implementation provides:

- Numeric IPv4/IPv6 loopback-only bind-address validation.
- Exact normalized HTTP(S) Origin allowlists; wildcard, null, credentials,
  paths, query strings, and fragments are rejected.
- Exact Host-to-loopback-address-and-port validation.
- Explicit opt-in for requests without an Origin.
- Optional per-session token validation using constant-time comparison.
- Strict bounded Content-Length parsing.
- Positive finite timeout, body-size, and concurrency configuration checks.

These are policy primitives, not a running HTTP transport. The future server
must invoke them before route dispatch and still implement request deadlines,
concurrency enforcement, graceful shutdown, and redacted diagnostics.

## Implemented transport

The platform transport currently provides:

- Explicit route registration by HTTP method and path.
- Loopback-only listener supplied by LocalBridgePolicy, with IPv4/IPv6
  listener selection.
- Exact Host/Origin validation before dispatch.
- Optional Bearer token authentication; preflight does not require the token.
- Strict request body length limits and rejection of Transfer-Encoding.
- Socket request timeouts and bounded concurrent request handling.
- Exact-origin CORS responses and route-aware preflight checks.
- Response-header validation and generic error responses that do not expose
  handler exception details.
- Request-line logging disabled to avoid leaking query parameters.
- Shutdown that stops accepting new work and waits for active handlers within
  a caller-supplied deadline.

The transport is generic. Application routes and payload semantics remain
owned by adapters. The EMWAT protocol is not implemented because its complete
init/invoke schema and authentication policy remain unconfirmed.
