"""Pranaxis MCP Gateway 0.3 — declarative consumption rules.

A rules file (JSON) describes, for one MCP server, which tool calls CONSUME a shared resource, how to name the
resource, and when a consumed resource is RELEASED (so its version can advance once the holder collects the result).

{
  "server": "vivado-ross",
  "description": "...",
  "consume": [                       # evaluated in order; the first rule that matches decides
    {"tool": "vivado_execute",       # tool name (exact, or glob with *)
     "when": {"command": "^\\s*(launch_runs|reset_runs?)\\b"},   # per-argument regex; ALL must match; named groups become fields
     "resource": "{session_id}/{run}",     # template: argument names, named groups, or $tool
     "each": {"arg": "command", "regex": "\\b(?:launch_runs|reset_runs?)\\s+(?P<run>[^\\s;\\[\\]-][^\\s;\\[\\]]*)(?:\\s+(?P<run2>[^\\s;\\[\\]-][^\\s;\\[\\]]*))?"},
     "note": "runs"}
  ],
  "release": [                       # calls whose RESPONSE shows a resource is complete -> pending release by holder
    {"tool": "vivado_execute", "when": {"command": "^\\s*wait_on_run\\b"}, "resource": "{session_id}/{run}",
     "each": {"arg": "command", "regex": "\\bwait_on_run\\s+(?P<run>[^\\s;\\[\\]]+)"}},
    {"tool": "vivado_status", "when": {"action": "^runs$"}, "resource": "{session_id}/{run}",
     "response": "\\b(?P<run>\\w+_\\d+)\\b[^\\n]{0,120}?(?:Complete|100%)"}   # regex on the response text, named groups
  ]
}

Fields available to templates: every top-level argument of the call (strings), every named group captured by `when`,
`each` or `response`, and $tool. A rule may also set "version": {"arg": "<name>"} to take the version from an
argument (e.g. an explicit row version / etag) instead of the gateway counter.
"""
import fnmatch, json, re

class RuleSet:
    def __init__(self, path):
        d = json.load(open(path)); self.server = d.get("server", path); self.consume = d.get("consume", []); self.release = d.get("release", [])
        for r in self.consume + self.release:
            r["_when"] = {k: re.compile(v) for k, v in (r.get("when") or {}).items()}
            if r.get("each"): r["_each"] = re.compile(r["each"]["regex"])
            if r.get("response"): r["_response"] = re.compile(r["response"])

    @staticmethod
    def _match(rule, tool, args):
        if not fnmatch.fnmatchcase(tool or "", rule.get("tool", "*")): return None
        fields = {k: v for k, v in (args or {}).items() if isinstance(v, (str, int, float))}; fields["$tool"] = tool
        for arg, rx in rule["_when"].items():
            m = rx.search(str((args or {}).get(arg, "")))
            if not m: return None
            fields.update({k: v for k, v in m.groupdict().items() if v is not None})
        return fields

    @staticmethod
    def _expand(template, fields):
        try: return template.format(**{k.replace("$", "_"): v for k, v in fields.items()}).replace("{_tool}", str(fields.get("$tool", "")))
        except KeyError: return None

    def consumes(self, tool, args):
        """-> list of (resource, explicit_version_or_None, rule) for a request, [] if it is not a consumption"""
        for rule in self.consume:
            fields = self._match(rule, tool, args)
            if fields is None: continue
            out = []; tmpl = rule["resource"].replace("{$tool}", "{_tool}")
            if rule.get("_each"):
                text = str((args or {}).get(rule["each"]["arg"], ""))
                for m in rule["_each"].finditer(text):
                    for k, v in m.groupdict().items():
                        if v is not None:
                            f = dict(fields); f["run"] = v; r = self._expand(tmpl, f)
                            if r: out.append(r)
            else:
                r = self._expand(tmpl, fields)
                if r: out.append(r)
            ver = None
            if rule.get("version", {}).get("arg"): ver = (args or {}).get(rule["version"]["arg"])
            return [(r, ver, rule) for r in dict.fromkeys(out)]
        return []

    def releases(self, tool, args, response_text):
        """-> list of resources shown complete by this response"""
        out = []
        for rule in self.release:
            fields = self._match(rule, tool, args)
            if fields is None: continue
            tmpl = rule["resource"].replace("{$tool}", "{_tool}")
            if rule.get("_each"):
                for m in rule["_each"].finditer(str((args or {}).get(rule["each"]["arg"], ""))):
                    f = dict(fields); f.update({k: v for k, v in m.groupdict().items() if v is not None}); r = self._expand(tmpl, f)
                    if r: out.append(r)
            elif rule.get("_response"):
                for m in rule["_response"].finditer(response_text or ""):
                    f = dict(fields); f.update({k: v for k, v in m.groupdict().items() if v is not None}); r = self._expand(tmpl, f)
                    if r: out.append(r)
            else:
                r = self._expand(tmpl, fields)
                if r: out.append(r)
        return list(dict.fromkeys(out))
