{{/*
Expand the name of the chart.
*/}}
{{- define "ctf-monitoring.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "ctf-monitoring.fullname" -}}
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

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "ctf-monitoring.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ctf-monitoring.labels" -}}
helm.sh/chart: {{ include "ctf-monitoring.chart" . }}
{{ include "ctf-monitoring.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "ctf-monitoring.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ctf-monitoring.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "ctf-monitoring.serviceAccountName" -}}
{{ include "ctf-monitoring.fullname" . }}
{{- end }}

{{- define "ctf-monitoring.workerNodeSelector" -}}
ctfr.attacking-lab.com/ctf: {{ .Values.ctf }}
ctfr.attacking-lab.com/role: worker
{{- end }}

{{- define "ctf-monitoring.checkerNodeSelector" -}}
ctfr.attacking-lab.com/ctf: {{ .Values.ctf }}
ctfr.attacking-lab.com/role: infra
ctfr.attacking-lab.com/checker: "true"
{{- end }}

{{- define "ctf-monitoring.gameserverNodeSelector" -}}
ctfr.attacking-lab.com/ctf: {{ .Values.ctf }}
ctfr.attacking-lab.com/role: infra
ctfr.attacking-lab.com/gameserver: "true"
{{- end }}

{{- define "ctf-monitoring.workerTolerations" -}}
- key: ctfr.attacking-lab.com/role
  operator: Equal
  value: worker
  effect: NoExecute
- key: ctfr.attacking-lab.com/ctf
  operator: Equal
  value: {{ .Values.ctf }}
  effect: NoExecute
{{- end }}

{{- define "ctf-monitoring.infraTolerations" -}}
- key: ctfr.attacking-lab.com/role
  operator: Equal
  value: infra
  effect: NoExecute
- key: ctfr.attacking-lab.com/ctf
  operator: Equal
  value: {{ .Values.ctf }}
  effect: NoExecute
{{- end }}

{{- define "ctf-monitoring.nodeExporterTemplateSpec" -}}
automountServiceAccountToken: false
serviceAccountName: node-exporter
securityContext:
  fsGroup: 65534
  runAsGroup: 65534
  runAsNonRoot: true
  runAsUser: 65534
containers:
  - name: node-exporter
    image: quay.io/prometheus/node-exporter:v1.9.1
    imagePullPolicy: IfNotPresent
    args:
      - --path.procfs=/host/proc
      - --path.sysfs=/host/sys
      - --path.rootfs=/host/root
      - --path.udev.data=/host/root/run/udev/data
      - --web.listen-address=[$(HOST_IP)]:9100
    securityContext:
      readOnlyRootFilesystem: true
    env:
      - name: HOST_IP
        value: 0.0.0.0
    ports:
      - name: metrics
        containerPort: 9100
        protocol: TCP
    livenessProbe:
      failureThreshold: 3
      httpGet:
        path: /
        port: metrics
        scheme: HTTP
      initialDelaySeconds: 0
      periodSeconds: 10
      successThreshold: 1
      timeoutSeconds: 1
    readinessProbe:
      failureThreshold: 3
      httpGet:
        path: /
        port: metrics
        scheme: HTTP
      initialDelaySeconds: 0
      periodSeconds: 10
      successThreshold: 1
      timeoutSeconds: 1
    volumeMounts:
      - name: proc
        mountPath: /host/proc
        readOnly: true
      - name: sys
        mountPath: /host/sys
        readOnly: true
      - name: root
        mountPath: /host/root
        mountPropagation: HostToContainer
        readOnly: true
hostNetwork: true
hostPID: true
hostIPC: false
nodeSelector:
  kubernetes.io/os: linux
tolerations:
  - operator: Exists
volumes:
  - name: proc
    hostPath:
      path: /proc
  - name: sys
    hostPath:
      path: /sys
  - name: root
    hostPath:
      path: /
{{- end }}
