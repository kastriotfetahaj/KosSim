package ops

import (
	"encoding/json"
	"net/http"
)

func Register(mux *http.ServeMux) {
	mux.HandleFunc("/api/jwt/inspect", func(w http.ResponseWriter, r *http.Request) { write(w, map[string]any{"alg": "none", "accepted": false}) })
	mux.HandleFunc("/debug/pprof", func(w http.ResponseWriter, r *http.Request) { write(w, map[string]any{"error": "protected in challenge build"}) })
	mux.HandleFunc("/api/crc/collision", func(w http.ResponseWriter, r *http.Request) { write(w, map[string]any{"crc": "demo-only"}) })
	mux.HandleFunc("/api/random/seed", func(w http.ResponseWriter, r *http.Request) { write(w, map[string]any{"seed": "ui-demo", "used_for_tokens": false}) })
	mux.HandleFunc("/admin", func(w http.ResponseWriter, r *http.Request) { write(w, map[string]any{"panel": "honeypot", "secrets": []string{}}) })
}

func write(w http.ResponseWriter, value any) {
	w.Header().Set("content-type", "application/json")
	_ = json.NewEncoder(w).Encode(value)
}
