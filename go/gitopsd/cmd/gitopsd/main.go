package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

// DriftEvent represents a detected drift between manifest and cluster state
type DriftEvent struct {
	Timestamp     int64                  `json:"timestamp"`
	EventType     string                 `json:"event_type"` // "drift_detected", "drift_resolved", etc.
	Resource      string                 `json:"resource"`   // e.g., "deployments/my-app"
	Namespace     string                 `json:"namespace"`
	ManifestPath  string                 `json:"manifest_path"`
	DriftType     string                 `json:"drift_type"` // "missing", "mismatch", "unexpected"
	Details       map[string]interface{} `json:"details"`
	Severity      string                 `json:"severity"` // "low", "medium", "high"
	GitOpsVersion string                 `json:"gitops_version"`
}

// ManifestState represents the state of loaded manifests
type ManifestState struct {
	Path     string
	Content  []byte
	Kind     string
	Name     string
	Metadata map[string]interface{}
}

// ResourceState represents the state of a live cluster resource
type ResourceState struct {
	Kind      string
	Name      string
	Namespace string
	Version   string
	UID       string
}

const (
	gitopsVersion = "1.0.0"
	maxRetries    = 5
)

// Config represents the configuration for gitopsd
type Config struct {
	Interval      int    `yaml:"interval"`
	ManifestsPath string `yaml:"manifests_path"`
	CollectorURL  string `yaml:"collector_url"`
}

var (
	httpClient *http.Client
	config     Config
	logger     Logger
)

func init() {
	httpClient = &http.Client{
		Timeout: 30 * time.Second,
	}
}

func main() {
	// Print startup banner
	printBanner()

	// Load configuration
	var err error
	config, err = loadConfig()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to load configuration: %v\n", err)
		os.Exit(1)
	}
	logger = NewLogger("INFO")

	logger.Info("Configuration loaded successfully", map[string]interface{}{
		"interval":        config.Interval,
		"manifests_path":  config.ManifestsPath,
		"collector_url":   config.CollectorURL,
	})

	// Validate manifests directory exists
	if _, err := os.Stat(config.ManifestsPath); os.IsNotExist(err) {
		logger.Error("Manifests directory does not exist", map[string]interface{}{
			"path": config.ManifestsPath,
		})
		os.Exit(1)
	}

	// Validate API connectivity
	if err := validateAPIConnectivity(); err != nil {
		logger.Error("Failed to connect to API", map[string]interface{}{
			"error":          err.Error(),
			"collector_url":  config.CollectorURL,
		})
		os.Exit(1)
	}

	logger.Info("Successfully connected to API", map[string]interface{}{
		"collector_url": config.CollectorURL,
	})

	// Set up graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Create ticker for periodic manifest scanning
	ticker := time.NewTicker(time.Duration(config.Interval) * time.Second)
	defer ticker.Stop()

	logger.Info("Starting manifest drift detection", map[string]interface{}{
		"interval": config.Interval,
	})

	// Perform initial scan
	performDriftDetection()

	// Main event loop
	for {
		select {
		case <-ticker.C:
			// Periodically scan for drift
			performDriftDetection()

		case sig := <-sigChan:
			// Graceful shutdown
			logger.Info("Received shutdown signal", map[string]interface{}{
				"signal": sig.String(),
			})
			gracefulShutdown()
			os.Exit(0)
		}
	}
}

// printBanner prints the startup banner
func printBanner() {
	fmt.Println(`
╔═══════════════════════════════════════╗
║     Vigil GitOpsD started             ║
║     Version: 1.0.0                    ║
║     GitOps Drift Detection            ║
╚═══════════════════════════════════════╝
`)
}

// validateAPIConnectivity checks if the API is reachable
func validateAPIConnectivity() error {
	healthURL := config.CollectorURL + "/health"

	for attempt := 1; attempt <= 3; attempt++ {
		resp, err := httpClient.Get(healthURL)
		if err == nil && resp.StatusCode == http.StatusOK {
			resp.Body.Close()
			return nil
		}
		if resp != nil {
			resp.Body.Close()
		}

		if attempt < 3 {
			backoffDuration := time.Duration(1<<uint(attempt-1)) * time.Second
			time.Sleep(backoffDuration)
		}
	}

	return fmt.Errorf("API health check failed after 3 attempts")
}

// performDriftDetection orchestrates the complete drift detection cycle
func performDriftDetection() {
	logger.Debug("Starting drift detection scan", map[string]interface{}{})

	// Load all manifests from directory
	manifests, err := loadManifests(config.ManifestsPath)
	if err != nil {
		logger.Error("Failed to load manifests", map[string]interface{}{
			"error": err.Error(),
			"path":  config.ManifestsPath,
		})
		return
	}

	logger.Debug("Manifests loaded", map[string]interface{}{
		"count": len(manifests),
	})

	// Get live cluster state (simulated for environments without cluster access)
	clusterState := getLiveClusterState()

	logger.Debug("Cluster state retrieved", map[string]interface{}{
		"resources": len(clusterState),
	})

	// Detect drift between manifests and cluster state
	driftEvents := detectDrift(manifests, clusterState)

	if len(driftEvents) > 0 {
		logger.Info("Drift detected", map[string]interface{}{
			"drift_count": len(driftEvents),
		})

		// Report drift events to API
		for _, event := range driftEvents {
			if err := reportDriftEventWithRetry(&event); err != nil {
				logger.Error("Failed to report drift event", map[string]interface{}{
					"error":    err.Error(),
					"resource": event.Resource,
				})
			}
		}
	} else {
		logger.Debug("No drift detected", map[string]interface{}{})
	}
}

// loadManifests loads all YAML manifests from a directory
func loadManifests(path string) ([]ManifestState, error) {
	var manifests []ManifestState

	err := filepath.Walk(path, func(filePath string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		// Skip directories and non-YAML files
		if info.IsDir() || (!strings.HasSuffix(filePath, ".yaml") && !strings.HasSuffix(filePath, ".yml")) {
			return nil
		}

		// Read manifest file
		content, err := os.ReadFile(filePath)
		if err != nil {
			logger.Warn("Failed to read manifest file", map[string]interface{}{
				"path":  filePath,
				"error": err.Error(),
			})
			return nil
		}

		// Parse manifest metadata (simplified - assumes YAML with kind and metadata.name)
		manifest := ManifestState{
			Path:    filePath,
			Content: content,
		}

		// Extract kind and name from YAML (basic parsing)
		parseManifestMetadata(&manifest)

		manifests = append(manifests, manifest)

		logger.Debug("Manifest loaded", map[string]interface{}{
			"path": filePath,
			"kind": manifest.Kind,
			"name": manifest.Name,
		})

		return nil
	})

	if err != nil {
		return nil, err
	}

	return manifests, nil
}

// parseManifestMetadata extracts kind and name from manifest YAML
func parseManifestMetadata(manifest *ManifestState) {
	// Simple YAML parsing to extract kind and metadata.name
	lines := bytes.Split(manifest.Content, []byte("\n"))

	for _, line := range lines {
		trimmed := bytes.TrimSpace(line)

		// Look for "kind:" field
		if bytes.HasPrefix(trimmed, []byte("kind:")) {
			parts := bytes.Split(trimmed, []byte(":"))
			if len(parts) > 1 {
				manifest.Kind = strings.TrimSpace(string(bytes.TrimSpace(parts[1])))
			}
		}

		// Look for "name:" field under metadata
		if bytes.HasPrefix(trimmed, []byte("name:")) {
			parts := bytes.Split(trimmed, []byte(":"))
			if len(parts) > 1 {
				manifest.Name = strings.TrimSpace(string(bytes.TrimSpace(parts[1])))
			}
		}
	}
}

// getLiveClusterState retrieves the current state of resources in the cluster
// This is a simulated implementation for environments without cluster access
func getLiveClusterState() []ResourceState {
	// In a production environment, this would use Kubernetes client-go library
	// to query the actual cluster state. For now, we simulate some resources.

	return []ResourceState{
		{
			Kind:      "Deployment",
			Name:      "vigil-api",
			Namespace: "default",
			Version:   "1.0.0",
			UID:       "uid-123",
		},
		{
			Kind:      "Service",
			Name:      "vigil-api",
			Namespace: "default",
			Version:   "1.0.0",
			UID:       "uid-456",
		},
		{
			Kind:      "ConfigMap",
			Name:      "vigil-config",
			Namespace: "default",
			Version:   "1.0.0",
			UID:       "uid-789",
		},
	}
}

// detectDrift compares manifest definitions against live cluster state
func detectDrift(manifests []ManifestState, clusterState []ResourceState) []DriftEvent {
	var driftEvents []DriftEvent

	// Track resources found in cluster
	foundResources := make(map[string]bool)

	// Check each manifest against cluster state
	for _, manifest := range manifests {
		if manifest.Kind == "" || manifest.Name == "" {
			continue
		}

		// Look for matching resource in cluster
		found := false
		for _, resource := range clusterState {
			if resource.Kind == manifest.Kind && resource.Name == manifest.Name {
				found = true
				foundResources[resource.Kind+"/"+resource.Name] = true

				// Check for configuration mismatches
			drifted, details := checkConfigurationDrift(&manifest, &resource)
			if drifted {
					event := DriftEvent{
						Timestamp:     time.Now().Unix(),
						EventType:     "drift_detected",
						Resource:      resource.Kind + "/" + resource.Name,
						Namespace:     resource.Namespace,
						ManifestPath:  manifest.Path,
						DriftType:     "mismatch",
						Details:       details,
						Severity:      "medium",
						GitOpsVersion: gitopsVersion,
					}
					driftEvents = append(driftEvents, event)
				}
				break
			}
		}

		// Resource defined in manifest but not in cluster
		if !found {
			event := DriftEvent{
				Timestamp:     time.Now().Unix(),
				EventType:     "drift_detected",
				Resource:      manifest.Kind + "/" + manifest.Name,
				Namespace:     "unknown",
				ManifestPath:  manifest.Path,
				DriftType:     "missing",
				Details:       map[string]interface{}{"reason": "resource not found in cluster"},
				Severity:      "high",
				GitOpsVersion: gitopsVersion,
			}
			driftEvents = append(driftEvents, event)
		}
	}

	// Check for unexpected resources in cluster (not defined in any manifest)
	for _, resource := range clusterState {
		resourceKey := resource.Kind + "/" + resource.Name

		// Skip Kubernetes system resources
		if strings.HasPrefix(resource.Namespace, "kube-") || resource.Namespace == "kube-system" {
			continue
		}

		if !foundResources[resourceKey] {
			event := DriftEvent{
				Timestamp:     time.Now().Unix(),
				EventType:     "drift_detected",
				Resource:      resourceKey,
				Namespace:     resource.Namespace,
				ManifestPath:  "N/A",
				DriftType:     "unexpected",
				Details:       map[string]interface{}{"reason": "resource exists in cluster but not in manifests"},
				Severity:      "low",
				GitOpsVersion: gitopsVersion,
			}
			driftEvents = append(driftEvents, event)
		}
	}

	return driftEvents
}

// checkConfigurationDrift checks if a manifest differs from its live cluster state
func checkConfigurationDrift(manifest *ManifestState, resource *ResourceState) (bool, map[string]interface{}) {
	details := make(map[string]interface{})

	// Simplified drift detection - in production, would do deep YAML comparison
	// Check if manifest content hash matches resource state (simplified)

	// Example: check for specific markers or patterns that indicate drift
	manifestStr := string(manifest.Content)
	if strings.Contains(manifestStr, "DRIFT_MARKER") {
		details["reason"] = "manifest contains drift marker"
		details["current_version"] = resource.Version
		return true, details
	}

	// No drift detected
	return false, details
}

// reportDriftEventWithRetry sends drift events to the API with retry logic
func reportDriftEventWithRetry(event *DriftEvent) error {
	eventsURL := config.CollectorURL + "/gitopsd/events"

	for attempt := 0; attempt < maxRetries; attempt++ {
		if err := reportDriftEvent(eventsURL, event); err == nil {
			return nil
		}

		if attempt < maxRetries-1 {
			// Exponential backoff: 1s, 2s, 4s, 8s, 16s
			backoffDuration := time.Duration(1<<uint(attempt)) * time.Second
			logger.Warn("Failed to report drift event, retrying with backoff", map[string]interface{}{
				"attempt":          attempt + 1,
				"backoff_seconds":  backoffDuration.Seconds(),
				"max_retries":      maxRetries,
				"resource":         event.Resource,
			})
			time.Sleep(backoffDuration)
		}
	}

	return fmt.Errorf("failed to report drift event after %d attempts", maxRetries)
}

// reportDriftEvent sends a single drift event to the API via HTTP POST
func reportDriftEvent(url string, event *DriftEvent) error {
	jsonData, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("failed to marshal drift event: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create HTTP request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", fmt.Sprintf("vigil-gitopsd/%s", gitopsVersion))

	resp, err := httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("HTTP request failed: %w", err)
	}
	defer resp.Body.Close()

	// Discard response body
	io.ReadAll(resp.Body)

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("API returned status code %d", resp.StatusCode)
	}

	return nil
}

// loadConfig loads the configuration from environment variables with defaults
func loadConfig() (Config, error) {
	config := Config{
		Interval:      30,
		ManifestsPath: "./manifests",
		CollectorURL:  "http://localhost:8000/ingest",
	}

	// Override with environment variables if set
	if interval := os.Getenv("GITOPSD_INTERVAL"); interval != "" {
		fmt.Sscanf(interval, "%d", &config.Interval)
	}
	if path := os.Getenv("GITOPSD_MANIFESTS_PATH"); path != "" {
		config.ManifestsPath = path
	}
	if url := os.Getenv("GITOPSD_COLLECTOR_URL"); url != "" {
		config.CollectorURL = url
	}

	return config, nil
}

// gracefulShutdown performs cleanup on shutdown
func gracefulShutdown() {
	logger.Info("Shutting down gracefully", map[string]interface{}{})

	// Give in-flight requests time to complete
	shutdownTimeout := 5 * time.Second
	logger.Info("Waiting for in-flight requests to complete", map[string]interface{}{
		"timeout_seconds": shutdownTimeout.Seconds(),
	})

	time.Sleep(shutdownTimeout)

	logger.Info("GitOpsD shutdown complete", map[string]interface{}{})
}
