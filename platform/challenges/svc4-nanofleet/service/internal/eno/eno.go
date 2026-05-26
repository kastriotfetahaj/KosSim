package eno

import "net/http"

type Task struct {
	Method         string `json:"method"`
	Flag           string `json:"flag"`
	CurrentRoundID int    `json:"current_round_id"`
	RelatedRoundID int    `json:"related_round_id"`
	VariantID      int    `json:"variant_id"`
}

func Authorized(r *http.Request, secret string) bool {
	sent := r.Header.Get("X-Checker-Secret")
	if sent == "" {
		sent = r.Header.Get("X-Service-Secret")
	}
	return sent != "" && sent == secret
}
