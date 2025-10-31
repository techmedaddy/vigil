package main

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Port              int    `yaml:"port"`
	CollectorAuditURL string `yaml:"collector_audit_url"`
}

const (
	defaultPort            = 8081
	defaultCollectorURL    = "http://127.0.0.1:8000/actions"
	configPath             = "configs/remediator.yaml"
	failureLimit           = 3
	failureWindow          = 5 * time.Minute
)

var (
	failureTimestamps = make(map[string][]time.Time)
	mu                sync.Mutex
	httpClient        = &http.Client{Timeout: 5 * time.Second}
	collectorAuditURL string // Will be set from config in main
)

func loadConfig() Config {
	conf := Config{
		Port:              defaultPort,
		CollectorAuditURL: defaultCollectorURL,
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		log.Printf("Warning: Could not read config file %s (%v). Using defaults.", configPath, err)
		return conf
	}

	if err := yaml.Unmarshal(data, &conf); err != nil {
		log.Printf("Warning: Could not parse config file %s (%v). Using defaults.", configPath, err)
		return Config{Port: defaultPort, CollectorAuditURL: defaultCollectorURL}
	}

	if conf.Port <= 0 {
		conf.Port = defaultPort
	}
	if conf.CollectorAuditURL == "" {
		conf.CollectorAuditURL = defaultCollectorURL
	}

	return conf
}

// postToActionLog sends a status update to the collector.
func postToActionLog(payload map[string]interface{}) {
	jsonData, err := json.Marshal(payload)
	if err != nil {
		log.Printf("Error marshaling action log payload: %v", err)
		return
	}

	req, err := http.NewRequest("POST", collectorAuditURL, bytes.NewBuffer(jsonData))
	if err != nil {
		log.Printf("Error creating action log request: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		log.Printf("Error sending action log: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		log.Printf("Action log received non-2xx status: %d", resp.StatusCode)
	}
}

// recordFailure logs a failure event for a given target.
func recordFailure(target string) {
	mu.Lock()
	defer mu.Unlock()
	failureTimestamps[target] = append(failureTimestamps[target], time.Now())
}

// tooManyFailures checks if the circuit breaker should be open for a target.
func tooManyFailures(target string) bool {
	mu.Lock()
	defer mu.Unlock()

	timestamps, ok := failureTimestamps[target]
	if !ok {
		return false
	}

	fiveMinutesAgo := time.Now().Add(-failureWindow)
	var recentFailures []time.Time
	for _, ts := range timestamps {
		if ts.After(fiveMinutesAgo) {
			recentFailures = append(recentFailures, ts)
		}
	}

	failureTimestamps[target] = recentFailures
	return len(recentFailures) >= failureLimit
}

func remediateHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Only POST method is allowed", http.StatusMethodNotAllowed)
		return
	}

	defer r.Body.Close()
	body, err := io.ReadAll(r.Body)
	if err != nil {
		log.Printf("Error reading request body: %v", err)
		http.Error(w, "Error reading request body", http.StatusInternalServerError)
		return
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(body, &payload); err != nil {
		log.Printf("Error unmarshaling JSON: %v", err)
		http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
		return
	}

	log.Printf("Received payload: %s", string(body))

	target, ok := payload["service"].(string)
	if !ok {
		log.Printf("Payload missing 'service' field")
		http.Error(w, "Payload missing 'service' field", http.StatusBadRequest)
		return
	}

	recordFailure(target)

	if tooManyFailures(target) {
		log.Printf("Circuit open for %s", target)
		details := map[string]string{"reason": "circuit open"}
		actionPayload := map[string]interface{}{
			"target":  target,
			"action":  "restart",
			"status":  "blocked",
			"details": details,
		}
		go postToActionLog(actionPayload)
		http.Error(w, "Circuit open: too many failures", http.StatusServiceUnavailable)
		return
	}

	log.Println("Simulating action: Restarting service...")

	actionPayload := map[string]interface{}{
		"target":  target,
		"action":  "restart",
		"status":  "success",
		"details": payload,
	}
	go postToActionLog(actionPayload)

	response := map[string]string{"status": "restarted"}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)

	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Printf("Error encoding JSON response: %v", err)
	}
}

func main() {
	config := loadConfig()
	collectorAuditURL = config.CollectorAuditURL
	listenAddr := ":" + strconv.Itoa(config.Port)

	http.HandleFunc("/remediate", remediateHandler)
	log.Printf("Remediator running on %s", listenAddr)
	if err := http.ListenAndServe(listenAddr, nil); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}

