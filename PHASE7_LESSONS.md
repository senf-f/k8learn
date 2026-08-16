# Phase 7 Lessons — Packaging the Manifests as a Helm Chart

Learning notes from replacing the four hand-written Kubernetes manifests with a
minimal Helm chart, without changing a single test. This is where the project
stops shipping raw YAML and starts shipping a *package* — the same objects, but
parameterized, versioned, and installed with one command.

---

## 1. What we built

| Path | Purpose |
|------|---------|
| `charts/qa-demo/Chart.yaml` | Chart metadata — name, chart version, appVersion |
| `charts/qa-demo/values.yaml` | Every knob: replicas, image, config, service, resources, probes, securityContext |
| `charts/qa-demo/templates/_helpers.tpl` | Named templates — the pinned `qa-demo.name` and `qa-demo.selectorLabels` |
| `charts/qa-demo/templates/{configmap,deployment,service}.yaml` | The three objects, now templated |
| `charts/qa-demo/templates/NOTES.txt` | Post-install hint printed by `helm install` |
| `archive/k8s-raw-manifests/` | The original Phase 2 manifests, kept as a reference (see §5) |

**Verified end-to-end via CI** (run `31944018061`): `STATUS: deployed` through
`helm upgrade --install`, then **20 passed in 17.72s** — the exact same suite as
Phase 6, untouched. Helm is not installed on the local Windows host, so CI on a
clean runner was the real proof.

---

## 2. The mental model: a chart is a manifest with holes in it

A Helm chart is not a new way to run Kubernetes — it's the *same* Deployment,
Service, and ConfigMap, with the hardcoded values lifted out into `values.yaml`
and the objects turned into Go templates. `helm install` renders the templates
against the values and hands the resulting plain YAML to the cluster.

```
values.yaml  --+
               |  helm renders templates against values
templates/*  --+-------------------------------------> plain k8s YAML --> cluster
_helpers.tpl --+
```

So the useful sanity check is literally "render it and read it":

```bash
helm template qa-demo charts/qa-demo --namespace qa-demo
```

The output should match `archive/k8s-raw-manifests/` almost line-for-line. If it
doesn't, the templating changed behavior — which in this phase it must **not**.

---

## 3. The constraint that drove every decision: don't move the tests

Phase 3's `conftest.py` hardcodes what it queries: `NAMESPACE`/`SERVICE`/
`DEPLOYMENT` are all `qa-demo`, and it lists pods with `label_selector=app=qa-demo`.
The whole point of Phase 7 was to change the *packaging* and keep the *system*
identical, so the chart had to render:

- a Deployment named exactly `qa-demo`
- a Service named exactly `qa-demo`
- a ConfigMap named exactly `qa-demo-config`
- an `app: qa-demo` selector label on all of them

Helm's idiomatic default fights this. The convention is a `fullname` helper that
produces `<release>-<chart>` (here that'd be `qa-demo-qa-demo`) and a big block
of `app.kubernetes.io/*` selector labels. Adopting that would have renamed every
object and broken all 11 integration tests.

**Resolution:** `_helpers.tpl` pins the names instead of deriving them.

```gotmpl
{{- define "qa-demo.name" -}}
qa-demo
{{- end -}}

{{- define "qa-demo.selectorLabels" -}}
app: qa-demo
{{- end -}}
```

`qa-demo.name` is a constant, not `{{ .Release.Name }}-{{ .Chart.Name }}`. The
selector is the single `app: qa-demo` label the tests expect — the standard
`app.kubernetes.io/*` labels are added in `qa-demo.labels` (stamped on metadata)
but deliberately kept **out** of the selector, because **a Deployment's selector
is immutable** — changing it later forces a delete-and-recreate.

---

## 4. Design decisions

### Hand-written minimal, not `helm create`
`helm create` scaffolds a chart with a service account, autoscaling, ingress
stubs, pod annotations, and a `fullname` helper — dozens of lines for features
this app doesn't use. That's the opposite of the project's YAGNI discipline. The
chart here has exactly the four things Phase 2 had, and nothing else, so reading
it teaches Helm rather than hiding the app in boilerplate.

### No Namespace template — `--create-namespace` instead
Phase 2 had a `namespace.yaml`. The chart has no equivalent, because **charts
shouldn't template a Namespace object** — it creates ownership headaches (Helm
tries to delete the namespace on uninstall, taking unrelated resources with it)
and it's the one Phase 2 gotcha about apply-ordering that Helm makes moot. The
namespace is created by the install command:

```bash
helm upgrade --install qa-demo charts/qa-demo \
  --namespace qa-demo --create-namespace --wait --timeout 120s
```

### `$IMAGE` stays the single source of truth
`setup-cluster.sh` already defined `IMAGE=k8s-qa-demo:local` and used it for
`docker build` and `kind load`. Rather than duplicate the repo and tag into the
helm command, it splits the one variable with bash parameter expansion:

```bash
--set image.repository="${IMAGE%%:*}" \   # everything before the first ':'  -> k8s-qa-demo
--set image.tag="${IMAGE##*:}"            # everything after the last ':'    -> local
```

So the build, the load, and the deploy all still derive from one string.

### `--wait` replaces `kubectl rollout status`
Phase 2's script ran a separate `kubectl rollout status` after applying.
`helm ... --wait` blocks until the release's pods are Ready, so it subsumes that
step — one fewer command, same guarantee.

---

## 5. Archive, don't delete

The old manifests were moved to `archive/k8s-raw-manifests/` with `git mv`
(so history follows the files) and an explanatory `README.md`, rather than
deleted. Reasoning specific to this repo: it's a **portfolio project built phase
by phase**, and each phase is a learning artifact. The raw manifests are the
*explicit* form of exactly what the chart renders to — keeping them next to the
chart lets a reader diff `helm template` output against the originals and see
precisely what templating added and what it hid. Deleting them would erase the
before-picture that makes the Helm phase legible.

This is a judgment call, not a universal rule: in a production repo you'd delete
superseded manifests and rely on git history. Here the archived copy *is* part
of the showcase.

---

## 6. Gotchas

### Gotcha 1 — Helm's `fullname` convention will silently rename your objects
The single biggest trap. `helm create` and most examples give you resource names
like `<release>-<chart>` and multi-label selectors. Drop that into a repo whose
tests query fixed names and everything "deploys fine" while every integration
test fails to find its Service/Deployment. If you have existing consumers (tests,
other services, dashboards) that reference resource names or selectors, **pin the
names in a helper** and verify with `helm template` before deploying.

### Gotcha 2 — never change a Deployment's `selector` casually
`spec.selector.matchLabels` is immutable after creation. The chart keeps the
selector to the single `app: qa-demo` label and puts the richer
`app.kubernetes.io/*` labels only in `metadata.labels`. Folding the standard
labels into the selector would look tidier and would be a landmine on the next
`helm upgrade`.

### Gotcha 3 — helm isn't on the Windows host; render checks still work offline
`helm: command not found` locally, so the full flow (`setup-cluster.sh` → pytest)
can only be exercised in CI here. But two of the most useful checks need **no
cluster and no Docker** — `helm lint charts/qa-demo` and
`helm template qa-demo charts/qa-demo`. Once helm is installed, those run
anywhere and catch template/schema mistakes long before a deploy.

### Gotcha 4 — `nindent` and the leading `{{-` are load-bearing
Blocks pulled in with `include ... | nindent N` and `toYaml ... | nindent N` are
indentation-sensitive: the `nindent` count must match the YAML depth, and the
`{{-` chomp on the line above removes the newline so the block lands where it
should. Get the number wrong and helm emits YAML that either fails to parse or
nests a field under the wrong parent. `helm template` is how you catch this —
eyeball the rendered indentation.

---

## 7. Takeaways

- **A chart is templated manifests, nothing more** — `helm template` renders the
  same YAML you wrote by hand; if the render differs from the originals in a
  refactor, the refactor changed behavior.
- **Existing consumers pin your names** — when tests/services reference resource
  names or selectors, override Helm's `fullname` convention and keep them stable;
  verify with `helm template` before you ever deploy.
- **A Deployment selector is immutable** — keep it minimal and stable; put the
  decorative labels in `metadata.labels`, not the selector.
- **Let the install own the namespace** — `--create-namespace`, not a Namespace
  template; it also retires Phase 2's apply-ordering gotcha.
- **One source of truth for the image** — bash parameter expansion split `$IMAGE`
  into repo/tag so build, load, and deploy can't drift.
- **`--wait` folds in the rollout check** — one command, same Ready guarantee.
- **Archive learning artifacts, delete production cruft** — context decides;
  here the raw manifests are the before-picture that makes the chart legible.
- **You can validate a chart offline** — `helm lint` and `helm template` need no
  cluster, which matters when the deploy path only exists in CI.
