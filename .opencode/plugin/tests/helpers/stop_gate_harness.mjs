// Drives the real stop-gate plugin module for the pytest suites.
//
// Usage: tsx stop_gate_harness.mjs <scenario> <directory> [other directory]
// Prints one JSON line on stdout; everything the plugin logs goes to stderr.
//
// The plugin is imported from its discovered path and given a fake V2 context, so no real
// server, session or model request is involved. Every wait is a handshake rather than a delay:
// the fake python3 announces its launch, cancellation, waiting and exit over a socket, and a
// drain resolves when the event loop has no work left. Nothing here polls on a timer.

import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import net from "node:net"
import { tmpdir } from "node:os"
import path from "node:path"
import process from "node:process"

const PLUGIN = new URL("../../stop-gate.ts", import.meta.url)

const FAKE_GATE = `\
import json, os, signal, socket, stat, sys

address = ("127.0.0.1", int(os.environ["STOP_GATE_PORT"]))
control = []

def report(message):
    with socket.create_connection(address) as link:
        link.sendall((json.dumps(message) + "\\n").encode())

def cancelled(*_args):
    report({"type": "cancelled"})
    for link in control:
        link.close()

signal.signal(signal.SIGTERM, cancelled)

report({
    "type": "launch",
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "stdin": "closed" if stat.S_ISCHR(os.fstat(0).st_mode) else "open",
})

if os.environ.get("STOP_GATE_RELEASE") == "wait":
    link = socket.create_connection(address)
    control.append(link)
    link.sendall(b'{"type": "waiting"}\\n')
    try:
        link.recv(1)
    except OSError:
        pass

code = int(os.environ.get("STOP_GATE_EXIT", "0"))
report({"type": "exit", "code": code})
sys.stderr.write(os.environ.get("STOP_GATE_STDERR", ""))
sys.exit(code)
`

const [scenario, directory, otherDirectory] = process.argv.slice(2)
if (!scenario || !directory) {
  console.error("usage: stop_gate_harness.mjs <scenario> <directory> [other directory]")
  process.exit(2)
}

// The gate boundary: a fake `python3` on PATH that reports how it was launched and how it ends.
const sandbox = mkdtempSync(path.join(tmpdir(), "stop-gate-"))
const bin = path.join(sandbox, "bin")
const gate = path.join(sandbox, "fake_gate.py")
mkdirSync(bin, { recursive: true })
writeFileSync(gate, FAKE_GATE)
const wrapper = '#!/bin/sh\nexec "$STOP_GATE_PYTHON" "$STOP_GATE_GATE" "$@"\n'
writeFileSync(path.join(bin, "python3"), wrapper)
chmodSync(path.join(bin, "python3"), 0o755)
process.env.PATH = `${bin}${path.delimiter}${process.env.PATH}`
process.env.STOP_GATE_GATE = gate
if (!process.env.STOP_GATE_PYTHON) {
  console.error("STOP_GATE_PYTHON must name the interpreter the fake gate runs on")
  process.exit(2)
}

// Everything the fake gates and the plugin's context report, and one notifier per change.
const records = []
let notified = []

function notify() {
  for (const listener of notified.splice(0)) listener()
}

const pending = new Set()

function waitFor(condition, label) {
  if (condition()) return Promise.resolve()
  return new Promise((resolve) => {
    pending.add(label)
    const listener = () => {
      if (!condition()) {
        notified.push(listener)
        return
      }
      pending.delete(label)
      resolve()
    }
    notified.push(listener)
  })
}

function launches() {
  return records.filter((record) => record.type === "launch")
}

function exits() {
  return records.filter((record) => record.type === "exit")
}

function release(index = 0) {
  const waiting = records.filter((record) => record.type === "waiting")[index]
  waiting.socket.write("go\n")
}

// One microtask turn per await, so a callback that runs on promise continuations has run.
async function drains(turns = 5) {
  for (let turn = 0; turn < turns; turn += 1) await Promise.resolve()
}

const server = net.createServer((socket) => {
  socket.setEncoding("utf8")
  socket.on("error", () => {})
  let buffered = ""
  socket.on("data", (chunk) => {
    buffered += chunk
    let end = buffered.indexOf("\n")
    while (end !== -1) {
      const record = JSON.parse(buffered.slice(0, end))
      buffered = buffered.slice(end + 1)
      record.socket = socket
      records.push(record)
      notify()
      end = buffered.indexOf("\n")
    }
  })
})
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve))
server.unref()
process.env.STOP_GATE_PORT = String(server.address().port)

// Resolves once the loop has no work left, so no callback of this turn can still be pending.
// One immediate first: beforeExit reports an empty loop, which then needs a turn to re-arm.
async function quiescent() {
  await new Promise((resolve) => setImmediate(resolve))
  await new Promise((resolve) => process.once("beforeExit", resolve))
}

function stream() {
  const queue = []
  const waiters = []
  let closed = false
  const close = () => {
    closed = true
    for (const waiter of waiters.splice(0)) waiter({ done: true, value: undefined })
  }
  const source = {
    delivered: 0,
    push(event) {
      const waiter = waiters.shift()
      if (waiter) {
        source.delivered += 1
        waiter({ done: false, value: event })
      } else queue.push(event)
      notify()
    },
    close,
    [Symbol.asyncIterator]() {
      return {
        next() {
          if (queue.length > 0) {
            source.delivered += 1
            return Promise.resolve({ done: false, value: queue.shift() })
          }
          if (closed) return Promise.resolve({ done: true, value: undefined })
          return new Promise((resolve) => waiters.push(resolve))
        },
        return() {
          close()
          return Promise.resolve({ done: true, value: undefined })
        },
      }
    },
  }
  return source
}

function idle(sessionID) {
  return { type: "session.idle", data: { sessionID } }
}

const events = stream()
const observed = { subscribeCalls: 0, prompts: [], sessions: {}, asked: [], diagnostics: [] }

const consoleError = console.error.bind(console)
console.error = (...args) => {
  observed.diagnostics.push(args.map((value) => String(value)).join(" "))
  notify()
  consoleError(...args)
}

const context = {
  location: { directory },
  event: {
    subscribe(options = {}) {
      observed.subscribeCalls += 1
      options.signal?.addEventListener("abort", () => events.close())
      notify()
      return events
    },
  },
  session: {
    async get({ sessionID }) {
      observed.asked.push(sessionID)
      notify()
      return { id: sessionID, location: { directory: observed.sessions[sessionID] ?? directory } }
    },
    async prompt(input) {
      observed.prompts.push(input)
      notify()
      return { id: "queued" }
    },
  },
}

async function gateFinished(count) {
  await waitFor(() => exits().length >= count, `gate result ${count}`)
  await quiescent()
}

const SCENARIOS = {
  // Loading only: the definition is accepted and setup subscribes; nothing else happens.
  async load() {
    await quiescent()
  },

  // One idle event for a local session must reach the gate with safe arguments.
  async "local-idle"() {
    events.push(idle("ses_local"))
    await waitFor(() => launches().length > 0, "the gate process")
  },

  // A live plugin, then an event that is not a session going idle.
  async "unrelated-event"() {
    events.push(idle("ses_local"))
    await waitFor(() => launches().length > 0, "the gate process")
    await gateFinished(1)
    events.push({ type: "config.updated", data: {} })
    await quiescent()
  },

  // An idle event whose session lives in another directory.
  async "other-location"() {
    observed.sessions.ses_other = otherDirectory
    events.push(idle("ses_other"))
    await waitFor(() => observed.asked.includes("ses_other"), "the session lookup")
    await quiescent()
  },

  // A second idle for the same session while its gate is still running.
  async "concurrent-idle"() {
    process.env.STOP_GATE_RELEASE = "wait"
    events.push(idle("ses_local"))
    await waitFor(() => launches().length > 0, "the first gate process")
    await waitFor(() => records.some((record) => record.type === "waiting"), "the waiting gate")

    // Only the gate already running waits; a wrongly started second one finishes and is counted.
    process.env.STOP_GATE_RELEASE = ""
    const delivered = events.delivered
    events.push(idle("ses_local"))
    await waitFor(() => events.delivered > delivered, "the second idle handed to the consumer")
    await drains()

    release()
    await gateFinished(1)
  },

  // Two gate results of 2 for one session, with the failure detail on stderr.
  async "failure-twice"() {
    process.env.STOP_GATE_EXIT = "2"
    process.env.STOP_GATE_STDERR = "checks failed\n"
    events.push(idle("ses_one"))
    await waitFor(() => observed.prompts.length === 1, "the corrective follow-up")
    await gateFinished(1)

    events.push(idle("ses_one"))
    await gateFinished(2)
  },

  // Gate results 2, 0 and 2 for one session: the 0 must clear the guard again.
  async "failure-reset"() {
    process.env.STOP_GATE_STDERR = "checks failed\n"

    process.env.STOP_GATE_EXIT = "2"
    events.push(idle("ses_one"))
    await waitFor(() => observed.prompts.length === 1, "the first corrective follow-up")
    await gateFinished(1)

    process.env.STOP_GATE_EXIT = "0"
    events.push(idle("ses_one"))
    await gateFinished(2)

    process.env.STOP_GATE_EXIT = "2"
    events.push(idle("ses_one"))
    await waitFor(() => observed.prompts.length === 2, "the second corrective follow-up")
    await gateFinished(3)
  },

  // The same failure for two sessions: each keeps its own guard.
  async "two-sessions"() {
    process.env.STOP_GATE_EXIT = "2"
    process.env.STOP_GATE_STDERR = "checks failed\n"

    events.push(idle("ses_one"))
    await waitFor(() => observed.prompts.length === 1, "the first session's follow-up")
    await gateFinished(1)

    events.push(idle("ses_two"))
    await waitFor(() => observed.prompts.length === 2, "the second session's follow-up")
    await gateFinished(2)
  },

  // Unloading while a gate runs: the process is cancelled, stops consuming, stays silent.
  async "unload"() {
    process.env.STOP_GATE_RELEASE = "wait"
    process.env.STOP_GATE_EXIT = "2"
    process.env.STOP_GATE_STDERR = "checks failed\n"

    events.push(idle("ses_local"))
    await waitFor(() => launches().length > 0, "the gate process")
    await waitFor(() => records.some((record) => record.type === "waiting"), "the waiting gate")

    await cleanup()
    cleanup = null
    await waitFor(
      () => records.some((record) => record.type === "cancelled"),
      "the cancelled gate process",
    )

    process.env.STOP_GATE_RELEASE = ""
    const delivered = events.delivered
    events.push(idle("ses_local"))
    await drains()
    report.deliveredAfterCleanup = events.delivered - delivered

    // The cancelled child still finishes and returns its result, after cleanup.
    await gateFinished(1)
  },

  // Gate results 2, 1 and 2: the unexpected exit is reported and changes nothing else.
  async "unexpected-exit"() {
    process.env.STOP_GATE_STDERR = "checks failed\n"

    process.env.STOP_GATE_EXIT = "2"
    events.push(idle("ses_one"))
    await waitFor(() => observed.prompts.length === 1, "the first corrective follow-up")
    await gateFinished(1)

    process.env.STOP_GATE_STDERR = "execution failed\n"
    process.env.STOP_GATE_EXIT = "1"
    events.push(idle("ses_one"))
    await gateFinished(2)

    process.env.STOP_GATE_STDERR = "checks failed\n"
    process.env.STOP_GATE_EXIT = "2"
    events.push(idle("ses_one"))
    await gateFinished(3)
  },

  // Python cannot be launched for the first idle; a later one still checks normally.
  async "launch-error"() {
    const python = path.join(bin, "python3")
    const savedPath = process.env.PATH
    rmSync(python)
    process.env.PATH = bin

    events.push(idle("ses_local"))
    await waitFor(
      () => observed.diagnostics.some((line) => line.includes("ENOENT")),
      "the launch error diagnostic",
    )
    await quiescent()

    writeFileSync(python, wrapper)
    chmodSync(python, 0o755)
    process.env.PATH = savedPath
    process.env.STOP_GATE_EXIT = "2"
    process.env.STOP_GATE_STDERR = "checks failed\n"

    events.push(idle("ses_local"))
    await waitFor(() => observed.prompts.length === 1, "the follow-up after recovery")
    await gateFinished(1)
  },
}

const report = {
  loadError: null,
  defaultKind: null,
  id: null,
  setupIsFunction: null,
  cleanupIsFunction: null,
  subscribeCalls: 0,
  gateRuns: 0,
  gate: [],
  exits: [],
  cancelled: false,
  deliveredAfterCleanup: null,
  prompts: [],
  diagnostics: [],
  sessionsAsked: [],
}

let cleanup = null
let failure = null

try {
  const loaded = await import(PLUGIN.href)
  const definition = loaded.default
  report.defaultKind = typeof definition
  report.id = typeof definition === "object" && definition !== null ? definition.id : null
  report.setupIsFunction = typeof definition?.setup === "function"

  if (report.setupIsFunction) {
    cleanup = await definition.setup(context)
    report.cleanupIsFunction = typeof cleanup === "function"
    await waitFor(() => observed.subscribeCalls > 0, "the event subscription")
    await (SCENARIOS[scenario] ?? unknownScenario)()
  }
} catch (error) {
  failure = String(error?.stack ?? error)
}

if (failure) {
  // Let a gate that is still waiting finish, so the loop can drain and the failure is reported.
  for (const record of records.filter((item) => item.type === "waiting")) record.socket.write("go\n")
}
await quiescent()
if (pending.size > 0) failure ??= `nothing more can happen while waiting for ${[...pending].join(", ")}`

report.subscribeCalls = observed.subscribeCalls
report.gateRuns = launches().length
report.gate = launches().map(({ argv, cwd, stdin }) => ({ argv, cwd, stdin }))
report.exits = exits().map(({ code }) => ({ code }))
report.cancelled = records.some((record) => record.type === "cancelled")
report.prompts = observed.prompts
report.diagnostics = observed.diagnostics
report.sessionsAsked = observed.asked

if (failure) {
  console.error(failure)
  process.exit(1)
}
console.log(JSON.stringify(report))
if (cleanup) await cleanup()
process.exit(0)

async function unknownScenario() {
  throw new Error(`unknown scenario '${scenario}'`)
}
