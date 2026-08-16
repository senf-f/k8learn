{{/*
Fixed resource base name. Kept as "qa-demo" (not the usual release-chart
combo) so resource names match what the integration tests query.
*/}}
{{- define "qa-demo.name" -}}
qa-demo
{{- end -}}

{{/*
Selector labels — MUST stay `app: qa-demo`. Selectors are immutable and the
test suite lists pods with label_selector=app=qa-demo.
*/}}
{{- define "qa-demo.selectorLabels" -}}
app: qa-demo
{{- end -}}

{{/*
Common labels stamped on every object: the selector label plus the standard
Helm/Kubernetes recommended labels.
*/}}
{{- define "qa-demo.labels" -}}
{{ include "qa-demo.selectorLabels" . }}
app.kubernetes.io/name: {{ include "qa-demo.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
