{{- define "arkime.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "arkime.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "arkime.namespace.meta" -}}
{{- if .Values.namespace }}
namespace: {{ .Values.namespace }}
{{- end }}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "arkime.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "arkime.labels" -}}
helm.sh/chart: {{ include "arkime.chart" . }}
{{ include "arkime.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "arkime.selectorLabels" -}}
app.kubernetes.io/name: {{ include "arkime.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Name with suffix
Usage: {{ include "arkime.nameWithSuffix" (dict "root" . "suffix" "elastic")}}
*/}}
{{- define "arkime.nameWithSuffix" -}}
{{- $r := .root -}}
{{- $s := .suffix | default "" -}}
{{- $base := include "arkime.fullname" $r -}}
{{- if $s }}{{ printf "%s-%s" $base $s | trunc 63 | trimSuffix "-" }}{{ else }}{{ $base }}{{ end -}}
{{- end -}}

{{/*
Convenience names per component
*/}}
{{- define "arkime.elasticsearch.name" -}}
{{- printf "%s-%s" (include "arkime.fullname" .) (default "elastic" .Values.elasticsearch.nameSuffix) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "arkime.kibana.name" -}}
{{- printf "%s-%s" (include "arkime.fullname" .) (default "kibana" .Values.kibana.nameSuffix) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "arkime.setup.name" }}
{{- printf "%s-%s" (include "arkime.fullname" .) (default "init" .Values.elasticSetup.nameSuffix) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "arkime.elasticsearch.defaultService" -}}
{{- printf "%s-es-default" (include "arkime.elasticsearch.name" .) -}}
{{- end -}}

{{- define "arkime.elasticsearch.elasticUserSecret" -}}
{{- printf "%s-es-elastic-user" (include "arkime.elasticsearch.name" .) -}}
{{- end -}}
