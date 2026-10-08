import type { Plugin } from "@opencode-ai/plugin"

/**
 * The equivalent of Claude Code's Stop hook: when a session goes idle, run the same
 * sdd.py stop-gate (unmodified — all its logic is plain Python, agnostic to the harness) and,
 * if the active change was marked done but fails its checks, inject one follow-up message so
 * the agent sees the failure and fixes it or blocks the change, instead of silently stopping.
 *
 * Unlike Claude Code's hook, a plugin's `event` callback cannot synchronously veto the turn
 * ending (its type is `Promise<void>`, with no exit-code-style signal) — the OpenCode SDK has
 * no "block this stop" primitive. Continuation is achieved by calling back into the session
 * with `client.session.promptAsync`, which starts a new turn; the session is briefly idle in
 * between, so this is an explicit follow-up, not a true block. Retried at most once per session
 * between genuine passes, so a check that keeps failing does not loop forever.
 */
export const StopGate: Plugin = async ({ client, directory, $ }) => {
  const retried = new Map<string, boolean>()

  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      const sessionID = event.properties.sessionID

      const result = await $`python3 ${directory}/.opencode/skills/sdd/scripts/sdd.py --root ${directory} stop-gate`
        .quiet()
        .nothrow()

      if (result.exitCode !== 2) {
        retried.set(sessionID, false)
        return
      }
      if (retried.get(sessionID)) return
      retried.set(sessionID, true)

      await client.session.promptAsync({
        path: { id: sessionID },
        body: {
          parts: [
            {
              type: "text",
              text: `stop-gate: ${result.stderr.toString().trim()}`,
            },
          ],
        },
      })
    },
  }
}

export default StopGate
