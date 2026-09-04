#!/usr/bin/env node
/** npm shim for the AgentICU Python application.
 *
 * `npm install -g agenticu` puts `agenticu` on PATH. On first run this shim
 * ensures the Python package (with the TUI extra) is installed, then forwards
 * all arguments to it. Prerequisite: Python >= 3.11 on PATH.
 */
const { spawnSync } = require("node:child_process");

const PIP_SPEC = "agenticu[tui]";

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "pipe", encoding: "utf8", ...opts });
  return r;
}

function fail(msg) {
  console.error(`agenticu: ${msg}`);
  process.exit(1);
}

// 1. Python present and new enough?
const py = run("python3", ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]);
if (py.status !== 0) {
  fail("Python 3 is required but was not found on PATH. Install Python >= 3.11 first: https://www.python.org/downloads/");
}
const [major, minor] = py.stdout.trim().split(".").map(Number);
if (major < 3 || (major === 3 && minor < 11)) {
  fail(`Python >= 3.11 is required, found ${py.stdout.trim()}.`);
}

// 2. `agenticu` binary already installed?
let probe = run("agenticu", ["--help"]);
if (probe.status !== 0) {
  console.error(`agenticu: Python package not found, installing \`${PIP_SPEC}\` via pip…`);
  const pip = run("python3", ["-m", "pip", "install", PIP_SPEC], { stdio: "inherit" });
  if (pip.status !== 0) {
    fail(`\`pip install ${PIP_SPEC}\` failed. Try manually: python3 -m pip install "${PIP_SPEC}"`);
  }
  probe = run("agenticu", ["--help"]);
  if (probe.status !== 0) {
    fail("installed but the `agenticu` binary is still not on PATH. Check your pip --user bin dir.");
  }
}

// 3. Forward everything (exit code included).
const fwd = spawnSync("agenticu", process.argv.slice(2), { stdio: "inherit" });
process.exit(fwd.status ?? 1);
