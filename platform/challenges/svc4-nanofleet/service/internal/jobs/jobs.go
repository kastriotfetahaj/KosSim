package jobs

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
)

type Header struct {
	Alg string `json:"alg"`
	Kid string `json:"kid,omitempty"`
}

type Payload struct {
	Node  string `json:"node"`
	Scope string `json:"scope"`
}

type KeyLookup func(kid string) (string, bool)

// Verify parses and validates a JWT-like diagnostic token of the form
// b64url(header_json).b64url(payload_json).b64url(sig). It supports two
// algorithms:
//
//   - "HS256": signature is HMAC-SHA256(secret, header64 + "." + payload64)
//   - "KID":   signature is HMAC-SHA256(lookup(kid), header64 + "." + payload64)
//
// VULN-E lives in the KID branch: the KeyLookup hands back the kid'd
// agent's `blob` string as the verification key. Any party that registers
// an agent learns that agent's blob (it is returned in the registration
// response) and can therefore mint a valid KID-signed token for any
// payload.node, including the secret diagnostic-flag node id.
func Verify(secret string, lookup KeyLookup, raw string) (Header, Payload, error) {
	parts := strings.Split(raw, ".")
	if len(parts) != 3 {
		return Header{}, Payload{}, errors.New("token: bad shape")
	}
	headerBytes, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return Header{}, Payload{}, errors.New("token: bad header b64")
	}
	var header Header
	if err := json.Unmarshal(headerBytes, &header); err != nil {
		return Header{}, Payload{}, errors.New("token: bad header json")
	}
	payloadBytes, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return Header{}, Payload{}, errors.New("token: bad payload b64")
	}
	var payload Payload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		return Header{}, Payload{}, errors.New("token: bad payload json")
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		return Header{}, Payload{}, errors.New("token: bad sig b64")
	}
	signed := parts[0] + "." + parts[1]
	var key []byte
	switch header.Alg {
	case "HS256":
		key = []byte(secret)
	case "KID":
		k, ok := lookup(header.Kid)
		if !ok {
			return Header{}, Payload{}, errors.New("token: unknown kid")
		}
		key = []byte(k)
	default:
		return Header{}, Payload{}, errors.New("token: unsupported alg")
	}
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(signed))
	if !hmac.Equal(mac.Sum(nil), sig) {
		return Header{}, Payload{}, errors.New("token: bad signature")
	}
	return header, payload, nil
}

// IssueHS256 mints an admin-bound diagnostic token. Used by the checker
// to seed the public surface; the bug does not depend on this codepath.
func IssueHS256(secret, node, scope string) string {
	header, _ := json.Marshal(Header{Alg: "HS256"})
	payload, _ := json.Marshal(Payload{Node: node, Scope: scope})
	header64 := base64.RawURLEncoding.EncodeToString(header)
	payload64 := base64.RawURLEncoding.EncodeToString(payload)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(header64 + "." + payload64))
	return header64 + "." + payload64 + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
