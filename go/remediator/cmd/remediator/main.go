package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"syscall"
	"time"
)

// RemediationTask represents a task to remediate a policy violation
type RemediationTask struct {
	ID            string                 `json:"id"`
	Timestamp     int64                  `json:"timestamp"`
	Resource      string                 `json:"resource"`   // e.g., "deployment/my-app"
	Namespace     string                 `json:"namespace"`
	Action        string                 `json:"action"`     // e.g., "restart", "scale", "apply_manifest"
	Parameters    map[string]interface{} `json:"parameters"` // action-specific parameters
	Priority      string                 `json:"priority"`   // "low", "medium", "high"
	PolicyID      string                 `json:"policy_id"`
	Timeout       int                    `json:"timeout"`     // seconds
	MaxRetries    int                    `json:"max_retries"`
}

// RemediationResult represents the result of a remediation action
type RemediationResult struct {
	TaskID        string                 `json:"task_id"`
	Timestamp     int64                  `json:"timestamp"`
	Status        string                 `json:"status"`     // "success", "failed", "timeout", "partial"
	Resource      string                 `json:"resource"`
	Namespace     string                 `json:"namespace"`
	Action        string                 `json:"action"`
	Duration      int                    `json:"duration"` // milliseconds
	ErrorMessage  string                 `json:"error_message,omitempty"`
	Details       map[string]interface{} `json:"details"`
	RemediatorID  string                 `json:"remediator_id"`
	RemediatorVersion string              `json:"remediator_version"`
	RetryAttempts int                    `json:"retry_attempts,omitempty"`
}

// RetryConfig holds retry configuration
type RetryConfig struct {
	MaxAttempts      int
	BaseDelay        time.Duration
	MaxDelay         time.Duration
	ExponentialBase  float64
}

// DefaultRetryConfig returns default retry configuration
func DefaultRetryConfig() RetryConfig {
	return RetryConfig{
		MaxAttempts:     3,
		BaseDelay:       1 * time.Second,
		MaxDelay:        60 * time.Second,
		ExponentialBase: 2.0,
	}
}

// CalculateBackoff calculates exponential backoff delay
func (rc RetryConfig) CalculateBackoff(attempt int) time.Duration {
	delay := float64(rc.BaseDelay) * float64(1<<uint(attempt))
	if delay > float64(rc.MaxDelay) {
		return rc.MaxDelay
	}
	return time.Duration(delay)
}



const (
	remediatorVersion = "1.0.0"
	maxRetries        = 5
)

var (
	httpClient       *http.Client
	config           RemediationConfig
	logger           Logger
	remediatorID     string
	taskQueue        chan RemediationTask
	activeTasks      sync.Map
	taskMutex        sync.Mutex
)

func init() {
	httpClient = &http.Client{
		Timeout: 30 * time.Second,
	}

	// Generate unique remediator ID
	hostname, _ := os.Hostname()
	remediatorID = fmt.Sprintf("remediator-%s-%d", hostname, os.Getpid())
}

func main() {
	// Print startup banner
	PrintBanner()

	// Load configuration
	cfg, err := LoadConfig()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to load configuration: %v\n", err)
		os.Exit(1)
	}
	config = RemediationConfig{
		Port:           cfg.Port,
		CollectorURL:   cfg.GetAPIURL(),
		LogLevel:       cfg.LogLevel,
		MaxConcurrent:  cfg.MaxConcurrent,
		TaskQueueSize:  cfg.TaskQueueSize,
	}
	logger = NewLogger(cfg.LogLevel)

	logger.Info("Configuration loaded successfully", map[string]interface{}{
		"port":            config.Port,
		"collector_url":   config.CollectorURL,
		"max_concurrent":  config.MaxConcurrent,
		"task_queue_size": config.TaskQueueSize,
	})

	// Initialize task queue
	taskQueue = make(chan RemediationTask, config.TaskQueueSize)

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
		"remediator_id": remediatorID,
	})

	// Set up graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start worker goroutines for concurrent remediation execution
	for i := 0; i < config.MaxConcurrent; i++ {
		go remediationWorker(i)
	}

	logger.Info("Remediation workers started", map[string]interface{}{
		"worker_count": config.MaxConcurrent,
	})

	// Set up HTTP server for receiving tasks
	mux := http.NewServeMux()
	mux.HandleFunc("/remediator/tasks", handleGetTasks)
	mux.HandleFunc("/remediator/health", handleHealth)

	httpServer := &http.Server{
		Addr:         fmt.Sprintf(":%d", config.Port),
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Start HTTP server in a goroutine
	go func() {
		logger.Info("Starting HTTP server", map[string]interface{}{
			"port": config.Port,
		})

		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("HTTP server error", map[string]interface{}{
				"error": err.Error(),
			})
		}
	}()

	// Start periodic task polling from API
	go startTaskPolling()

	logger.Info("Vigil Remediator is ready", map[string]interface{}{
		"port":            config.Port,
		"remediator_id":   remediatorID,
		"max_concurrent":  config.MaxConcurrent,
	})

	// Wait for shutdown signal
	<-sigChan
	logger.Info("Received shutdown signal", map[string]interface{}{})

	// Graceful shutdown
	gracefulShutdown(httpServer)
	os.Exit(0)
}



// loadConfig loads configuration from environment and defaults
func loadConfig() RemediationConfig {
	// This function is deprecated - use LoadConfig() from config.go instead
	// Kept for backwards compatibility during transition
	config := RemediationConfig{
		Port:          8081,
		CollectorURL:  "http://localhost:8000",
		LogLevel:      "INFO",
		MaxConcurrent: 5,
		TaskQueueSize: 100,
	}
	return config
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

// handleGetTasks handles HTTP GET requests for new tasks
func handleGetTasks(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	logger.Debug("Received tasks request", map[string]interface{}{
		"remote_addr": r.RemoteAddr,
	})

	// Get query parameters
	limitStr := r.URL.Query().Get("limit")
	limit := 10
	if l, err := strconv.Atoi(limitStr); err == nil && l > 0 && l <= 50 {
		limit = l
	}

	// Fetch tasks from API
	tasks, err := fetchTasksFromAPI(limit)
	if err != nil {
		logger.Error("Failed to fetch tasks from API", map[string]interface{}{
			"error": err.Error(),
		})
		http.Error(w, "Failed to fetch tasks", http.StatusInternalServerError)
		return
	}

	// Queue tasks for execution
	for _, task := range tasks {
		select {
		case taskQueue <- task:
			logger.Debug("Task queued", map[string]interface{}{
				"task_id": task.ID,
				"action":  task.Action,
			})
		default:
			logger.Warn("Task queue full, dropping task", map[string]interface{}{
				"task_id": task.ID,
			})
		}
	}

	// Return response
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"tasks_received": len(tasks),
	})
}

// handleHealth handles health check requests
func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":       "healthy",
		"remediator_id": remediatorID,
		"version":      remediatorVersion,
		"active_tasks": getActiveTasks(),
	})
}

// getActiveTasks returns count of active remediation tasks
func getActiveTasks() int {
	count := 0
	activeTasks.Range(func(key, value interface{}) bool {
		count++
		return true
	})
	return count
}

// fetchTasksFromAPI retrieves pending tasks from the API
func fetchTasksFromAPI(limit int) ([]RemediationTask, error) {
	tasksURL := fmt.Sprintf("%s/remediator/tasks?limit=%d&remediator_id=%s", 
		config.CollectorURL, limit, remediatorID)

	resp, err := httpClient.Get(tasksURL)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch tasks: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API returned status %d", resp.StatusCode)
	}

	var response struct {
		Tasks []RemediationTask `json:"tasks"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, fmt.Errorf("failed to decode tasks: %w", err)
	}

	return response.Tasks, nil
}

// startTaskPolling periodically polls the API for new tasks
func startTaskPolling() {
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		tasks, err := fetchTasksFromAPI(20)
		if err != nil {
			logger.Warn("Task polling failed", map[string]interface{}{
				"error": err.Error(),
			})
			continue
		}

		for _, task := range tasks {
			select {
			case taskQueue <- task:
				logger.Debug("Task queued from polling", map[string]interface{}{
					"task_id": task.ID,
				})
			default:
				logger.Debug("Task queue full during polling", map[string]interface{}{})
			}
		}
	}
}

// remediationWorker processes remediation tasks from the queue
func remediationWorker(workerID int) {
	logger.Debug("Remediation worker started", map[string]interface{}{
		"worker_id": workerID,
	})

	for task := range taskQueue {
		logger.Info("Processing remediation task", map[string]interface{}{
			"task_id":   task.ID,
			"action":    task.Action,
			"resource":  task.Resource,
			"worker_id": workerID,
		})

		// Mark task as active
		activeTasks.Store(task.ID, true)

		// Execute remediation action
		startTime := time.Now()
		result := executeRemediationAction(&task)
		duration := time.Since(startTime).Milliseconds()

		result.Duration = int(duration)
		result.RemediatorID = remediatorID
		result.RemediatorVersion = remediatorVersion

		// Report result
		if err := reportRemediationResultWithRetry(&result); err != nil {
			logger.Error("Failed to report remediation result", map[string]interface{}{
				"error":   err.Error(),
				"task_id": task.ID,
			})
		} else {
			logger.Info("Remediation result reported", map[string]interface{}{
				"task_id":  task.ID,
				"status":   result.Status,
				"duration": duration,
			})
		}

		// Mark task as complete
		activeTasks.Delete(task.ID)
	}
}

// executeRemediationAction executes a specific remediation action with retry logic
func executeRemediationAction(task *RemediationTask) RemediationResult {
	result := RemediationResult{
		TaskID:    task.ID,
		Timestamp: time.Now().Unix(),
		Resource:  task.Resource,
		Namespace: task.Namespace,
		Action:    task.Action,
		Details:   make(map[string]interface{}),
	}

	// Configure retry based on task or defaults
	retryConfig := DefaultRetryConfig()
	if task.MaxRetries > 0 {
		retryConfig.MaxAttempts = task.MaxRetries
	}

	// Execute action with retry logic
	var lastError error
	for attempt := 0; attempt < retryConfig.MaxAttempts; attempt++ {
		result.RetryAttempts = attempt + 1
		
		// Execute the action
		switch task.Action {
		case "restart_pod":
			result = executeRestartPod(task, result)
		case "scale_deployment":
			result = executeScaleDeployment(task, result)
		case "apply_manifest":
			result = executeApplyManifest(task, result)
		case "cordon_node":
			result = executeCordonNode(task, result)
		case "execute_command":
			result = executeCommand(task, result)
		default:
			result.Status = "failed"
			result.ErrorMessage = fmt.Sprintf("Unknown action: %s", task.Action)
			result.Details["reason"] = "unsupported_action"
			return result // Don't retry unsupported actions
		}

		// Check if action succeeded
		if result.Status == "success" {
			if attempt > 0 {
				logger.Info("Remediation succeeded after retry", map[string]interface{}{
					"task_id":  task.ID,
					"action":   task.Action,
					"attempts": attempt + 1,
				})
			}
			return result
		}

		// Action failed, check if we should retry
		lastError = fmt.Errorf("%s", result.ErrorMessage)
		
		// Don't retry on certain error types
		if result.Details["reason"] == "missing_parameter" || 
		   result.Details["reason"] == "invalid_parameter" {
			logger.Warn("Non-retryable error encountered", map[string]interface{}{
				"task_id": task.ID,
				"action":  task.Action,
				"reason":  result.Details["reason"],
			})
			return result
		}

		// Calculate backoff for next attempt
		if attempt < retryConfig.MaxAttempts-1 {
			backoffDelay := retryConfig.CalculateBackoff(attempt)
			logger.Warn("Remediation failed, retrying with backoff", map[string]interface{}{
				"task_id":         task.ID,
				"action":          task.Action,
				"attempt":         attempt + 1,
				"max_attempts":    retryConfig.MaxAttempts,
				"backoff_seconds": backoffDelay.Seconds(),
				"error":           result.ErrorMessage,
			})
			time.Sleep(backoffDelay)
		}
	}

	// All retries exhausted
	logger.Error("Remediation failed after all retries", map[string]interface{}{
		"task_id":      task.ID,
		"action":       task.Action,
		"attempts":     retryConfig.MaxAttempts,
		"final_error":  lastError.Error(),
	})
	
	result.ErrorMessage = fmt.Sprintf("Failed after %d attempts: %s", retryConfig.MaxAttempts, lastError.Error())
	result.Details["retry_exhausted"] = true
	
	return result
}

// executeRestartPod restarts a Kubernetes pod
func executeRestartPod(task *RemediationTask, result RemediationResult) RemediationResult {
	podName, ok := task.Parameters["pod_name"].(string)
	if !ok || podName == "" {
		result.Status = "failed"
		result.ErrorMessage = "Missing pod_name parameter"
		result.Details["reason"] = "missing_parameter"
		return result
	}

	logger.Debug("Restarting pod", map[string]interface{}{
		"pod_name":  podName,
		"namespace": task.Namespace,
	})

	// Simulated pod restart (production would use Kubernetes client-go)
	result.Status = "success"
	result.Details["pod_name"] = podName
	result.Details["action_type"] = "kubernetes_pod_restart"

	return result
}

// executeScaleDeployment scales a Kubernetes deployment
func executeScaleDeployment(task *RemediationTask, result RemediationResult) RemediationResult {
	deploymentName, ok := task.Parameters["deployment_name"].(string)
	if !ok || deploymentName == "" {
		result.Status = "failed"
		result.ErrorMessage = "Missing deployment_name parameter"
		result.Details["reason"] = "missing_parameter"
		return result
	}

	replicas, ok := task.Parameters["replicas"].(float64)
	if !ok || replicas < 0 {
		result.Status = "failed"
		result.ErrorMessage = "Invalid replicas parameter"
		result.Details["reason"] = "invalid_parameter"
		return result
	}

	logger.Debug("Scaling deployment", map[string]interface{}{
		"deployment": deploymentName,
		"namespace":  task.Namespace,
		"replicas":   int(replicas),
	})

	result.Status = "success"
	result.Details["deployment_name"] = deploymentName
	result.Details["replicas"] = int(replicas)
	result.Details["action_type"] = "kubernetes_deployment_scale"

	return result
}

// executeApplyManifest applies a Kubernetes manifest
func executeApplyManifest(task *RemediationTask, result RemediationResult) RemediationResult {
	manifestContent, ok := task.Parameters["manifest"].(string)
	if !ok || manifestContent == "" {
		result.Status = "failed"
		result.ErrorMessage = "Missing manifest parameter"
		result.Details["reason"] = "missing_parameter"
		return result
	}

	logger.Debug("Applying manifest", map[string]interface{}{
		"namespace": task.Namespace,
		"length":    len(manifestContent),
	})

	result.Status = "success"
	result.Details["manifest_length"] = len(manifestContent)
	result.Details["action_type"] = "kubernetes_apply_manifest"

	return result
}

// executeCordonNode cordons a Kubernetes node
func executeCordonNode(task *RemediationTask, result RemediationResult) RemediationResult {
	nodeName, ok := task.Parameters["node_name"].(string)
	if !ok || nodeName == "" {
		result.Status = "failed"
		result.ErrorMessage = "Missing node_name parameter"
		result.Details["reason"] = "missing_parameter"
		return result
	}

	logger.Debug("Cordoning node", map[string]interface{}{
		"node_name": nodeName,
	})

	result.Status = "success"
	result.Details["node_name"] = nodeName
	result.Details["action_type"] = "kubernetes_node_cordon"

	return result
}

// executeCommand executes a custom command
func executeCommand(task *RemediationTask, result RemediationResult) RemediationResult {
	command, ok := task.Parameters["command"].(string)
	if !ok || command == "" {
		result.Status = "failed"
		result.ErrorMessage = "Missing command parameter"
		result.Details["reason"] = "missing_parameter"
		return result
	}

	logger.Debug("Executing command", map[string]interface{}{
		"command": command,
	})

	// Simulated command execution (production would use exec.Command with proper isolation)
	result.Status = "success"
	result.Details["command"] = command
	result.Details["action_type"] = "custom_command_execution"

	return result
}

// reportRemediationResultWithRetry reports result to API with exponential backoff retry
func reportRemediationResultWithRetry(result *RemediationResult) error {
	resultsURL := config.CollectorURL + "/remediator/results"
	retryConfig := DefaultRetryConfig()
	retryConfig.MaxAttempts = maxRetries

	var lastErr error
	for attempt := 0; attempt < retryConfig.MaxAttempts; attempt++ {
		err := reportRemediationResult(resultsURL, result)
		if err == nil {
			if attempt > 0 {
				logger.Info("Result reported successfully after retry", map[string]interface{}{
					"task_id":  result.TaskID,
					"attempts": attempt + 1,
				})
			}
			return nil
		}
		
		lastErr = err

		if attempt < retryConfig.MaxAttempts-1 {
			backoffDelay := retryConfig.CalculateBackoff(attempt)
			logger.Warn("Failed to report result, retrying with exponential backoff", map[string]interface{}{
				"attempt":         attempt + 1,
				"max_attempts":    retryConfig.MaxAttempts,
				"backoff_seconds": backoffDelay.Seconds(),
				"task_id":         result.TaskID,
				"error":           err.Error(),
			})
			time.Sleep(backoffDelay)
		}
	}

	logger.Error("Failed to report result after all retries", map[string]interface{}{
		"task_id":     result.TaskID,
		"attempts":    retryConfig.MaxAttempts,
		"final_error": lastErr.Error(),
	})

	return fmt.Errorf("failed to report result after %d attempts: %w", retryConfig.MaxAttempts, lastErr)
}

// reportRemediationResult sends a single result to the API via HTTP POST
func reportRemediationResult(url string, result *RemediationResult) error {
	jsonData, err := json.Marshal(result)
	if err != nil {
		return fmt.Errorf("failed to marshal result: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create HTTP request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", fmt.Sprintf("vigil-remediator/%s", remediatorVersion))

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
func gracefulShutdown(httpServer *http.Server) {
	logger.Info("Starting graceful shutdown", map[string]interface{}{})

	// Stop accepting new tasks
	close(taskQueue)

	// Wait for active tasks to complete (with timeout)
	shutdownTimeout := 30 * time.Second
	deadline := time.Now().Add(shutdownTimeout)

	logger.Info("Waiting for active tasks to complete", map[string]interface{}{
		"timeout_seconds": shutdownTimeout.Seconds(),
	})

	for {
		activeTasks := getActiveTasks()
		if activeTasks == 0 {
			break
		}

		if time.Now().After(deadline) {
			logger.Warn("Shutdown timeout reached with active tasks", map[string]interface{}{
				"active_tasks": activeTasks,
			})
			break
		}

		time.Sleep(100 * time.Millisecond)
	}

	// Shutdown HTTP server
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		logger.Error("HTTP server shutdown error", map[string]interface{}{
			"error": err.Error(),
		})
	}

	logger.Info("Remediator shutdown complete", map[string]interface{}{})
}
