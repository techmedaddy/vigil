import os
import glob
import time
import random
import requests
import yaml
import logging

# --- Configuration ---
COLLECTOR_URL = "http://127.0.0.1:8000/ingest"
MANIFEST_GLOB_PATH = "manifests/services/*.yaml"
METRIC_INTERVAL_SEC = 1.0
DRIFT_MIN_INTERVAL_SEC = 20
DRIFT_MAX_INTERVAL_SEC = 40

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---

def send_metric():
    """Generates and POSTs a single CPU metric to the collector."""
    try:
        # Generate a random value. Per prompt, 0-100.
        # This will frequently trigger alerts if policies look for > 0.8
        cpu_val = random.uniform(0.0, 100.0)
        
        payload = {
            "name": "cpu_usage",
            "value": cpu_val
        }
        
        response = requests.post(COLLECTOR_URL, json=payload, timeout=5)
        
        if response.status_code < 300:
            logging.info(f"Successfully sent metric: cpu_usage = {cpu_val:.2f}")
        else:
            logging.warning(f"Failed to send metric. Status: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        logging.error(f"Connection error: Could not connect to collector at {COLLECTOR_URL}")
    except Exception as e:
        logging.error(f"Error in send_metric: {e}")

def induce_drift():
    """
    Finds a random manifest file and modifies it to simulate GitOps drift.
    Uses safe_load and dump to preserve YAML structure and comments.
    """
    try:
        manifest_files = glob.glob(MANIFEST_GLOB_PATH)
        if not manifest_files:
            logging.warning(f"No manifest files found at '{MANIFEST_GLOB_PATH}'. Skipping drift.")
            return

        # Pick a random manifest file to modify
        target_file = random.choice(manifest_files)
        
        # Safely read the YAML
        with open(target_file, 'r') as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            logging.warning(f"Manifest {target_file} is not a valid dict. Skipping drift.")
            return

        # Simulate drift by adding/updating a top-level key or annotation
        # This is a safe modification that won't break manifests
        drift_key = "x_drift_simulation_timestamp"
        data[drift_key] = int(time.time())
        
        # Add a random annotation if 'metadata' and 'annotations' exist
        if 'metadata' in data and isinstance(data.get('metadata'), dict):
            if 'annotations' not in data['metadata'] or data['metadata']['annotations'] is None:
                data['metadata']['annotations'] = {}
            data['metadata']['annotations']['vigil-drift-test'] = f"trigger-{random.randint(1000, 9999)}"

        # Safely write the YAML back
        with open(target_file, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
            
        logging.info(f"DRIFT INDUCED: Modified {target_file}")

    except yaml.YAMLError as e:
        logging.error(f"YAML error processing {target_file}: {e}")
    except IOError as e:
        logging.error(f"File I/O error with {target_file}: {e}")
    except Exception as e:
        logging.error(f"Error in induce_drift: {e}")

# --- Main Loop ---

def main():
    """Runs the main simulation loop."""
    logging.info(f"Starting failure simulator...")
    logging.info(f" - Sending metrics to: {COLLECTOR_URL}")
    logging.info(f" - Inducing drift in:   {MANIFEST_GLOB_PATH}")
    
    last_drift_time = time.time()
    next_drift_delay = random.uniform(DRIFT_MIN_INTERVAL_SEC, DRIFT_MAX_INTERVAL_SEC)

    while True:
        try:
            # 1. Send metric every second
            send_metric()
            
            # 2. Check if it's time to induce drift
            current_time = time.time()
            if (current_time - last_drift_time) > next_drift_delay:
                induce_drift()
                last_drift_time = current_time
                next_drift_delay = random.uniform(DRIFT_MIN_INTERVAL_SEC, DRIFT_MAX_INTERVAL_SEC)
                logging.info(f"Next drift scheduled in {next_drift_delay:.1f} seconds.")

            # Wait for the next cycle
            time.sleep(METRIC_INTERVAL_SEC)
            
        except KeyboardInterrupt:
            logging.info("Simulation stopped by user.")
            break
        except Exception as e:
            logging.error(f"Unhandled error in main loop: {e}")
            time.sleep(5) # Avoid rapid-fire crashes

if __name__ == "__main__":
    main()