package main

import (
	"bytes"
	"encoding/json"
	"log"
	"math/rand"
	"net/http"
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

type Metric struct {
	Name  string  `json:"name"`
	Value float64 `json:"value"`
}

type Config struct {
	CollectorURL string `yaml:"collector_url"`
	Interval     int    `yaml:"interval"`
}

const (
	defaultCollectorURL = "http://127.0.0.1:8000/ingest"
	defaultInterval     = 10
	configPath          = "configs/agent.yaml"
)

func loadConfig() Config {
	conf := Config{
		CollectorURL: defaultCollectorURL,
		Interval:     defaultInterval,
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		log.Printf("Warning: Could not read config file %s (%v). Using defaults.", configPath, err)
		return conf
	}

	if err := yaml.Unmarshal(data, &conf); err != nil {
		log.Printf("Warning: Could not parse config file %s (%v). Using defaults.", configPath, err)
		// Return the default config in case of unmarshal error
		return Config{CollectorURL: defaultCollectorURL, Interval: defaultInterval}
	}

	// Ensure partial configs are filled with defaults
	if conf.CollectorURL == "" {
		conf.CollectorURL = defaultCollectorURL
	}
	if conf.Interval <= 0 {
		conf.Interval = defaultInterval
	}

	return conf
}

func main() {
	config := loadConfig()
	collectorURL := config.CollectorURL
	interval := time.Duration(config.Interval) * time.Second

	client := &http.Client{Timeout: 5 * time.Second}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	r := rand.New(rand.NewSource(time.Now().UnixNano()))

	log.Printf("Agent started. Sending metrics to %s every %ds", collectorURL, config.Interval)

	for range ticker.C {
		go sendMetric(collectorURL, client, r)
	}
}

func sendMetric(url string, client *http.Client, r *rand.Rand) {
	data := Metric{
		Name:  "cpu_usage",
		Value: r.Float64(),
	}

	payload, err := json.Marshal(data)
	if err != nil {
		log.Printf("marshal error: %v", err)
		return
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(payload))
	if err != nil {
		log.Printf("Failed to create request: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		log.Printf("send error: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		log.Printf("non-2xx response: %d", resp.StatusCode)
	}
}
