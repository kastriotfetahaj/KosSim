package routes

import (
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"

	"nanofleet/internal/eno"
	"nanofleet/internal/firmware"
	"nanofleet/internal/jobs"
	"nanofleet/internal/ops"
	"nanofleet/internal/state"
	"nanofleet/internal/token"
	"nanofleet/internal/ui"
)

func New(store *state.Store) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/" && r.Method == http.MethodPost {
			enoTask(w, r, store)
			return
		}
		if r.URL.Path == "/" {
			ui.Index(w)
			return
		}
		http.NotFound(w, r)
	})
	mux.HandleFunc("/static/", ui.Static)
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, map[string]any{"status": "up", "name": "nanofleet", "service": store.Team + "/" + store.Service})
	})
	mux.HandleFunc("/whoami", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, map[string]any{"team": store.Team, "service": store.Service, "runtime": "go-net-http"})
	})
	mux.HandleFunc("/service", func(w http.ResponseWriter, r *http.Request) {
		if !eno.Authorized(r, store.Secret) {
			http.Error(w, `{"error":"forbidden"}`, http.StatusForbidden)
			return
		}
		writeJSON(w, map[string]any{"serviceName": "nanofleet", "flagVariants": 3, "noiseVariants": 3, "havocVariants": 6})
	})
	mux.HandleFunc("/api/nodes", func(w http.ResponseWriter, r *http.Request) {
		store.Lock.Lock()
		defer store.Lock.Unlock()
		nodes := []state.Node{}
		for _, node := range store.Nodes {
			copy := node
			copy.Data = ""
			nodes = append(nodes, copy)
		}
		writeJSON(w, map[string]any{"nodes": nodes})
	})
	mux.HandleFunc("/api/routes/diag-token", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, map[string]any{"token": token.Sign(store.Secret, "diag")})
	})
	mux.HandleFunc("/api/route/", func(w http.ResponseWriter, r *http.Request) { routeCommand(w, r, store) })
	mux.HandleFunc("/api/v2/agent/register", func(w http.ResponseWriter, r *http.Request) { registerAgent(w, r, store) })
	mux.HandleFunc("/api/v2/jobs", func(w http.ResponseWriter, r *http.Request) { scheduleJob(w, r, store) })
	mux.HandleFunc("/api/v2/jobs/diagnostic", func(w http.ResponseWriter, r *http.Request) { diagnosticPayload(w, r, store) })
	mux.HandleFunc("/api/v2/jobs/", func(w http.ResponseWriter, r *http.Request) { readJob(w, r, store) })
	mux.HandleFunc("/api/v2/firmware/issue", func(w http.ResponseWriter, r *http.Request) { firmwareIssue(w, r, store) })
	mux.HandleFunc("/api/v2/firmware/read", func(w http.ResponseWriter, r *http.Request) { firmwareRead(w, r, store) })
	mux.HandleFunc("/api/tlv/decode", func(w http.ResponseWriter, r *http.Request) { tlvDecode(w, r, store) })
	mux.HandleFunc("/api/firmware/blob/", func(w http.ResponseWriter, r *http.Request) { firmwareBlob(w, r, store) })
	ops.Register(mux)
	return mux
}

func registerAgent(w http.ResponseWriter, r *http.Request, store *state.Store) {
	if r.Method != http.MethodPost {
		http.NotFound(w, r)
		return
	}
	var body struct {
		Label string `json:"label"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if body.Label == "" {
		body.Label = "agent"
	}
	node := store.RegisterNode(body.Label)
	writeJSON(w, map[string]any{"node": node})
}

func scheduleJob(w http.ResponseWriter, r *http.Request, store *state.Store) {
	if r.Method != http.MethodPost {
		http.NotFound(w, r)
		return
	}
	var body struct {
		Node     string `json:"node"`
		Template string `json:"template"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if body.Template == "" {
		body.Template = "noop"
	}
	job := store.Schedule(body.Node, body.Template)
	writeJSON(w, map[string]any{"job": job})
}

func readJob(w http.ResponseWriter, r *http.Request, store *state.Store) {
	id := strings.TrimPrefix(r.URL.Path, "/api/v2/jobs/")
	job, ok := store.Job(id)
	if !ok {
		http.NotFound(w, r)
		return
	}
	writeJSON(w, map[string]any{"job": job})
}

func enoTask(w http.ResponseWriter, r *http.Request, store *state.Store) {
	if !eno.Authorized(r, store.Secret) {
		http.Error(w, `{"error":"forbidden"}`, http.StatusForbidden)
		return
	}
	var task eno.Task
	_ = json.NewDecoder(r.Body).Decode(&task)
	method := strings.ToUpper(task.Method)
	tick := task.RelatedRoundID
	if tick == 0 {
		tick = task.CurrentRoundID
	}
	if method == "PUTFLAG" {
		if task.Flag == "" {
			writeJSON(w, map[string]any{"result": "INTERNAL_ERROR", "message": "missing flag"})
			return
		}
		writeJSON(w, map[string]any{"result": "OK", "attack_info": store.PutFlag(tick, task.VariantID, task.Flag)})
		return
	}
	if method == "GETFLAG" {
		result := "MUMBLE"
		if store.GetFlag(tick, task.VariantID, task.Flag) {
			result = "OK"
		}
		writeJSON(w, map[string]any{"result": result})
		return
	}
	if method == "PUTNOISE" {
		store.PutNoise(tick, task.VariantID)
		writeJSON(w, map[string]any{"result": "OK"})
		return
	}
	if method == "GETNOISE" {
		result := "MUMBLE"
		if store.GetNoise(tick, task.VariantID) {
			result = "OK"
		}
		writeJSON(w, map[string]any{"result": result})
		return
	}
	if method == "HAVOC" {
		result := "MUMBLE"
		if store.Havoc(tick, task.VariantID) {
			result = "OK"
		}
		writeJSON(w, map[string]any{"result": result})
		return
	}
	writeJSON(w, map[string]any{"result": "OK"})
}

// routeCommand hosts VULN-A (route shadowing via ';' chaining).
func routeCommand(w http.ResponseWriter, r *http.Request, store *state.Store) {
	raw := strings.TrimPrefix(r.URL.Path, "/api/route/")
	tok, ok := token.Verify(store.Secret, r.URL.Query().Get("token"))
	if !ok || !strings.HasPrefix(raw, tok.Prefix) {
		http.Error(w, `{"error":"route_denied"}`, http.StatusForbidden)
		return
	}
	results := []map[string]any{}
	for _, cmd := range strings.Split(raw, ";") {
		if cmd == "diag" {
			results = append(results, map[string]any{"status": "nominal"})
		}
		if strings.HasPrefix(cmd, "read:") {
			nodeID := strings.TrimPrefix(cmd, "read:")
			store.Lock.Lock()
			node, exists := store.Nodes[nodeID]
			store.Lock.Unlock()
			if exists {
				results = append(results, map[string]any{"node": nodeID, "telemetry": node})
			}
		}
	}
	writeJSON(w, map[string]any{"route": raw, "results": results})
}

// tlvDecode hosts VULN-B (magic length=260 dumps raw node data).
func tlvDecode(w http.ResponseWriter, r *http.Request, store *state.Store) {
	nodeID := r.URL.Query().Get("node")
	length := r.URL.Query().Get("length")
	store.Lock.Lock()
	node, exists := store.Nodes[nodeID]
	store.Lock.Unlock()
	if !exists {
		http.NotFound(w, r)
		return
	}
	if length == "260" {
		writeJSON(w, map[string]any{"node": nodeID, "value_hex": hex.EncodeToString([]byte(node.Data))})
		return
	}
	writeJSON(w, map[string]any{"node": nodeID, "kind": node.Kind})
}

// firmwareBlob hosts VULN-C (manifest=public dumps plaintext).
func firmwareBlob(w http.ResponseWriter, r *http.Request, store *state.Store) {
	blob := strings.TrimPrefix(r.URL.Path, "/api/firmware/blob/")
	store.Lock.Lock()
	nodeID, ok := store.BlobToID[blob]
	node := store.Nodes[nodeID]
	store.Lock.Unlock()
	if !ok {
		http.NotFound(w, r)
		return
	}
	if r.URL.Query().Get("manifest") == "public" {
		writeJSON(w, map[string]any{"blob": blob, "payload": node.Data})
		return
	}
	writeJSON(w, map[string]any{"blob": blob, "status": "sealed"})
}

// firmwareIssue mints a signed manifest token for public blobs only.
// The signature binds {blob, ttl} cryptographically; intended use is for
// inventory readers to fetch their own public firmware payloads.
func firmwareIssue(w http.ResponseWriter, r *http.Request, store *state.Store) {
	blob := r.URL.Query().Get("blob")
	if blob == "" {
		http.Error(w, `{"error":"missing_blob"}`, http.StatusBadRequest)
		return
	}
	node, ok := store.NodeByBlob(blob)
	if !ok {
		http.NotFound(w, r)
		return
	}
	if node.Kind != "public" {
		http.Error(w, `{"error":"private_blob"}`, http.StatusForbidden)
		return
	}
	writeJSON(w, map[string]any{"manifest": firmware.Issue(store.Secret, blob, 3600)})
}

// firmwareRead hosts VULN-D. A valid manifest token is required to call this
// endpoint, but the signature only covers the manifest body (blob + ttl).
// The handler additionally consults `?reveal=1` from the querystring -- which
// is NOT part of the signed material -- and when set, returns the payload of
// whichever blob the caller pointed `?blob=` at. Any signed manifest (even one
// minted for the public drone) unlocks reveal on every blob in the fleet.
func firmwareRead(w http.ResponseWriter, r *http.Request, store *state.Store) {
	manifest, ok := firmware.Verify(store.Secret, r.URL.Query().Get("manifest"))
	if !ok {
		http.Error(w, `{"error":"bad_manifest"}`, http.StatusForbidden)
		return
	}
	blob := r.URL.Query().Get("blob")
	if blob == "" {
		blob = manifest.Blob
	}
	node, ok := store.NodeByBlob(blob)
	if !ok {
		http.NotFound(w, r)
		return
	}
	if r.URL.Query().Get("reveal") == "1" {
		writeJSON(w, map[string]any{"blob": blob, "ttl": manifest.TTL, "payload": node.Data})
		return
	}
	writeJSON(w, map[string]any{"blob": blob, "ttl": manifest.TTL, "kind": node.Kind})
}

// diagnosticPayload hosts VULN-E. The endpoint requires a JWT-like token; in
// the intended (HS256) path the operator's shared secret signs the token. The
// implementation also accepts `alg=KID`, looking the kid up against the
// registered-agent table and using that agent's `blob` as the HMAC key. Since
// /api/v2/agent/register returns the blob to the registering caller, anyone
// can mint a KID-signed token for any payload.node -- including the secret
// diagnostic flag node id leaked in attack_info.
func diagnosticPayload(w http.ResponseWriter, r *http.Request, store *state.Store) {
	raw := r.URL.Query().Get("token")
	lookup := func(kid string) (string, bool) {
		node, ok := store.NodeByID(kid)
		if !ok {
			return "", false
		}
		return node.Blob, true
	}
	_, payload, err := jobs.Verify(store.Secret, lookup, raw)
	if err != nil {
		http.Error(w, `{"error":"bad_token","reason":"`+err.Error()+`"}`, http.StatusForbidden)
		return
	}
	node, ok := store.NodeByID(payload.Node)
	if !ok {
		http.NotFound(w, r)
		return
	}
	writeJSON(w, map[string]any{"node": node.ID, "scope": payload.Scope, "payload": node.Data})
}

func writeJSON(w http.ResponseWriter, value any) {
	w.Header().Set("content-type", "application/json")
	_ = json.NewEncoder(w).Encode(value)
}
