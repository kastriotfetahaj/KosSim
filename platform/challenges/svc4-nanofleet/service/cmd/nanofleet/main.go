package main

import (
	"log"
	"net/http"
	"os"

	"nanofleet/internal/routes"
	"nanofleet/internal/state"
)

func main() {
	store := state.New(os.Getenv("TEAM_NAME"), os.Getenv("SERVICE_NAME"), os.Getenv("SERVICE_PUSH_SECRET"), os.Getenv("BOOT_FLAG"))
	mux := routes.New(store)
	log.Fatal(http.ListenAndServe(":8080", mux))
}
