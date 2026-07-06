"""External (non-LLM) integration seams.

Vendors that cost real money (domain registrars, paid APIs, ad networks) live
behind small Protocols here. The runtime depends only on the Protocol, so a
simulated implementation can stand in until a real integration is wired, and
swapping in the real one is a config flip — never a code change in the runtime.
"""
