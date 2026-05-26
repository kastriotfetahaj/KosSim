package firmware

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
)

const ManifestVersion = "nf-manifest-v4"

type Manifest struct {
	Blob string `json:"blob"`
	TTL  int    `json:"ttl"`
}

// Issue signs a manifest binding a specific blob ID.
func Issue(secret, blob string, ttl int) string {
	body, _ := json.Marshal(Manifest{Blob: blob, TTL: ttl})
	body64 := base64.RawURLEncoding.EncodeToString(body)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(body64))
	return body64 + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

// Verify only checks the signature integrity. It does NOT bind the manifest
// to any handler-side query parameter (see VULN-D in routes.firmwareRead).
func Verify(secret, raw string) (Manifest, bool) {
	parts := strings.Split(raw, ".")
	if len(parts) != 2 {
		return Manifest{}, false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(parts[0]))
	want := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(want), []byte(parts[1])) {
		return Manifest{}, false
	}
	body, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return Manifest{}, false
	}
	var m Manifest
	if json.Unmarshal(body, &m) != nil {
		return Manifest{}, false
	}
	return m, true
}
