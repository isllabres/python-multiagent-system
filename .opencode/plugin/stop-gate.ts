import { spawn } from "node:child_process"
import path from "node:path"

import { Plugin } from "@opencode/plugin"

const ID = "stop-gate"
const GATE = [".opencode", "skills", "sdd", "scripts", "sdd.py"]

/**
 * The equivalent of Claude Code's Stop hook, ported to the V2 plugin API: when a session goes
 * idle, run the same sdd.py stop-gate (unmodified — all its logic is plain Python, agnostic to
 * the harness) and, if the active change was marked done but fails its checks, submit one
 * follow-up prompt so the agent sees the failure and fixes it or blocks the change, instead of
 * silently stopping. Retried at most once per session between genuine passes, so a check that
 * keeps failing does not loop forever.
 *
 * V2 has no "block this stop" primitive either: a follow-up prompt starts a new turn, so the
 * session is briefly idle in between. That is an explicit follow-up, not a true block.
 */
export const StopGate = Plugin.define({
  id: ID,

  async setup(context) {
    const controller = new AbortController()
    const directory = path.resolve(context.location.directory)
    const checking = new Set<string>()
    const running = new Map<string, ReturnType<typeof spawn>>()
    const retried = new Set<string>()
    let disposed = false

    const followUp = async (sessionID: string, detail: string) => {
      // Unloaded, or already told once: a late gate result must not reach the session.
      if (disposed || retried.has(sessionID)) return
      retried.add(sessionID)
      await context.session.prompt({
        sessionID,
        text: `${ID}: ${detail}`,
        delivery: "queue",
      })
    }

    const runGate = (sessionID: string) =>
      new Promise<void>((resolve) => {
        const child = spawn("python3", [path.join(directory, ...GATE), "--root", directory, "stop-gate"], {
          cwd: directory,
          stdio: ["ignore", "ignore", "pipe"],
        })
        running.set(sessionID, child)

        const stderr: Buffer[] = []
        child.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk))
        child.on("close", (code) => {
          running.delete(sessionID)
          const detail = Buffer.concat(stderr).toString().trim()
          if (code === 0) {
            retried.delete(sessionID)
          } else if (code === 2) {
            void followUp(sessionID, detail).catch((error: unknown) => {
              console.error(`${ID}: could not submit the follow-up: ${String(error)}`)
            })
          } else {
            // Neither a pass nor a failing change: report it and keep the session's guard.
            console.error(`${ID}: gate exited with code ${String(code)}: ${detail}`)
          }
          resolve()
        })
        child.on("error", (error: Error) => {
          running.delete(sessionID)
          console.error(`${ID}: could not launch the gate: ${error.message}`)
          resolve()
        })
      })

    const check = async (sessionID: string) => {
      // Reserved before the first await so two idles for one session cannot both start a gate.
      if (checking.has(sessionID)) return
      checking.add(sessionID)
      try {
        const session = await context.session.get({ sessionID })
        if (path.resolve(session.location.directory) !== directory) return
        if (controller.signal.aborted) return
        await runGate(sessionID)
      } finally {
        checking.delete(sessionID)
      }
    }

    const consume = async () => {
      for await (const event of context.event.subscribe({ signal: controller.signal })) {
        if (event.type !== "session.idle") continue
        // Not awaited: one session's long gate must not hold up the next session's events.
        void check(event.data.sessionID).catch((error: unknown) => {
          console.error(`${ID}: check failed: ${String(error)}`)
        })
      }
    }
    void consume().catch((error: unknown) => {
      if (!controller.signal.aborted) console.error(`${ID}: event stream failed: ${String(error)}`)
    })

    return () => {
      disposed = true
      controller.abort()
      for (const child of running.values()) child.kill()
      running.clear()
      checking.clear()
    }
  },
})

export default StopGate
