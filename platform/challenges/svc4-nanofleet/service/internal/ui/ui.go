package ui

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

func Index(w http.ResponseWriter) {
	body, err := os.ReadFile("/app/static/index.html")
	if err != nil {
		body = []byte("<!doctype html><title>NanoFleet</title><h1>NanoFleet</h1>")
	}
	w.Header().Set("content-type", "text/html; charset=utf-8")
	_, _ = w.Write(body)
}

func Static(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(r.URL.Path, "/static/")
	name = strings.Map(func(ch rune) rune {
		if ch >= 'a' && ch <= 'z' || ch >= 'A' && ch <= 'Z' || ch >= '0' && ch <= '9' || ch == '.' || ch == '-' || ch == '_' {
			return ch
		}
		return -1
	}, name)
	if strings.HasSuffix(name, ".css") {
		w.Header().Set("content-type", "text/css")
	}
	if strings.HasSuffix(name, ".js") {
		w.Header().Set("content-type", "application/javascript")
	}
	http.ServeFile(w, r, filepath.Join("/app/static", name))
}
