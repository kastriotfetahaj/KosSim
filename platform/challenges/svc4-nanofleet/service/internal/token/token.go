package token

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
)

type RouteToken struct {
	Prefix string `json:"prefix"`
}

func Sign(secret, prefix string) string {
	body, _ := json.Marshal(RouteToken{Prefix: prefix})
	body64 := base64.RawURLEncoding.EncodeToString(body)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(body64))
	return body64 + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func Verify(secret, raw string) (RouteToken, bool) {
	parts := strings.Split(raw, ".")
	if len(parts) != 2 {
		return RouteToken{}, false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(parts[0]))
	want := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(want), []byte(parts[1])) {
		return RouteToken{}, false
	}
	body, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return RouteToken{}, false
	}
	var tok RouteToken
	return tok, json.Unmarshal(body, &tok) == nil
}
