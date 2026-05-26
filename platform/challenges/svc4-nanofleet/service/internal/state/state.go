package state

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

type Node struct {
	ID      string `json:"id"`
	Blob    string `json:"blob"`
	Payload int    `json:"payload"`
	Kind    string `json:"kind"`
	Data    string `json:"data,omitempty"`
}

type Job struct {
	ID       string `json:"id"`
	NodeID   string `json:"node_id"`
	Template string `json:"template"`
	State    string `json:"state"`
	Result   string `json:"result"`
}

type Store struct {
	Team     string
	Service  string
	Secret   string
	Flags    map[string]string
	Nodes    map[string]Node
	BlobToID map[string]string
	Jobs     map[string]Job
	DataDir  string
	Lock     sync.Mutex
}

type diskState struct {
	Flags    map[string]string `json:"flags"`
	Nodes    map[string]Node   `json:"nodes"`
	BlobToID map[string]string `json:"blob_to_id"`
	Jobs     map[string]Job    `json:"jobs"`
}

func New(team, service, secret, boot string) *Store {
	if team == "" {
		team = "team"
	}
	if service == "" {
		service = "svc4"
	}
	if secret == "" {
		secret = "rotate-secret"
	}
	if boot == "" {
		boot = "FLAG{BOOT_NANOFLEET}"
	}
	dataDir := os.Getenv("NANOFLEET_DATA_DIR")
	if dataDir == "" {
		dataDir = "/var/lib/nanofleet"
	}
	s := &Store{Team: team, Service: service, Secret: secret, Flags: map[string]string{}, Nodes: map[string]Node{}, BlobToID: map[string]string{}, Jobs: map[string]Job{}, DataDir: dataDir}
	s.Load()
	s.PutFlag(0, 0, boot)
	s.PutFlag(0, 1, boot+"_MANIFEST")
	s.PutFlag(0, 2, boot+"_DIAGNOSTIC")
	s.Nodes["public-drone"] = Node{ID: "public-drone", Blob: "public-blob", Payload: 0, Kind: "public", Data: "nominal"}
	s.BlobToID["public-blob"] = "public-drone"
	s.persist()
	return s
}

func key(tick, payload int) string { return fmt.Sprintf("%d:%d", tick, payload) }

func ShortHash(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])[:18]
}

func (s *Store) PutFlag(tick, payload int, flag string) string {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	s.Flags[key(tick, payload)] = flag
	node := ShortHash(fmt.Sprintf("%s:%d:%d:%s", s.Team, tick, payload, flag))
	blob := ShortHash("blob:" + node)
	kind := "secret"
	switch payload {
	case 1:
		kind = "manifest"
	case 2:
		kind = "diagnostic"
	}
	s.Nodes[node] = Node{ID: node, Blob: blob, Payload: payload, Kind: kind, Data: flag}
	s.BlobToID[blob] = node
	s.persist()
	info, _ := json.Marshal(map[string]any{"a": node, "b": blob, "p": payload})
	return string(info)
}

func (s *Store) GetFlag(tick, payload int, expected string) bool {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	if s.Flags[key(tick, payload)] != expected {
		return false
	}
	for _, node := range s.Nodes {
		if node.Data == expected && node.Payload == payload {
			return true
		}
	}
	return false
}

func (s *Store) PutNoise(tick, payload int) {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	node := ShortHash(fmt.Sprintf("%s:noise:%d:%d", s.Team, tick, payload))
	blob := ShortHash("blob:" + node)
	s.Nodes[node] = Node{ID: node, Blob: blob, Payload: payload, Kind: "public", Data: fmt.Sprintf("sample:%s:%d:%d", s.Service, tick, payload)}
	s.BlobToID[blob] = node
	s.persist()
}

func (s *Store) GetNoise(tick, payload int) bool {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	node := ShortHash(fmt.Sprintf("%s:noise:%d:%d", s.Team, tick, payload))
	item, ok := s.Nodes[node]
	return ok && item.Kind == "public"
}

func (s *Store) Havoc(tick, payload int) bool {
	s.PutNoise(tick, payload)
	s.Lock.Lock()
	defer s.Lock.Unlock()
	return len(s.Nodes) > 0 && len(s.BlobToID) > 0
}

func (s *Store) RegisterNode(label string) Node {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	id := ShortHash(s.Team + ":agent:" + label)
	blob := ShortHash("blob:" + id)
	node := Node{ID: id, Blob: blob, Payload: 0, Kind: "agent", Data: "ready:" + label}
	s.Nodes[id] = node
	s.BlobToID[blob] = id
	s.persist()
	return node
}

func (s *Store) Schedule(nodeID, template string) Job {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	node := s.Nodes[nodeID]
	id := ShortHash(s.Team + ":job:" + nodeID + ":" + template + fmt.Sprintf(":%d", len(s.Jobs)))
	job := Job{ID: id, NodeID: nodeID, Template: template, State: "SUCCESS", Result: "ok:" + node.Kind}
	s.Jobs[id] = job
	s.persist()
	return job
}

func (s *Store) Job(id string) (Job, bool) {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	job, ok := s.Jobs[id]
	return job, ok
}

func (s *Store) NodeByID(id string) (Node, bool) {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	n, ok := s.Nodes[id]
	return n, ok
}

func (s *Store) NodeByBlob(blob string) (Node, bool) {
	s.Lock.Lock()
	defer s.Lock.Unlock()
	id, ok := s.BlobToID[blob]
	if !ok {
		return Node{}, false
	}
	n, ok := s.Nodes[id]
	return n, ok
}

func (s *Store) Load() {
	raw, err := os.ReadFile(filepath.Join(s.DataDir, "state.json"))
	if err != nil {
		return
	}
	var snap diskState
	if json.Unmarshal(raw, &snap) != nil {
		return
	}
	if snap.Flags != nil {
		s.Flags = snap.Flags
	}
	if snap.Nodes != nil {
		s.Nodes = snap.Nodes
	}
	if snap.BlobToID != nil {
		s.BlobToID = snap.BlobToID
	}
	if snap.Jobs != nil {
		s.Jobs = snap.Jobs
	}
}

func (s *Store) persist() {
	_ = os.MkdirAll(filepath.Join(s.DataDir, "jobs"), 0o755)
	raw, err := json.Marshal(diskState{Flags: s.Flags, Nodes: s.Nodes, BlobToID: s.BlobToID, Jobs: s.Jobs})
	if err == nil {
		_ = os.WriteFile(filepath.Join(s.DataDir, "state.json"), raw, 0o600)
	}
	_ = os.WriteFile(filepath.Join(s.DataDir, "jobs", "latest.log"), []byte(fmt.Sprintf("%d\n", len(s.Nodes))), 0o600)
}
