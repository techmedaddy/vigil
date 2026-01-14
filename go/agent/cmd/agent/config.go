package main

import (
	"fmt"
	"os"
	"strconv"

	"gopkg.in/yaml.v3"
)

// Config represents the agent configuration
type Config struct {
	Interval      int    `yaml:"interval"`
	CollectorURL  string `yaml:"collector_url"`
	LogLevel      string `yaml:"log_level"`
	ReportMetrics bool   `yaml:"report_metrics"`
}

// LoadConfig loads configuration from file and environment variables
func LoadConfig() (*Config, error) {
	config := &Config{
		// Default values
		Interval:      10,
		CollectorURL:  "http://localhost:8000/ingest",
		LogLevel:      "INFO",
		ReportMetrics: true,
	}

	// Try to load from config file
	configPaths := []string{
		"./configs/agent.yaml",
		"/etc/vigil/agent/config/agent.yaml",
		os.Getenv("CONFIG_PATH"),
	}

	for _, path := range configPaths {
		if path != "" {
			if data, err := os.ReadFile(path); err == nil {
				if err := yaml.Unmarshal(data, config); err != nil {
					return nil, fmt.Errorf("failed to parse config file %s: %w", path, err)
				}
				break
			}
		}
	}

	// Override with environment variables
	if interval := os.Getenv("AGENT_INTERVAL"); interval != "" {
		if val, err := strconv.Atoi(interval); err == nil {
			config.Interval = val
		}
	}

	if collectorURL := os.Getenv("API_HOST"); collectorURL != "" {
		apiPort := os.Getenv("API_PORT")
		if apiPort == "" {
			apiPort = "8000"
		}
		config.CollectorURL = fmt.Sprintf("http://%s:%s/ingest", collectorURL, apiPort)
	}

	if logLevel := os.Getenv("LOG_LEVEL"); logLevel != "" {
		config.LogLevel = logLevel
	}

	// Validation
	if config.Interval < 1 {
		config.Interval = 10
	}

	if config.CollectorURL == "" {
		return nil, fmt.Errorf("collector_url is required")
	}

	return config, nil
}
