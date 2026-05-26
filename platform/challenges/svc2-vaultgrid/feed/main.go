// VaultGrid feed sidecar.
//
// Append-only TLV stream on disk plus a SQLite index of (id, offset, length,
// tenant). Records on the wire are [type:u8][length:u32 BE][value:length].
// The /append endpoint trusts the caller-supplied `length` field separately
// from the actual data length, which is the length-confusion surface used by
// flagstore 2.
package main

import (
	"database/sql"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

type App struct {
	mu     sync.Mutex
	db     *sql.DB
	log    *os.File
	secret string
}

const schemaSQL = `
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL,
    type INTEGER NOT NULL,
    file_offset INTEGER NOT NULL,
    length INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_tenant ON records (tenant);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    ts INTEGER NOT NULL
);
`

func mustEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func newApp() *App {
	dir := mustEnv("VAULTGRID_FEED_DATA_DIR", "/var/lib/vaultgrid-feed")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		log.Fatalf("feed mkdir: %v", err)
	}
	dbPath := filepath.Join(dir, "feed.db")
	db, err := sql.Open("sqlite3", dbPath+"?_journal_mode=WAL&_busy_timeout=5000")
	if err != nil {
		log.Fatalf("feed sqlite: %v", err)
	}
	if _, err := db.Exec(schemaSQL); err != nil {
		log.Fatalf("feed schema: %v", err)
	}
	logPath := filepath.Join(dir, "stream.log")
	lf, err := os.OpenFile(logPath, os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		log.Fatalf("feed log open: %v", err)
	}
	return &App{db: db, log: lf, secret: mustEnv("SERVICE_PUSH_SECRET", "rotate-secret")}
}

func (a *App) audit(actor, action, target string) {
	_, _ = a.db.Exec(
		"INSERT INTO audit (actor, action, target, ts) VALUES (?, ?, ?, ?)",
		actor, action, target, time.Now().UnixMilli(),
	)
}

func (a *App) requireSecret(r *http.Request) bool {
	return r.Header.Get("X-Checker-Secret") == a.secret
}

func writeJSON(w http.ResponseWriter, code int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(body)
}

type appendReq struct {
	ID     string `json:"id"`
	Tenant string `json:"tenant"`
	Type   uint8  `json:"type"`
	Value  string `json:"value_hex"`
	Length *int64 `json:"length"`
}

func (a *App) handleAppend(w http.ResponseWriter, r *http.Request) {
	var body appendReq
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_json"})
		return
	}
	value, err := hex.DecodeString(body.Value)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_hex"})
		return
	}
	if body.ID == "" || body.Tenant == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing_field"})
		return
	}
	if body.Tenant != "public" && !a.requireSecret(r) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	stated := int64(len(value))
	if body.Length != nil {
		stated = *body.Length
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	offset, err := a.log.Seek(0, io.SeekEnd)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "seek"})
		return
	}
	header := make([]byte, 5)
	header[0] = body.Type
	binary.BigEndian.PutUint32(header[1:], uint32(stated))
	if _, err := a.log.Write(header); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "write_header"})
		return
	}
	if _, err := a.log.Write(value); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "write_value"})
		return
	}
	if _, err := a.db.Exec(
		"INSERT OR REPLACE INTO records (id, tenant, type, file_offset, length, created_at) VALUES (?, ?, ?, ?, ?, ?)",
		body.ID, body.Tenant, int(body.Type), offset+5, stated, time.Now().UnixMilli(),
	); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "index"})
		return
	}
	actor := "public"
	if a.requireSecret(r) {
		actor = "checker"
	}
	a.audit(actor, "feed.append", body.ID)
	writeJSON(w, http.StatusOK, map[string]any{
		"id":     body.ID,
		"tenant": body.Tenant,
		"offset": offset,
		"length": stated,
	})
}

type recordRow struct {
	ID         string
	Tenant     string
	Type       int
	FileOffset int64
	Length     int64
	CreatedAt  int64
}

func (a *App) loadRecord(id string) (*recordRow, error) {
	row := a.db.QueryRow(
		"SELECT id, tenant, type, file_offset, length, created_at FROM records WHERE id = ?",
		id,
	)
	var r recordRow
	if err := row.Scan(&r.ID, &r.Tenant, &r.Type, &r.FileOffset, &r.Length, &r.CreatedAt); err != nil {
		return nil, err
	}
	return &r, nil
}

func (a *App) readBytes(offset, length int64) ([]byte, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	end, err := a.log.Seek(0, io.SeekEnd)
	if err != nil {
		return nil, err
	}
	if offset > end {
		return nil, errors.New("offset past end")
	}
	if offset+length > end {
		length = end - offset
	}
	if length < 0 {
		length = 0
	}
	buf := make([]byte, length)
	if _, err := a.log.ReadAt(buf, offset); err != nil && !errors.Is(err, io.EOF) {
		return nil, err
	}
	return buf, nil
}

func (a *App) handleShow(w http.ResponseWriter, r *http.Request) {
	id := r.URL.Query().Get("id")
	tenant := r.URL.Query().Get("tenant")
	if id == "" || tenant == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing_field"})
		return
	}
	row, err := a.loadRecord(id)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not_found"})
		return
	}
	if row.Tenant != tenant {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "wrong_tenant"})
		return
	}
	buf, err := a.readBytes(row.FileOffset, row.Length)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "read"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id":        row.ID,
		"tenant":    row.Tenant,
		"type":      row.Type,
		"length":    row.Length,
		"value_hex": hex.EncodeToString(buf),
	})
}

func (a *App) handleList(w http.ResponseWriter, r *http.Request) {
	tenant := r.URL.Query().Get("tenant")
	if tenant == "" {
		tenant = "public"
	}
	rows, err := a.db.Query(
		"SELECT id, tenant, type, file_offset, length, created_at FROM records WHERE tenant = ? ORDER BY file_offset ASC LIMIT 200",
		tenant,
	)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"records": []any{}})
		return
	}
	defer rows.Close()
	out := make([]map[string]any, 0)
	for rows.Next() {
		var rec recordRow
		if err := rows.Scan(&rec.ID, &rec.Tenant, &rec.Type, &rec.FileOffset, &rec.Length, &rec.CreatedAt); err != nil {
			continue
		}
		out = append(out, map[string]any{
			"id":         rec.ID,
			"tenant":     rec.Tenant,
			"type":       rec.Type,
			"length":     rec.Length,
			"created_at": rec.CreatedAt,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"records": out, "tenant": tenant})
}

func (a *App) handleRange(w http.ResponseWriter, r *http.Request) {
	offsetStr := r.URL.Query().Get("offset")
	lengthStr := r.URL.Query().Get("length")
	offset, err := strconv.ParseInt(offsetStr, 10, 64)
	if err != nil || offset < 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_offset"})
		return
	}
	length, err := strconv.ParseInt(lengthStr, 10, 64)
	if err != nil || length < 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad_length"})
		return
	}
	if length > 65536 {
		length = 65536
	}
	buf, err := a.readBytes(offset, length)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "read"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"offset": offset,
		"length": int64(len(buf)),
		"hex":    hex.EncodeToString(buf),
	})
}

func (a *App) handleReplay(w http.ResponseWriter, r *http.Request) {
	if !a.requireSecret(r) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	end, err := a.log.Seek(0, io.SeekEnd)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "seek"})
		return
	}
	buf := make([]byte, end)
	if _, err := a.log.ReadAt(buf, 0); err != nil && !errors.Is(err, io.EOF) {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "read"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"stream_hex": hex.EncodeToString(buf), "length": end})
}

func (a *App) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "up", "name": "vaultgrid-feed"})
}

func main() {
	app := newApp()
	mux := http.NewServeMux()
	mux.HandleFunc("/health", app.handleHealth)
	mux.HandleFunc("/api/feed/append", app.handleAppend)
	mux.HandleFunc("/api/feed/show", app.handleShow)
	mux.HandleFunc("/api/feed/records", app.handleList)
	mux.HandleFunc("/api/feed/replay", app.handleReplay)
	mux.HandleFunc("/api/feed/range", app.handleRange)
	addr := mustEnv("VAULTGRID_FEED_ADDR", ":4103")
	srv := &http.Server{
		Addr:         addr,
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}
	fmt.Printf("vaultgrid-feed listening on %s\n", addr)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf("feed serve: %v", err)
	}
}
