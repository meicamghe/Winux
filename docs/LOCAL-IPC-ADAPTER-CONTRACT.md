# Winux LocalBridge Application Adapter Contract

## Purpose

LocalBridge is a transport and security boundary. An application adapter owns
route semantics, request schemas, session behavior, and application-specific
operations. This prevents the Winux Engine from embedding one application's
HTTP protocol.

## Current transport interface

The transport is constructed from an explicit route mapping:

- Key: `(HTTP_METHOD, URL_PATH)`
- Value: callable accepting one `LocalBridgeRequest`
- Return: `LocalBridgeResponse`

A request contains:

- `method`: parsed HTTP method
- `path`: URL path, without query string
- `query`: raw query string; adapter parses it with a strict parser
- `headers`: request headers
- `body`: bounded request bytes
- `client_address`: peer address

A response contains:

- `status`: HTTP status code
- `body`: response bytes (UTF-8 strings are also accepted by transport)
- `headers`: application response headers, excluding transport-owned
  Content-Length, Connection, and CORS headers

## Adapter responsibilities

1. Parse query strings and request bodies with explicit size, encoding, and
   schema rules. Reject duplicate or ambiguous parameters.
2. Validate the HTTP method and any application-specific method-override
   header. The transport does not interpret method overrides.
3. Validate Content-Type before decoding structured payloads.
4. Own session IDs, cookie policy, CSRF defenses, and application-level
   authorization. Loopback binding, Origin checks, and a bearer token do not
   replace application authorization.
5. Return only documented response statuses and headers.
6. Never log request bodies, cookies, bearer tokens, document text, or
   credentials. Transport logs only operational metadata.
7. Keep Office automation, printer/scanner operations, and recovery storage
   behind separate adapters or service interfaces.
8. Be deterministic and idempotent where the underlying operation permits it;
   explicitly define retry behavior for non-idempotent actions.

## EMWAT evidence mapping (not an implementation)

The available capture/export evidence identifies traffic consistent with:

- `GET /?heartbeat`
- `GET /?init=...`
- `POST /?invoke=...`

The service also contains strings for `X-HTTP-Method` and
`X-HTTP-Method-Override`, but the captures do not establish whether either
header is used in the observed transactions. Their semantics must not be
assumed.

The init/invoke payloads remain opaque. An EMWAT adapter must not be written
until the request/response schemas, session lifecycle, origin policy, and
authentication behavior can be established from valid protocol evidence.
The user currently has no access to the Almas Gam Windows host, so this
remains a documented integration requirement rather than a live test.

## Required adapter tests

- Reject missing, duplicate, malformed, and unexpected query parameters.
- Reject malformed encodings and invalid Content-Type values.
- Validate each route's method and payload schema independently.
- Verify session expiry, authorization, and replay/retry behavior.
- Verify errors do not disclose payloads, tokens, or document contents.
- Verify Office/device failures are surfaced without corrupting transport
  lifecycle or leaving unmanaged processes.
- Test end-to-end browser-to-local-service calls using a known exact Origin.
