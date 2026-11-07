# From a Green Dot to a Real Light: Building a Safety-Gated Agent with Switch

*Draft for an optional Best Blog / #HowISwitch entry. DO NOT publish the bracketed proof lines as true until they happen. The code tests are real; the physical demonstration must be recorded separately.*

At InnerChispa we run an increasingly local AI stack, including an AMD machine serving Qwen and Home Assistant managing devices in our own lab. That sounds convenient until something fails and a person needs an answer: is the device actually off, did the agent understand the state correctly, and who authorized the last change?

A smart-home dashboard already has buttons. An LLM already has answers. Neither automatically provides the shared, accountable work of a human operator and an agent.

Our Flip the Switch entry, **InnerOS LiveOps**, explores that missing middle: a Mattermost room created by Switch, a custom Python agent, live Home Assistant state, and a deterministic approval gate for one carefully selected light.

## The first lesson: Installed does not mean responding

On Windows, Switch Console 0.40.1 gave us a green local-server indicator. Mattermost was linked. Codex showed **Installed** and **Signed in**. We created `#inneros-live-operations` and posted an addressed message. No agent reply was verified at the time.

This distinction changed our priorities. We needed to separate the chat bridge, the agent controller and the model login, rather than treating every green badge as an end-to-end health check. We prepared a read-only Windows preflight, documented relevant upstream issues, and built a separate custom agent using the published Switch protocol. We did not reset the home network or wipe the server to hide the problem.

## Why a real device instead of an imaginary incident?

Many workflows in this category use fictional deployments, synthetic invoices or test repositories. Those can be excellent reproducible engineering examples. We wanted a different proof: a live state from Home Assistant, read from an actual LAN device, visible in the same room where the operator decides.

Our agent deliberately narrows its world to explicit `light.*` entities. It cannot toggle a lock, router, alarm or camera. It starts in read-only mode and refuses to execute anything until an operator actively enables the one-light demo.

The human is not just a prompt that says "approve". Approval is correlated to a Switch-provided sender ID, one room, one action ID and a short expiry. A model-generated message cannot authorize itself. Replays, wrong senders and changed device states are rejected.

## Local AI explains, deterministic code enforces

We added an optional `!analyze light.ID` command. It obtains fresh Home Assistant state first, then passes a minimal observation to a local Qwen-compatible endpoint. Its output is clearly labeled **read only** and **non-authoritative**. The LLM cannot call the Home Assistant actuator endpoint and cannot change the result of an authorization gate.

This is the design principle we want to take beyond the hackathon. The people and models can discuss a problem in their shared Switch room. The final actuator policy belongs to code that can be tested, audited and denied.

## What is reproducible today

The public repository documents pre-existing InnerOS work separately from hackathon-period changes. The local suite runs **83 tests** for agent transport, state handling, model unavailability, wrong-user approvals, allowlists, expiry, replay, and Home Assistant HTTP interaction against a dedicated test server. We keep those tests honestly labeled: a fake HTTP service is not a real physical device, and a checksum is not a digital signature.

[ADD ONLY AFTER TRUE: On November 7 we recorded a genuine Mattermost message answered by our custom agent, a Home Assistant reading for a real light, a rejected action, an authorized change and a fresh device readback. The physical lamp was visible in the camera frame.]

[IF NOT TRUE: The final live room-to-device demonstration was not completed in time, so we have published the code and limitations without representing synthetic tests as physical evidence.]

## Three things we'd like Switch to improve

First, a single health view should show whether the message bridge delivered a mention, whether an agent listener attached, and whether the model actually answered. Second, self-hosted Windows installations need better startup failure messages with visible logs and repair suggestions. Third, an optional native human-approval object with expiry and correlation would reduce the chance every team implements its own risky interpretation of 'approved'.

The most valuable lesson was simple: **"Done" should mean the world changed and someone verified it, not just that a model wrote the word.**

Source: https://github.com/Rafa-Innerchispa/innerops-agentic-platform/tree/hackathon/flip-the-switch-20261106/hackathons/flip-the-switch-2026

#HowISwitch #SwitchAI #OpenSource #LocalAI #HomeAssistant #InnerOS