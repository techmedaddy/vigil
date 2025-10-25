package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"time"
)

type Metric struct {
	Name  string  `json:"name"`
	Value float64 `json:"value"`
}

func main() {
	collectorURL := "http://127.0.0.1:8000/ingest"
	client := &http.Client{Timeout: 5 * time.Second}
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	r := rand.New(rand.NewSource(time.Now().UnixNano()))

	for range ticker.C {
		fmt.Println("sending metric...") // visible heartbeat
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

	resp, err := client.Post(url, "application/json", bytes.NewBuffer(payload))
	if err != nil {
		log.Printf("send error: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		log.Printf("metric sent successfully: %.3f", data.Value)
	} else {
		log.Printf("non-2xx response: %d", resp.StatusCode)
	}
}
