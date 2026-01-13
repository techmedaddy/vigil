import os
import glob
import time
import random
import requests
import yaml
import logging
import argparse
import json
from pathlib import Path

# --- Configuration ---
COLLECTOR_URL = "http://127.0.0.1:8000/ingest"
DRIFT_ENDPOINT = "http://127.0.0.1:8000/drift"
DEFAULT_BURST_SIZE = 5
DEFAULT_INJECTION_INTERVAL = 2.0
DEFAULT_DRIFT_MANIFEST = "manifests/services/web.service.yaml"
MAX_RETRIES = 3
RETRY_DELAY_SEC = 2.0

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def inject_cpu_burst(burst_size, interval):
    """
    Injects a burst of high CPU usage metrics to the collector.
    
    Args:
        burst_size (int): Number of high CPU metrics to send
        interval (float): Delay between metric injections in seconds
    """
    logger.info(f"[ANOMALY] Initiating CPU burst injection: {burst_size} spikes at {interval}s interval")
    
    for i in range(burst_size):
        # Generate randomized CPU value between 0.85 and 0.99 (85%-99% usage)
        cpu_val = random.uniform(0.85, 0.99)
        
        payload = {
            "name": "cpu_usage",
            "value": cpu_val * 100,  # Convert to percentage (85-99)
            "timestamp": time.time()
        }
        
        retries = 0
        while retries < MAX_RETRIES:
            try:
                response = requests.post(COLLECTOR_URL, json=payload, timeout=5)
                
                if response.status_code < 300:
                    logger.info(f"[SPIKE {i+1}/{burst_size}] CPU usage: {cpu_val*100:.2f}% - SUCCESS")
                    break
                else:
                    logger.warning(f"[SPIKE {i+1}/{burst_size}] Failed to send metric. Status: {response.status_code}")
                    if retries < MAX_RETRIES - 1:
                        logger.info(f"Retrying in {RETRY_DELAY_SEC}s...")
                        time.sleep(RETRY_DELAY_SEC)
                        retries += 1
                    else:
                        logger.error(f"[SPIKE {i+1}/{burst_size}] Max retries exceeded.")
                        
            except requests.exceptions.ConnectionError:
                logger.error(f"[SPIKE {i+1}/{burst_size}] Connection error: Could not reach collector at {COLLECTOR_URL}")
                if retries < MAX_RETRIES - 1:
                    logger.info(f"Retrying in {RETRY_DELAY_SEC}s...")
                    time.sleep(RETRY_DELAY_SEC)
                    retries += 1
                else:
                    logger.error(f"[SPIKE {i+1}/{burst_size}] Max retries exceeded.")
                    
            except requests.exceptions.Timeout:
                logger.error(f"[SPIKE {i+1}/{burst_size}] Request timeout while contacting collector")
                if retries < MAX_RETRIES - 1:
                    logger.info(f"Retrying in {RETRY_DELAY_SEC}s...")
                    time.sleep(RETRY_DELAY_SEC)
                    retries += 1
                else:
                    logger.error(f"[SPIKE {i+1}/{burst_size}] Max retries exceeded.")
                    
            except Exception as e:
                logger.error(f"[SPIKE {i+1}/{burst_size}] Error in inject_cpu_burst: {e}")
                break
        
        # Wait before next spike (except after last one)
        if i < burst_size - 1:
            time.sleep(interval)
    
    logger.info(f"[ANOMALY] CPU burst injection completed.")


def simulate_drift(manifest_path):
    """
    Simulates GitOps drift by POSTing manifest path and metadata to the drift endpoint.
    
    Args:
        manifest_path (str): Path to the manifest file to use for drift simulation
    """
    logger.info(f"[DRIFT] Initiating drift simulation with manifest: {manifest_path}")
    
    # Verify manifest exists
    if not os.path.exists(manifest_path):
        logger.error(f"[DRIFT] Manifest file not found: {manifest_path}")
        return
    
    try:
        # Read manifest metadata
        with open(manifest_path, 'r') as f:
            manifest_data = yaml.safe_load(f)
        
        if not isinstance(manifest_data, dict):
            logger.error(f"[DRIFT] Manifest is not a valid dict: {manifest_path}")
            return
        
        # Prepare drift payload
        drift_metadata = {
            "manifest_path": manifest_path,
            "timestamp": time.time(),
            "resource_kind": manifest_data.get("kind", "Unknown"),
            "resource_name": manifest_data.get("metadata", {}).get("name", "Unknown"),
            "drift_type": "simulated_anomaly"
        }
        
        payload = {
            "path": manifest_path,
            "metadata": drift_metadata
        }
        
        retries = 0
        while retries < MAX_RETRIES:
            try:
                response = requests.post(DRIFT_ENDPOINT, json=payload, timeout=5)
                
                if response.status_code < 300:
                    logger.info(f"[DRIFT] Drift simulation successful for {manifest_path} - Status: {response.status_code}")
                    break
                else:
                    logger.warning(f"[DRIFT] Failed to report drift. Status: {response.status_code}")
                    if retries < MAX_RETRIES - 1:
                        logger.info(f"Retrying in {RETRY_DELAY_SEC}s...")
                        time.sleep(RETRY_DELAY_SEC)
                        retries += 1
                    else:
                        logger.error(f"[DRIFT] Max retries exceeded for manifest: {manifest_path}")
                        
            except requests.exceptions.ConnectionError:
                logger.error(f"[DRIFT] Connection error: Could not reach drift endpoint at {DRIFT_ENDPOINT}")
                if retries < MAX_RETRIES - 1:
                    logger.info(f"Retrying in {RETRY_DELAY_SEC}s...")
                    time.sleep(RETRY_DELAY_SEC)
                    retries += 1
                else:
                    logger.error(f"[DRIFT] Max retries exceeded.")
                    
            except requests.exceptions.Timeout:
                logger.error(f"[DRIFT] Request timeout while contacting drift endpoint")
                if retries < MAX_RETRIES - 1:
                    logger.info(f"Retrying in {RETRY_DELAY_SEC}s...")
                    time.sleep(RETRY_DELAY_SEC)
                    retries += 1
                else:
                    logger.error(f"[DRIFT] Max retries exceeded.")
                    
            except Exception as e:
                logger.error(f"[DRIFT] Error in simulate_drift: {e}")
                break
    
    except yaml.YAMLError as e:
        logger.error(f"[DRIFT] YAML error processing {manifest_path}: {e}")
    except IOError as e:
        logger.error(f"[DRIFT] File I/O error with {manifest_path}: {e}")
    except Exception as e:
        logger.error(f"[DRIFT] Unexpected error in simulate_drift: {e}")


def main():
    """
    Orchestrator function that runs the failure simulation loop.
    Parses CLI arguments and executes fault injection scenarios.
    """
    parser = argparse.ArgumentParser(
        description="Advanced fault injection simulator for Vigil monitoring system"
    )
    parser.add_argument(
        "--burst",
        type=int,
        default=DEFAULT_BURST_SIZE,
        help=f"Number of CPU spikes to inject per burst (default: {DEFAULT_BURST_SIZE})"
    )
    parser.add_argument(
        "--drift",
        type=str,
        default=DEFAULT_DRIFT_MANIFEST,
        help=f"Path to manifest file for drift simulation (default: {DEFAULT_DRIFT_MANIFEST})"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INJECTION_INTERVAL,
        help=f"Delay between successive injections in seconds (default: {DEFAULT_INJECTION_INTERVAL})"
    )
    parser.add_argument(
        "--collector-url",
        type=str,
        default=COLLECTOR_URL,
        help=f"Collector API endpoint (default: {COLLECTOR_URL})"
    )
    parser.add_argument(
        "--drift-url",
        type=str,
        default=DRIFT_ENDPOINT,
        help=f"Drift endpoint URL (default: {DRIFT_ENDPOINT})"
    )
    
    args = parser.parse_args()
    
    # Update global endpoints if provided
    global COLLECTOR_URL, DRIFT_ENDPOINT
    COLLECTOR_URL = args.collector_url
    DRIFT_ENDPOINT = args.drift_url
    
    logger.info("=" * 70)
    logger.info("VIGIL ADVANCED FAULT INJECTION SIMULATOR")
    logger.info("=" * 70)
    logger.info(f"Configuration:")
    logger.info(f"  - Burst Size: {args.burst} spikes")
    logger.info(f"  - Injection Interval: {args.interval}s")
    logger.info(f"  - Drift Manifest: {args.drift}")
    logger.info(f"  - Collector URL: {COLLECTOR_URL}")
    logger.info(f"  - Drift Endpoint: {DRIFT_ENDPOINT}")
    logger.info("=" * 70)
    logger.info("Starting simulation... Press Ctrl+C to stop.")
    logger.info("=" * 70)
    
    try:
        while True:
            logger.info(f"\n[CYCLE] Starting new injection cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Inject CPU burst
            inject_cpu_burst(args.burst, args.interval)
            
            # Simulate drift
            simulate_drift(args.drift)
            
            # Wait for next cycle
            logger.info(f"[CYCLE] Waiting {args.interval}s before next cycle...\n")
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        logger.info("\n" + "=" * 70)
        logger.info("Simulation stopped by user. Shutting down gracefully.")
        logger.info("=" * 70)
    except Exception as e:
        logger.error(f"Unhandled error in main loop: {e}")
        logger.info("Attempting to recover in 5 seconds...")
        time.sleep(5)


if __name__ == "__main__":
    main()