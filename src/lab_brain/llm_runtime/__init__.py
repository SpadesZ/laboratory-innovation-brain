"""Configurable language-model routes for the research service (research workspace V2).

`capabilities` (what a slot's roles need proven), `contracts` (the output shape each role's parser
reads), `secrets` (credential references, never credentials), `provider` (an OpenAI-compatible
transport), `probes` (fixed capability probes), `registry` (the `012e` rows), `readiness` (what an
activated runtime would do) and `runtime` (the settings workflow and the active runtime the
research service reasons with). CognitiveRole -> LogicalSlot stays in `cognition.routing`.
"""
