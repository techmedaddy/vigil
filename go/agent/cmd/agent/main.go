package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

// MetricsPayload represents the metrics sent to the API
type MetricsPayload struct {
	Timestamp    int64                  `json:"timestamp"`
	Hostname     string                 `json:"hostname"`
	Metrics      map[string]interface{} `json:"metrics"`
	AgentVersion string                 `json:"agent_version"`
}

const (
	agentVersion = "1.0.0"
	maxRetries   = 5
)

var (
	httpClient *http.Client
	config     *Config
	logger     Logger
)

func init() {
	// Initialize HTTP client with timeout
	httpClient = &http.Client{
		Timeout: 30 * time.Second,
	}
}

func main() {
	// Print startup banner
	printBanner()

	// Initialize configuration
	var err error
	config, err = LoadConfig()
	if err != nil {
		log.Fatalf("Failed to load configuration: %v", err)
	}

	// Initialize structured logging
	logger = NewLogger("INFO")
	logger.Info("Configuration loaded successfully", map[string]interface{}{
		"interval":       config.Interval,
		"collector_url":  config.CollectorURL,
	})

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

	// Create ticker for periodic metrics collection
	ticker := time.NewTicker(time.Duration(config.Interval) * time.Second)
	defer ticker.Stop()

	// Metrics collection loop
	logger.Info("Starting metrics collection", map[string]interface{}{
		"interval": config.Interval,
	})

	// Collect metrics immediately on startup
	collectAndSendMetrics()

	// Main event loop
	for {
		select {
		case <-ticker.C:
			// Periodically collect and send metrics
			collectAndSendMetrics()

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
║     Vigil Agent started               ║
║     Version: 1.0.0                    ║
║     Monitoring and Metrics Collection ║
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

// collectAndSendMetrics collects system metrics and sends them to the API
func collectAndSendMetrics() {
	hostname, err := os.Hostname()
	if err != nil {
		logger.Error("Failed to get hostname", map[string]interface{}{
			"error": err.Error(),
		})
		hostname = "unknown"
	}

	// Collect metrics
	metrics := make(map[string]interface{})

	// CPU metrics
	if cpuMetrics, err := collectCPUMetrics(); err != nil {
		logger.Warn("Failed to collect CPU metrics", map[string]interface{}{
			"error": err.Error(),
		})
	} else {
		metrics["cpu"] = cpuMetrics
	}

	// Memory metrics
	if memMetrics, err := collectMemoryMetrics(); err != nil {
		logger.Warn("Failed to collect memory metrics", map[string]interface{}{
			"error": err.Error(),
		})
	} else {
		metrics["memory"] = memMetrics
	}

	// Disk metrics
	if diskMetrics, err := collectDiskMetrics(); err != nil {
		logger.Warn("Failed to collect disk metrics", map[string]interface{}{
			"error": err.Error(),
		})
	} else {
		metrics["disk"] = diskMetrics
	}

	// Network metrics
	if netMetrics, err := collectNetworkMetrics(); err != nil {
		logger.Warn("Failed to collect network metrics", map[string]interface{}{
			"error": err.Error(),
		})
	} else {
		metrics["network"] = netMetrics
	}

	// Create payload
	payload := MetricsPayload{
		Timestamp:    time.Now().Unix(),
		Hostname:     hostname,
		Metrics:      metrics,
		AgentVersion: agentVersion,
	}

	// Send metrics with retry
	if err := sendMetricsWithRetry(&payload); err != nil {
		logger.Error("Failed to send metrics after retries", map[string]interface{}{
			"error": err.Error(),
		})
	} else {
		logger.Info("Metrics sent successfully", map[string]interface{}{
			"metric_count": len(metrics),
		})
	}
}

// collectCPUMetrics collects CPU utilization metrics
func collectCPUMetrics() (map[string]interface{}, error) {
	metrics := make(map[string]interface{})

	// Read /proc/stat for CPU stats
	data, err := os.ReadFile("/proc/stat")
	if err != nil {
		return nil, err
	}

	// Parse CPU line and extract utilization
	// This is a simplified implementation; production code would calculate actual utilization
	lines := bytes.Split(data, []byte("\n"))
	if len(lines) > 0 {
		cpuLine := string(lines[0])
		metrics["cores"] = 4 // Placeholder: should be detected from /proc/cpuinfo
		metrics["usage_percent"] = 25.5 // Placeholder: should be calculated from /proc/stat deltas
		metrics["raw_data"] = cpuLine
	}

	return metrics, nil
}

// collectMemoryMetrics collects memory utilization metrics
func collectMemoryMetrics() (map[string]interface{}, error) {
	metrics := make(map[string]interface{})

	// Read /proc/meminfo for memory stats
	data, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return nil, err
	}

	// Parse memory info
	lines := bytes.Split(data, []byte("\n"))
	memInfo := make(map[string]uint64)

	for _, line := range lines {
		fields := bytes.Fields(line)
		if len(fields) >= 2 {
			key := string(bytes.TrimSuffix(fields[0], []byte(":")))
			var value uint64
			fmt.Sscanf(string(fields[1]), "%d", &value)
			memInfo[key] = value
		}
	}

	if memTotal, ok := memInfo["MemTotal"]; ok {
		if memAvailable, ok := memInfo["MemAvailable"]; ok {
			usagePercent := float64(memTotal-memAvailable) / float64(memTotal) * 100
			metrics["total_kb"] = memTotal
			metrics["available_kb"] = memAvailable
			metrics["used_kb"] = memTotal - memAvailable
			metrics["usage_percent"] = usagePercent
		}
	}

	return metrics, nil
}

// collectDiskMetrics collects disk utilization metrics
func collectDiskMetrics() (map[string]interface{}, error) {
	metrics := make(map[string]interface{})

	// Read /proc/mounts for mounted filesystems
	data, err := os.ReadFile("/proc/mounts")
	if err != nil {
		return nil, err
	}

	// Parse mount points
	lines := bytes.Split(data, []byte("\n"))
	diskList := []map[string]interface{}{}

	for _, line := range lines {
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		fields := bytes.Fields(line)
		if len(fields) >= 2 {
			device := string(fields[0])
			mountPoint := string(fields[1])

			// Skip pseudo filesystems
			if strings.HasPrefix(device, "sys") ||
				strings.HasPrefix(device, "proc") ||
				strings.HasPrefix(device, "dev") {
				continue
			}

			// Create disk entry (simplified)
			diskEntry := map[string]interface{}{
				"device":      device,
				"mount_point": mountPoint,
				"total_gb":    100, // Placeholder
				"used_gb":     50,  // Placeholder
				"free_gb":     50,  // Placeholder
			}
			diskList = append(diskList, diskEntry)
		}
	}

	metrics["filesystems"] = diskList
	return metrics, nil
}

// collectNetworkMetrics collects network interface metrics
func collectNetworkMetrics() (map[string]interface{}, error) {
	metrics := make(map[string]interface{})

	// Read /proc/net/dev for network stats
	data, err := os.ReadFile("/proc/net/dev")
	if err != nil {
		return nil, err
	}

	// Parse network interfaces
	lines := bytes.Split(data, []byte("\n"))
	interfaces := []map[string]interface{}{}

	for _, line := range lines[2:] { // Skip header lines
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}

		// Split by colon to separate interface name from stats
		parts := bytes.Split(line, []byte(":"))
		if len(parts) == 2 {
			ifName := string(bytes.TrimSpace(parts[0]))
			stats := bytes.Fields(parts[1])

			if len(stats) >= 2 {
				var rxBytes, txBytes uint64
				fmt.Sscanf(string(stats[0]), "%d", &rxBytes)
				fmt.Sscanf(string(stats[8]), "%d", &txBytes)

				ifEntry := map[string]interface{}{
					"name":       ifName,
					"rx_bytes":   rxBytes,
					"tx_bytes":   txBytes,
					"rx_packets": 0, // Can be extracted from stats
					"tx_packets": 0, // Can be extracted from stats
				}
				interfaces = append(interfaces, ifEntry)
			}
		}
	}

	metrics["interfaces"] = interfaces
	return metrics, nil
}

// sendMetricsWithRetry sends metrics to the API with exponential backoff retry
func sendMetricsWithRetry(payload *MetricsPayload) error {
	metricsURL := config.CollectorURL + "/agent/metrics"

	for attempt := 0; attempt < maxRetries; attempt++ {
		if err := sendMetrics(metricsURL, payload); err == nil {
			return nil
		}

		if attempt < maxRetries-1 {
			// Exponential backoff: 1s, 2s, 4s, 8s, 16s
			backoffDuration := time.Duration(1<<uint(attempt)) * time.Second
			logger.Warn("Failed to send metrics, retrying with backoff", map[string]interface{}{
				"attempt":          attempt + 1,
				"backoff_seconds":  backoffDuration.Seconds(),
				"max_retries":      maxRetries,
			})
			time.Sleep(backoffDuration)
		}
	}

	return fmt.Errorf("failed to send metrics after %d attempts", maxRetries)
}

// sendMetrics sends metrics to the API via HTTP POST
func sendMetrics(url string, payload *MetricsPayload) error {
	jsonData, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal metrics: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create HTTP request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", fmt.Sprintf("vigil-agent/%s", agentVersion))

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

// gracefulShutdown performs cleanup on shutdown
func gracefulShutdown() {
	logger.Info("Shutting down gracefully", map[string]interface{}{})

	// Give in-flight requests time to complete
	shutdownTimeout := 5 * time.Second
	logger.Info("Waiting for in-flight requests to complete", map[string]interface{}{
		"timeout_seconds": shutdownTimeout.Seconds(),
	})

	time.Sleep(shutdownTimeout)

	logger.Info("Agent shutdown complete", map[string]interface{}{})
}
