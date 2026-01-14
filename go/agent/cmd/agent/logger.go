package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"time"
)

// LogLevel represents the severity level of a log message
type LogLevel int

const (
	DEBUG LogLevel = iota
	INFO
	WARN
	ERROR
)

// logLevelNames maps log levels to their string representations
var logLevelNames = map[LogLevel]string{
	DEBUG: "DEBUG",
	INFO:  "INFO",
	WARN:  "WARN",
	ERROR: "ERROR",
}

// logLevelFromString converts a string to a LogLevel
func logLevelFromString(level string) LogLevel {
	switch strings.ToUpper(level) {
	case "DEBUG":
		return DEBUG
	case "INFO":
		return INFO
	case "WARN":
		return WARN
	case "ERROR":
		return ERROR
	default:
		return INFO
	}
}

// Logger provides structured logging
type Logger interface {
	Debug(message string, fields map[string]interface{})
	Info(message string, fields map[string]interface{})
	Warn(message string, fields map[string]interface{})
	Error(message string, fields map[string]interface{})
}

// StructuredLogger implements structured JSON logging
type StructuredLogger struct {
	level  LogLevel
	logger *log.Logger
}

// NewLogger creates a new structured logger
func NewLogger(levelStr string) Logger {
	return &StructuredLogger{
		level:  logLevelFromString(levelStr),
		logger: log.New(os.Stdout, "", 0),
	}
}

// logEntry represents a log entry in JSON format
type logEntry struct {
	Timestamp string                 `json:"timestamp"`
	Level     string                 `json:"level"`
	Message   string                 `json:"message"`
	Fields    map[string]interface{} `json:"fields,omitempty"`
}

// log outputs a log message at the specified level
func (sl *StructuredLogger) log(level LogLevel, message string, fields map[string]interface{}) {
	if level < sl.level {
		return
	}

	entry := logEntry{
		Timestamp: time.Now().Format(time.RFC3339Nano),
		Level:     logLevelNames[level],
		Message:   message,
		Fields:    fields,
	}

	jsonBytes, err := json.Marshal(entry)
	if err != nil {
		sl.logger.Printf("[ERROR] Failed to marshal log entry: %v\n", err)
		return
	}

	sl.logger.Println(string(jsonBytes))
}

// Debug logs a debug message
func (sl *StructuredLogger) Debug(message string, fields map[string]interface{}) {
	sl.log(DEBUG, message, fields)
}

// Info logs an info message
func (sl *StructuredLogger) Info(message string, fields map[string]interface{}) {
	sl.log(INFO, message, fields)
}

// Warn logs a warning message
func (sl *StructuredLogger) Warn(message string, fields map[string]interface{}) {
	sl.log(WARN, message, fields)
}

// Error logs an error message
func (sl *StructuredLogger) Error(message string, fields map[string]interface{}) {
	sl.log(ERROR, message, fields)
}

// PrintBanner prints a formatted banner to the console (not JSON)
func PrintBanner() {
	fmt.Println(`
╔═══════════════════════════════════════╗
║     Vigil Agent started               ║
║     Version: 1.0.0                    ║
║     Monitoring and Metrics Collection ║
╚═══════════════════════════════════════╝
`)
}
