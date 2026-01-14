package main

import (
	"fmt"
	"os"
	"strconv"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// RemediationConfig represents the configuration for the Remediator
type RemediationConfig struct {
	Port          int    `yaml:"port"`
	APIHost       string `yaml:"api_host"`
	APIPort       int    `yaml:"api_port"`
	LogLevel      string `yaml:"log_level"`
	MaxConcurrent int    `yaml:"max_concurrent"`
	TaskQueueSize int    `yaml:"task_queue_size"`
	Interval      int    `yaml:"interval"`
}

// LoadConfig loads the configuration from file and environment variables
func LoadConfig() (*RemediationConfig, error) {
	config := &RemediationConfig{
		Port:          8081,
		APIHost:       "localhost",
		APIPort:       8000,
		LogLevel:      "INFO",
		MaxConcurrent: 5,
		TaskQueueSize: 100,
		Interval:      10,
	}

	// Try to load from YAML files
	possiblePaths := []string{
		"./configs/remediator.yaml",
		"/etc/vigil/remediator/config/remediator.yaml",
	}

	// Check if CONFIG_PATH environment variable is set
	if configPath := os.Getenv("CONFIG_PATH"); configPath != "" {
		possiblePaths = append([]string{configPath}, possiblePaths...)
	}

	configLoaded := false
	for _, path := range possiblePaths {
		if data, err := os.ReadFile(path); err == nil {
			if err := yaml.Unmarshal(data, config); err != nil {
				return nil, fmt.Errorf("failed to parse config file %s: %w", path, err)
			}
			configLoaded = true
			break
		}
	}

	if !configLoaded {
		// Silently continue with defaults if no file found
	}

	// Override with environment variables
	if port := os.Getenv("REMEDIATOR_PORT"); port != "" {
		if p, err := strconv.Atoi(port); err == nil {
			config.Port = p
		}
	}

	if apiHost := os.Getenv("API_HOST"); apiHost != "" {
		config.APIHost = apiHost
	}

	if apiPort := os.Getenv("API_PORT"); apiPort != "" {
		if p, err := strconv.Atoi(apiPort); err == nil {
			config.APIPort = p
		}
	}

	if logLevel := os.Getenv("LOG_LEVEL"); logLevel != "" {
		config.LogLevel = logLevel
	}

	if maxConcurrent := os.Getenv("MAX_CONCURRENT"); maxConcurrent != "" {
		if mc, err := strconv.Atoi(maxConcurrent); err == nil {
			config.MaxConcurrent = mc
		}
	}

	if taskQueueSize := os.Getenv("TASK_QUEUE_SIZE"); taskQueueSize != "" {
		if tqs, err := strconv.Atoi(taskQueueSize); err == nil {
			config.TaskQueueSize = tqs
		}
	}

	if interval := os.Getenv("POLLING_INTERVAL"); interval != "" {
		if i, err := strconv.Atoi(interval); err == nil {
			config.Interval = i
		}
	}

	return config, nil
}

// GetAPIURL returns the full API URL for the remediator
func (c *RemediationConfig) GetAPIURL() string {
	return fmt.Sprintf("http://%s:%d", c.APIHost, c.APIPort)
}

// GetListenerAddress returns the address to listen on
func (c *RemediationConfig) GetListenerAddress() string {
	return fmt.Sprintf(":%d", c.Port)
}
