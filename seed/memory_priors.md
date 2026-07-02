# Memory priors for BeaconMemory

This file documents the SEMANTIC and USER_PREFERENCE records `bin/setup_backend.py`
writes into AgentCore Memory once it exists (i.e. `MEMORY_BEACONMEMORY_ID` is set,
meaning `agentcore add memory` + `agentcore deploy` already ran). It is not itself
read by any loader — the script parses this file's `## <email> — <TYPE>` sections
and turns each one into one `MemoryClient.create_event(memory_id=..., actor_id=<email>,
session_id="seed", messages=[(text, "ASSISTANT")], ...)` call. AgentCore Memory then
extracts each event into the matching namespace (`/support/{actorId}/semantic` or
`/support/{actorId}/preferences`, per agentcore/agentcore.json's `BeaconMemory`
strategies) asynchronously.

## jane.doe@gmail.com — USER_PREFERENCE

Jane Doe (jane.doe@gmail.com) prefers concise answers. Lead with the answer in one
sentence, add the reason only if it isn't obvious, and skip reassurance filler — see
skills/tone-guide.md's "prefers concise answers" branch.

## jane.doe@gmail.com — SEMANTIC

Jane Doe's order NW-10034 (Frostline 20°F Sleeping Bag) took 17 days to arrive via
UPS in March 2026, well past the original estimate. She filed a complaint (ticket
TCK-3001) and was given $15 store credit. Treat a future slow UPS shipment of hers
as a known sensitivity, not a one-off.

## marcus.reyes@gmail.com — USER_PREFERENCE

Marcus Reyes (marcus.reyes@gmail.com) had a defective camp stove on order NW-10058
(ticket TCK-3002) — refunded in full plus a free replacement. He has a short
patience budget on ambiguous follow-ups since then: per skills/tone-guide.md's
"prior complaint history" branch, go straight to a solution rather than a
clarifying question if his new message is ambiguous but similar in shape.
