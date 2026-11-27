"""Un seul geste ne compte qu'une fois : pas de FOCUS_AWAY en plus d'une violation déjà signalée."""
import json
import re
import shutil
import subprocess
from unittest import skipUnless

from .tests_examen_securite import ExamFixture

# Exécute le vrai script de la page d'examen dans Node : seuls le navigateur, le réseau et l'horloge sont simulés.
HARNESS = r"""
const [script, state, steps] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let now = 0, focused = true, timers = [], nextId = 0;
const sent = [], handlers = {}, elements = {};
const on = (target) => (name, fn) => { handlers[target + name] = fn; };
const stub = (values = {}) => new Proxy(() => {}, {
  get: (_, key) => key in values ? values[key] : key === 'then' ? undefined
    : key === 'toString' ? () => '' : typeof key === 'symbol' ? undefined : (values[key] = stub()),
  set: (_, key, value) => { values[key] = value; return true; },
  apply: () => stub(),
});
const element = (id) => elements[id] ??= stub({addEventListener: on(id + ':')});
element('exam-state').textContent = state;
const document = {
  hidden: false, fullscreenElement: {}, hasFocus: () => focused, getElementById: element,
  createElement: () => stub(), addEventListener: on('document:'),
};
const window = {addEventListener: on('window:'), location: {}, innerWidth: 800, innerHeight: 600};
class FormData { constructor() { this.values = {}; } set(k, v) { this.values[k] = v; } }
const fetch = async (url, options) => {
  sent.push(options.body.values.event);
  return {status: 200, ok: true, json: async () => ({status: 'IN_PROGRESS', warning: true, count: 1})};
};
const setTimeout = (fn, ms) => { timers.push({id: ++nextId, at: now + ms, fn}); return nextId; };
const clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
const flush = () => new Promise(setImmediate);
async function wait(ms) {
  const end = now + ms;
  for (;;) {
    const due = timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!due) break;
    clearTimeout(due.id); now = due.at; due.fn(); await flush();
  }
  now = end;
}
const actions = {
  exit_fullscreen: () => { document.fullscreenElement = null; handlers['document:fullscreenchange'](); },
  leave_window: () => { focused = false; handlers['window:blur'](); },
  hide_tab: () => { focused = false; document.hidden = true; handlers['document:visibilitychange'](); handlers['window:blur'](); },
};
new Function('window', 'document', 'fetch', 'FormData', 'setTimeout', 'clearTimeout', 'setInterval', 'performance', script)(
  window, document, fetch, FormData, setTimeout, clearTimeout, () => 0, {now: () => now});
(async () => {
  await handlers['enterFullscreen:click']();
  await wait(5000);
  for (const step of steps) {
    if (typeof step === 'number') await wait(step); else actions[step]();
    await flush();
  }
  console.log(JSON.stringify(sent));
})();
"""


@skipUnless(shutil.which("node"), "Node.js absent : comportement de la page non vérifié")
class OneGestureOneViolationTests(ExamFixture):
    def violations_sent(self, *steps):
        page = self.client.get(f"/attempt/{self.attempt.id}/").content.decode()
        state = re.search(r'<script id="exam-state"[^>]*>(.*?)</script>', page, re.S).group(1)
        script = re.search(r"<script>\s*(\(\(\) => \{\s*const URLS.*?)</script>", page, re.S).group(1)
        run = subprocess.run([shutil.which("node"), "-e", HARNESS], input=json.dumps([script, state, steps]),
                             capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return [event for event in json.loads(run.stdout) if event not in ("FOCUS_LOSS", "WINDOW_RESIZE")]

    def test_hidden_tab_is_reported_once(self):
        self.assertEqual(self.violations_sent("hide_tab", 5000), ["TAB_SWITCH"])

    def test_window_left_while_leaving_fullscreen_is_reported_once(self):
        self.assertEqual(self.violations_sent("exit_fullscreen", "leave_window", 5000), ["FULLSCREEN_EXIT"])

    def test_leaving_the_window_alone_is_still_reported(self):
        self.assertEqual(self.violations_sent("leave_window", 5000), ["FOCUS_AWAY"])

    def test_leaving_the_window_later_is_still_reported(self):
        self.assertEqual(self.violations_sent("exit_fullscreen", 10000, "leave_window", 5000),
                         ["FULLSCREEN_EXIT", "FOCUS_AWAY"])
