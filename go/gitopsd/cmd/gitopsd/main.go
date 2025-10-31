package main

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"path/filepath"
	"time"

	// Assuming 'vigil' is the Go module name defined in go.mod
	"vigil/gitopsd/pkg/gitopsd"

)

var (
	httpClient = &http.Client{Timeout: 10 * time.Second}
)

// postDriftNotification sends an alert to the collector about manifest drift.
func postDriftNotification(url, filePath string) {
	// Use the file name as the target
	target := filepath.Base(filePath)

	payload := map[string]string{
		"target":  target,
		"action":  "reconcile",
		"status":  "pending",
		"details": "Detected manifest drift in " + filePath,
	}

	jsonData, err := json.Marshal(payload)
	if err != nil {
		log.Printf("Error: Failed to marshal JSON for %s: %v", target, err)
		return
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		log.Printf("Error: Failed to create request for %s: %v", target, err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		log.Printf("Error: Failed to POST drift notification for %s: %v", target, err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		log.Printf("Warning: Non-2xx response (%d) from collector for %s", resp.StatusCode, target)
	} else {
		log.Printf("Successfully reported drift for %s to collector.", target)
	}
}

func main() {
	log.Println("Starting Vigil GitOps Daemon...")

	// 1. Load configuration
	config := gitopsd.LoadConfig("configs/gitopsd.yaml")
	log.Printf("Config loaded: Watching %s (Interval: %ds)", config.ManifestsPath, config.Interval)
	log.Printf("Reporting drift to: %s", config.CollectorURL)

	// 2. Perform initial scan
	currentState := gitopsd.ScanManifests(config.ManifestsPath)
	log.Printf("Initial scan complete. Found %d manifests.", len(currentState))

	// 3. Start the watch loop
	ticker := time.NewTicker(time.Duration(config.Interval) * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		log.Println("Scanning for manifest drift...")

		// Scan file system
		newState := gitopsd.ScanManifests(config.ManifestsPath)

		// Compare with previous state
		changes := gitopsd.DetectChanges(currentState, newState)

		if len(changes) > 0 {
			log.Printf("Detected drift in %d file(s).", len(changes))
			for _, file := range changes {
				log.Printf(" - Drift detected: %s", file)
				// Report each change to the collector
				go postDriftNotification(config.CollectorURL, file)
			}
		} else {
			log.Println("No drift detected.")
		}

		// Update state for next cycle
		currentState = newState
	}
}
